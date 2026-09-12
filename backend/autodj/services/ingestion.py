"""Library ingestion.

Turns files on disk into validated ``tracks`` rows: hash, probe, prove the audio decodes, resolve
naming, persist. A file that cannot be used is recorded as FAILED with a structured reason instead
of aborting the scan.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.decode import (
    SourceError,
    SourceFailure,
    SourceMetadata,
    decode_to_mono,
    probe_source,
)
from autodj.audio.naming import TrackNaming, naming_from_filename, resolve_naming
from autodj.config.settings import Settings
from autodj.logging_config import get_logger
from autodj.persistence.database import session_scope
from autodj.persistence.repositories import TrackRepository

logger = get_logger(__name__)

HASH_CHUNK_BYTES = 1024 * 1024

# A file whose peak amplitude never exceeds this has nothing to mix. Chosen to sit above 16-bit
# dither noise (about 1.5e-5) and far below any audible content.
SILENCE_PEAK_FLOOR = 1e-4


class FileStatus(StrEnum):
    ADDED = "added"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FileOutcome:
    audio_path: str
    status: FileStatus
    failure: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class FilePreview:
    """How a file would be interpreted, without writing anything."""

    audio_path: str
    naming: TrackNaming | None
    duration_seconds: float | None
    failure: dict[str, str] | None = None


@dataclass(slots=True)
class IngestionReport:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def record(self, outcome: FileOutcome) -> None:
        self.scanned += 1
        match outcome.status:
            case FileStatus.ADDED:
                self.added += 1
            case FileStatus.UPDATED:
                self.updated += 1
            case FileStatus.UNCHANGED:
                self.unchanged += 1
            case FileStatus.FAILED:
                self.failed += 1
                reason = (outcome.failure or {}).get("reason", str(SourceFailure.DECODE_FAILED))
                self.failures.append((outcome.audio_path, reason))


def compute_content_hash(path: Path) -> str:
    """SHA-256 of the file bytes.

    Change detection only: a hash decides whether a known path needs revalidating. It is never
    used to look a file up, so it cannot merge two paths into one track.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


