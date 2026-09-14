"""Offline analysis: beat grid, energy curve, and stable mixable regions.

Decodes a persisted track, runs the pure analyzers, and writes tempo, energy, confidence
and temporal features back. One file never aborts the batch: decode and tracking
failures become FAILED rows with a structured reason.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.beats import (
    AnalysisFailure,
    BeatAnalysis,
    BeatTrackingError,
    analyze_beats,
)
from autodj.audio.decode import SourceError, decode_to_mono
from autodj.audio.energy import EnergyAnalysis, analyze_energy
from autodj.audio.regions import RegionDetectionError, StableRegion, detect_stable_regions
from autodj.config.settings import Settings
from autodj.logging_config import get_logger
from autodj.persistence.database import session_scope
from autodj.persistence.repositories import TrackRepository

logger = get_logger(__name__)


class PipelineFailure(StrEnum):
    MISSING_FILE = "MISSING_FILE"
    UNEXPECTED = "UNEXPECTED"


class AnalysisOutcomeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class TrackFeatures:
    beats: BeatAnalysis
    energy: EnergyAnalysis
    regions: list[StableRegion]


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    audio_path: str
    status: AnalysisOutcomeStatus
    native_bpm: float | None = None
    confidence: float | None = None
    energy: float | None = None
    region_count: int | None = None
    failure: dict[str, str] | None = None


@dataclass(slots=True)
class AnalysisReport:
    selected: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    elapsed_seconds: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def record(self, outcome: AnalysisOutcome) -> None:
        match outcome.status:
            case AnalysisOutcomeStatus.COMPLETED:
                self.completed += 1
            case AnalysisOutcomeStatus.FAILED:
                self.failed += 1
                reason = (outcome.failure or {}).get("reason", str(PipelineFailure.UNEXPECTED))
                self.failures.append((outcome.audio_path, reason))
            case AnalysisOutcomeStatus.SKIPPED:
                self.skipped += 1


class LibraryAnalysisService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._session_factory = session_factory

    @property
    def library_dir(self) -> Path:
        return self._settings.audio_library_dir.expanduser().resolve()

    def analyze(
        self,
        library_dir: Path | None = None,
        *,
        reanalyze: bool = False,
        audio_path: str | None = None,
        limit: int | None = None,
    ) -> AnalysisReport:
        root = (library_dir or self.library_dir).expanduser().resolve()
        started = time.perf_counter()
        report = AnalysisReport()

        with session_scope(self._session_factory) as session:
            tracks = TrackRepository(session).list_for_analysis(
                analysis_version=self._settings.analysis.version,
                reanalyze=reanalyze,
                audio_path=audio_path,
                limit=limit,
            )
            jobs = [(track.id, track.audio_path) for track in tracks]

        report.selected = len(jobs)
        logger.info(
            "library_analysis_started",
            library_dir=str(root),
            selected=report.selected,
            reanalyze=reanalyze,
        )

        for track_id, relative_path in jobs:
            report.record(self._analyze_track(track_id, relative_path, root))

        if report.selected:
            self._rescale_library_energy()

        report.elapsed_seconds = time.perf_counter() - started
        logger.info(
            "library_analysis_finished",
            library_dir=str(root),
            selected=report.selected,
            completed=report.completed,
            failed=report.failed,
            skipped=report.skipped,
            elapsed_seconds=round(report.elapsed_seconds, 3),
        )
        return report

    def _analyze_track(self, track_id: int, relative_path: str, root: Path) -> AnalysisOutcome:
        with session_scope(self._session_factory) as session:
            repository = TrackRepository(session)
            track = repository.get_by_id(track_id)
            if track is None:
                return AnalysisOutcome(relative_path, AnalysisOutcomeStatus.SKIPPED)
            repository.mark_processing(track)

        path = (root / relative_path).resolve()
        if not path.is_file():
            failure = {
                "reason": str(PipelineFailure.MISSING_FILE),
                "detail": f"source file is missing: {relative_path}",
            }
            return self._persist_failure(track_id, relative_path, failure)

        try:
            features = self._run_analysis(path)
        except SourceError as error:
            logger.warning(
                "track_analysis_failed",
                audio_path=relative_path,
                reason=str(error.failure),
                detail=error.detail,
            )
            return self._persist_failure(track_id, relative_path, error.as_dict())
        except BeatTrackingError as error:
            logger.warning(
                "track_analysis_failed",
                audio_path=relative_path,
                reason=str(error.failure),
                detail=error.detail,
            )
            return self._persist_failure(track_id, relative_path, error.as_dict())
        except RegionDetectionError as error:
            logger.warning(
                "track_analysis_failed",
                audio_path=relative_path,
                reason=str(error.failure),
                detail=error.detail,
            )
            return self._persist_failure(track_id, relative_path, error.as_dict())
        except Exception as error:
            logger.exception("track_analysis_unexpected", audio_path=relative_path)
            failure = {
                "reason": str(PipelineFailure.UNEXPECTED),
                "detail": f"{type(error).__name__}: {error}",
            }
            return self._persist_failure(track_id, relative_path, failure)

        with session_scope(self._session_factory) as session:
            repository = TrackRepository(session)
            track = repository.get_by_id(track_id)
            if track is None:
                return AnalysisOutcome(relative_path, AnalysisOutcomeStatus.SKIPPED)
            repository.save_analysis(
                track,
                features.beats,
                features.energy,
                features.regions,
                version=self._settings.analysis.version,
            )

        logger.info(
            "track_analysis_completed",
            audio_path=relative_path,
            native_bpm=round(features.beats.native_bpm, 3),
            confidence=round(features.beats.confidence, 3),
            energy=round(features.energy.scalar, 3),
            beat_count=int(features.beats.beat_times.size),
            region_count=len(features.regions),
            tempo_octave_factor=features.beats.tempo_octave_factor,
            analysis_version=self._settings.analysis.version,
        )
        return AnalysisOutcome(
            relative_path,
            AnalysisOutcomeStatus.COMPLETED,
            native_bpm=features.beats.native_bpm,
            confidence=features.beats.confidence,
            energy=features.energy.scalar,
            region_count=len(features.regions),
        )

    def _run_analysis(self, path: Path) -> TrackFeatures:
        settings = self._settings
        samples = decode_to_mono(
            path,
            sample_rate=settings.analysis.sample_rate,
            timeout=settings.ingestion.subprocess_timeout_seconds,
        )
        beats = analyze_beats(
            samples,
            sample_rate=settings.analysis.sample_rate,
            hop_length=settings.analysis.hop_length,
            refine_hop_length=settings.analysis.refine_hop_length,
            start_bpm=settings.analysis.start_bpm,
            min_bpm=settings.analysis.min_bpm,
            max_bpm=settings.analysis.max_bpm,
            min_beats=settings.analysis.min_beats,
            max_ibi_cv=settings.analysis.max_ibi_cv,
            min_onset_contrast=settings.analysis.min_onset_contrast,
            min_confidence=settings.analysis.min_confidence,
            refine_search_radius_frames=settings.analysis.refine_search_radius_frames,
        )
        energy = analyze_energy(
            samples,
            sample_rate=settings.analysis.sample_rate,
            hop_length=settings.analysis.hop_length,
            alpha=settings.energy.alpha,
            rms_floor_db=settings.energy.rms_floor_db,
            rms_ceiling_db=settings.energy.rms_ceiling_db,
            curve_hz=settings.energy.curve_hz,
            aggregation=settings.energy.aggregation,
            onset_low_percentile=settings.energy.normalization_low_percentile,
            onset_high_percentile=settings.energy.normalization_high_percentile,
        )
        regions = detect_stable_regions(
            beats.beat_times,
            onset_unit=energy.onset_unit,
            sample_rate=energy.sample_rate,
            hop_length=energy.hop_length,
            energy_curve=energy.curve,
            energy_curve_hz=energy.curve_hz,
            window_beats=settings.stable_regions.window_beats,
            step_beats=settings.stable_regions.step_beats,
            ibi_cv_max=settings.stable_regions.ibi_cv_max,
            ibi_tolerance=settings.stable_regions.ibi_tolerance,
            in_tolerance_fraction_min=settings.stable_regions.in_tolerance_fraction_min,
            onset_strength_floor=settings.stable_regions.onset_strength_floor,
            max_regions_per_track=settings.stable_regions.max_regions_per_track,
            weight_tempo_consistency=settings.stable_regions.weight_tempo_consistency,
            weight_onset_strength=settings.stable_regions.weight_onset_strength,
            weight_in_tolerance=settings.stable_regions.weight_in_tolerance,
        )
        return TrackFeatures(beats=beats, energy=energy, regions=regions)

    def _rescale_library_energy(self) -> None:
        energy = self._settings.energy
        with session_scope(self._session_factory) as session:
            TrackRepository(session).rescale_library_energy(
                low_percentile=energy.normalization_low_percentile,
                high_percentile=energy.normalization_high_percentile,
                analysis_version=self._settings.analysis.version,
            )

    def _persist_failure(
        self, track_id: int, relative_path: str, failure: dict[str, str]
    ) -> AnalysisOutcome:
        with session_scope(self._session_factory) as session:
            repository = TrackRepository(session)
            track = repository.get_by_id(track_id)
            if track is None:
                return AnalysisOutcome(relative_path, AnalysisOutcomeStatus.SKIPPED)
            repository.save_analysis_failure(track, failure)
        return AnalysisOutcome(relative_path, AnalysisOutcomeStatus.FAILED, failure=failure)


# Re-export for callers that persist a reason without importing the DSP module.
__all__ = [
    "AnalysisFailure",
    "AnalysisOutcome",
    "AnalysisOutcomeStatus",
    "AnalysisReport",
    "LibraryAnalysisService",
    "PipelineFailure",
    "TrackFeatures",
]
