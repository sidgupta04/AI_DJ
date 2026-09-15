"""Render service: decode stems, mix a TransitionPlan, write a WAV, persist the row.

The only layer that composes persistence, ``autodj.dj`` plans, and ``autodj.render``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.decode import SourceError, decode_to_pcm
from autodj.config.settings import Settings
from autodj.dj.types import TransitionPlan
from autodj.logging_config import get_logger
from autodj.persistence.database import session_scope
from autodj.persistence.models import TransitionStatus
from autodj.persistence.repositories import TrackRepository, TransitionRepository
from autodj.render.mix import render_transition
from autodj.render.stretch import build_stretcher
from autodj.render.types import RenderedMix, RenderError, RenderFailure
from autodj.render.write import write_pcm16_wav

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Outcome of rendering one planned transition."""

    transition_id: int
    status: TransitionStatus
    wav_path: Path | None
    peak_dbfs: float | None
    peak_exceeded: bool
    clipped: bool
    failure: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class _Stem:
    track_id: int
    path: Path
    native_bpm: float
    beat_times: np.ndarray


class RenderService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._session_factory = session_factory

    @property
    def library_dir(self) -> Path:
        return self._settings.audio_library_dir.expanduser().resolve()

    @property
    def cache_dir(self) -> Path:
        return self._settings.render_cache_dir.expanduser().resolve()

    def render_plan(
        self,
        plan: TransitionPlan,
        *,
        output_path: Path | None = None,
    ) -> RenderResult:
        """Render ``plan`` to a 16-bit WAV and insert a ``transitions`` row.

        A ``RENDERED`` row is written only after the WAV is complete at the
        published path. Any failure unlinks that attempt's file (and any
        sibling ``.tmp``) and stores ``FAILED`` with no ``wav_path``.
        """
        destination = output_path if output_path is not None else self._default_wav_path(plan)
        try:
            mix = self._mix(plan)
            write_pcm16_wav(destination, mix.audio, sample_rate=mix.sample_rate)
        except RenderError as error:
            self._discard_attempt(destination)
            return self._persist(plan, status=TransitionStatus.FAILED, failure=error.as_dict())
        except SourceError as error:
            self._discard_attempt(destination)
            return self._persist(
                plan,
                status=TransitionStatus.FAILED,
                failure={
                    "reason": str(RenderFailure.DECODE_FAILED),
                    "detail": error.detail,
                },
            )
        except OSError as error:
            self._discard_attempt(destination)
            return self._persist(
                plan,
                status=TransitionStatus.FAILED,
                failure=RenderError(RenderFailure.WRITE_FAILED, str(error)).as_dict(),
            )

        try:
            result = self._persist(
                plan,
                status=TransitionStatus.RENDERED,
                wav_path=self._stored_wav_path(destination),
                peak_dbfs=mix.peak_dbfs,
                peak_exceeded=mix.peak_exceeded,
                clipped=mix.clipped,
                absolute_wav=destination,
            )
        except Exception:
            self._discard_attempt(destination)
            raise

        logger.info(
            "transition_rendered",
            track_a_id=plan.track_a_id,
            track_b_id=plan.track_b_id,
            stretch_ratio=round(plan.stretch_ratio, 4),
            wav_path=str(destination),
            peak_dbfs=round(mix.peak_dbfs, 2),
            peak_exceeded=mix.peak_exceeded,
            clipped=mix.clipped,
            frames=int(mix.audio.shape[0]),
        )
        return result

    def _mix(self, plan: TransitionPlan) -> RenderedMix:
        stem_a, stem_b = self._load_stems(plan)
        settings = self._settings
        timeout = settings.ingestion.subprocess_timeout_seconds
        render_rate = settings.render.sample_rate
        render_channels = settings.render.channels
        outgoing = decode_to_pcm(
            stem_a.path,
            sample_rate=render_rate,
            channels=render_channels,
            timeout=timeout,
        )
        incoming = decode_to_pcm(
            stem_b.path,
            sample_rate=render_rate,
            channels=render_channels,
            timeout=timeout,
        )
        stretcher = build_stretcher(settings.tempo.stretch_backend)
        return render_transition(
            outgoing,
            incoming,
            outgoing_beat_times=stem_a.beat_times,
            incoming_beat_times=stem_b.beat_times,
            outgoing_native_bpm=stem_a.native_bpm,
            incoming_native_bpm=stem_b.native_bpm,
            session_bpm=plan.session_bpm,
            outgoing_start_beat=plan.outgoing_region.start_beat,
            outgoing_end_beat=plan.outgoing_region.end_beat,
            incoming_start_beat=plan.incoming_region.start_beat,
            incoming_end_beat=plan.incoming_region.end_beat,
            stretcher=stretcher,
            sample_rate=render_rate,
            channels=render_channels,
            min_stretch_ratio=settings.tempo.min_stretch_ratio,
            max_stretch_ratio=settings.tempo.max_stretch_ratio,
            crossfade_beats=settings.transition.crossfade_beats,
            margin_beats=settings.transition.margin_beats,
            align_on_downbeat=settings.transition.align_on_downbeat,
            peak_ceiling_dbfs=settings.render.peak_ceiling_dbfs,
        )

    def _load_stems(self, plan: TransitionPlan) -> tuple[_Stem, _Stem]:
        with session_scope(self._session_factory) as session:
            repository = TrackRepository(session)
            stem_a = self._stem(repository, plan.track_a_id)
            stem_b = self._stem(repository, plan.track_b_id)
        return stem_a, stem_b

    def _stem(self, repository: TrackRepository, track_id: int) -> _Stem:
        track = repository.get_by_id(track_id)
        analysis = repository.get_analysis(track_id)
        if track is None or analysis is None or track.native_bpm is None:
            raise RenderError(
                RenderFailure.MISSING_TRACK,
                f"track {track_id} is missing source metadata or analysis",
            )
        path = self.library_dir / track.audio_path
        if not path.is_file():
            raise RenderError(RenderFailure.MISSING_FILE, f"source file not found: {path}")
        return _Stem(
            track_id=track.id,
            path=path,
            native_bpm=track.native_bpm,
            beat_times=np.asarray(analysis.beat_times, dtype=np.float64),
        )

    def _default_wav_path(self, plan: TransitionPlan) -> Path:
        name = (
            f"a{plan.track_a_id}_b{plan.track_b_id}"
            f"_out{plan.outgoing_region.start_beat}"
            f"_in{plan.incoming_region.start_beat}.wav"
        )
        return self.cache_dir / "transitions" / name

    def _stored_wav_path(self, absolute: Path) -> str:
        """Prefer a path relative to the render cache; fall back to absolute."""
        try:
            return str(absolute.resolve().relative_to(self.cache_dir))
        except ValueError:
            return str(absolute)

    def _discard_attempt(self, destination: Path) -> None:
        """Remove a failed publish attempt so it cannot be treated as a valid mix."""
        destination.unlink(missing_ok=True)
        for orphan in destination.parent.glob(f".{destination.name}.*.tmp"):
            orphan.unlink(missing_ok=True)

    def _persist(
        self,
        plan: TransitionPlan,
        *,
        status: TransitionStatus,
        wav_path: str | None = None,
        peak_dbfs: float | None = None,
        peak_exceeded: bool = False,
        clipped: bool = False,
        failure: dict[str, str] | None = None,
        absolute_wav: Path | None = None,
    ) -> RenderResult:
        with session_scope(self._session_factory) as session:
            row = TransitionRepository(session).save(
                track_a_id=plan.track_a_id,
                track_b_id=plan.track_b_id,
                session_bpm=plan.session_bpm,
                stretch_ratio=plan.stretch_ratio,
                outgoing_start_beat=plan.outgoing_region.start_beat,
                outgoing_end_beat=plan.outgoing_region.end_beat,
                incoming_start_beat=plan.incoming_region.start_beat,
                incoming_end_beat=plan.incoming_region.end_beat,
                pair_cost=plan.pair_cost,
                stability_cost=plan.stability_cost,
                energy_cost=plan.energy_cost,
                stretch_cost=plan.stretch_cost,
                position_cost=plan.position_cost,
                status=status,
                config_snapshot=self._settings.snapshot(),
                wav_path=wav_path,
                peak_dbfs=peak_dbfs,
                peak_exceeded=peak_exceeded,
                clipped=clipped,
                failure_reason=failure,
            )
            transition_id = row.id
        if status is TransitionStatus.FAILED:
            logger.warning(
                "transition_render_failed",
                track_a_id=plan.track_a_id,
                track_b_id=plan.track_b_id,
                reason=(failure or {}).get("reason"),
            )
        return RenderResult(
            transition_id=transition_id,
            status=status,
            wav_path=absolute_wav,
            peak_dbfs=peak_dbfs,
            peak_exceeded=peak_exceeded,
            clipped=clipped,
            failure=failure,
        )