class LibraryIngestionService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._session_factory = session_factory

    @property
    def library_dir(self) -> Path:
        return self._settings.audio_library_dir.expanduser().resolve()

    def discover(self, library_dir: Path | None = None) -> list[Path]:
        """Every audio file under the library, in a deterministic order."""
        root = (library_dir or self.library_dir).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"audio library directory not found: {root}")

        ingestion = self._settings.ingestion
        files = [
            path
            for path in root.rglob("*")
            if path.is_file() and not path.name.startswith(".") and ingestion.matches(path.suffix)
        ]
        return sorted(files)

    def scan(self, library_dir: Path | None = None, *, recheck: bool = False) -> IngestionReport:
        root = (library_dir or self.library_dir).expanduser().resolve()
        started = time.perf_counter()
        report = IngestionReport()

        files = self.discover(root)
        logger.info("library_scan_started", library_dir=str(root), file_count=len(files))

        with session_scope(self._session_factory) as session:
            repository = TrackRepository(session)
            for path in files:
                report.record(self._ingest(repository, path, root, recheck=recheck))

        report.elapsed_seconds = time.perf_counter() - started
        logger.info(
            "library_scan_finished",
            library_dir=str(root),
            scanned=report.scanned,
            added=report.added,
            updated=report.updated,
            unchanged=report.unchanged,
            failed=report.failed,
            elapsed_seconds=round(report.elapsed_seconds, 3),
        )
        return report

    def preview(self, library_dir: Path | None = None) -> list[FilePreview]:
        """Show how each file's title and artist would be resolved, touching no database.

        Probe only: naming comes from tags when present, otherwise the filename, which is what a
        messy library needs checked before committing rows.
        """
        root = (library_dir or self.library_dir).expanduser().resolve()
        previews: list[FilePreview] = []
        for path in self.discover(root):
            relative_path = _relative_path(path, root)
            try:
                metadata = probe_source(
                    path, timeout=self._settings.ingestion.subprocess_timeout_seconds
                )
            except SourceError as error:
                previews.append(
                    FilePreview(
                        audio_path=relative_path,
                        naming=naming_from_filename(path.stem),
                        duration_seconds=None,
                        failure=error.as_dict(),
                    )
                )
                continue
            previews.append(
                FilePreview(
                    audio_path=relative_path,
                    naming=resolve_naming(metadata.tags, path.stem),
                    duration_seconds=metadata.duration_seconds,
                )
            )
        return previews

    def ingest_file(
        self, path: Path, library_dir: Path | None = None, *, recheck: bool = False
    ) -> FileOutcome:
        """Ingest one file in its own transaction."""
        root = (library_dir or self.library_dir).expanduser().resolve()
        with session_scope(self._session_factory) as session:
            return self._ingest(TrackRepository(session), path.resolve(), root, recheck=recheck)

    def _ingest(
        self, repository: TrackRepository, path: Path, root: Path, *, recheck: bool
    ) -> FileOutcome:
        relative_path = _relative_path(path, root)
        content_hash = compute_content_hash(path)

        existing = repository.get_by_path(relative_path)
        if (
            existing is not None
            and not recheck
            and existing.content_hash == content_hash
            and existing.failure_reason is None
        ):
            logger.debug("track_unchanged", audio_path=relative_path)
            return FileOutcome(relative_path, FileStatus.UNCHANGED)

        try:
            metadata = self._validate_source(path)
        except SourceError as error:
            repository.save_failure(
                audio_path=relative_path,
                content_hash=content_hash,
                naming=naming_from_filename(path.stem),
                failure=error.as_dict(),
            )
            logger.warning(
                "track_ingest_failed",
                audio_path=relative_path,
                reason=str(error.failure),
                detail=error.detail,
            )
            return FileOutcome(relative_path, FileStatus.FAILED, error.as_dict())

        naming = resolve_naming(metadata.tags, path.stem)
        _, created = repository.save_source(
            audio_path=relative_path,
            content_hash=content_hash,
            naming=naming,
            metadata=metadata,
        )
        logger.info(
            "track_ingested",
            audio_path=relative_path,
            created=created,
            title=naming.title,
            artist=naming.artist,
            metadata_source=str(naming.source),
            duration_seconds=round(metadata.duration_seconds, 3),
            native_sample_rate=metadata.sample_rate,
            channels=metadata.channels,
        )
        return FileOutcome(relative_path, FileStatus.ADDED if created else FileStatus.UPDATED)

    def _validate_source(self, path: Path) -> SourceMetadata:
        """Probe, then prove the audio actually decodes to usable samples."""
        ingestion = self._settings.ingestion
        metadata = probe_source(path, timeout=ingestion.subprocess_timeout_seconds)

        if metadata.duration_seconds < ingestion.min_duration_seconds:
            raise SourceError(
                SourceFailure.TOO_SHORT,
                f"{metadata.duration_seconds:.2f}s is below the "
                f"{ingestion.min_duration_seconds:g}s minimum",
            )

        samples = decode_to_mono(
            path,
            sample_rate=self._settings.analysis.sample_rate,
            max_seconds=ingestion.validation_seconds,
            timeout=ingestion.subprocess_timeout_seconds,
        )
        if _peak(samples) <= SILENCE_PEAK_FLOOR:
            self._reject_only_if_silent_throughout(path, metadata)
        return metadata

    def _reject_only_if_silent_throughout(self, path: Path, metadata: SourceMetadata) -> None:
        """Widen the window before calling a file silent.

        A quiet opening says nothing about a track: ambient intros, long fade-ins and exports
        padded with leading silence are all normal. Only a file with no audible content anywhere
        is unusable, so re-decode a much longer stretch and judge on that. This costs a second
        decode, but only for the rare file whose first seconds are silent.
        """
        ingestion = self._settings.ingestion
        window = min(ingestion.silence_scan_seconds, metadata.duration_seconds)
        samples = decode_to_mono(
            path,
            sample_rate=self._settings.analysis.sample_rate,
            max_seconds=window,
            timeout=ingestion.subprocess_timeout_seconds,
        )
        peak = _peak(samples)
        if peak <= SILENCE_PEAK_FLOOR:
            raise SourceError(
                SourceFailure.SILENT_AUDIO,
                f"peak amplitude {peak:.2e} across {window:g}s of audio is inaudible",
            )
        logger.info(
            "track_starts_silent",
            audio_path=path.name,
            silent_seconds_at_least=ingestion.validation_seconds,
        )


def _peak(samples: np.ndarray) -> float:
    return float(np.max(np.abs(samples)))


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()
