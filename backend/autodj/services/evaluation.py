"""Offline model-ladder evaluation. Services alone compose DJ, rendering and metrics."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.decode import SourceError, decode_to_pcm
from autodj.config.settings import Settings
from autodj.dj.baselines import Strategy, baseline_order
from autodj.dj.plan import plan_transition
from autodj.dj.rank import rank_candidates
from autodj.dj.retrieve import retrieve_candidates
from autodj.dj.types import RegionInfo, TrackCandidate, TransitionPlan
from autodj.metrics.transition import alignment_error, energy_discontinuity_db
from autodj.persistence.database import session_scope
from autodj.persistence.models import TransitionStatus
from autodj.persistence.repositories import TrackRepository, TransitionRepository
from autodj.render.mix import render_transition
from autodj.render.stretch import build_stretcher
from autodj.render.types import RenderedMix, RenderError, RenderFailure
from autodj.render.write import write_pcm16_wav
from autodj.services.selection import candidate_from_row


@dataclass(frozen=True)
class EvaluationChoice:
    track: TrackCandidate
    plan: TransitionPlan
    outgoing_seconds: float | None = None
    incoming_seconds: float | None = None


def choose_transition(
    settings: Settings,
    current: TrackCandidate,
    candidates: list[TrackCandidate],
    *,
    strategy: Strategy,
    seed: int,
    paired_track: TrackCandidate | None = None,
) -> EvaluationChoice | None:
    """One transition, not a session. Paired mode fixes B so blind B/D compares identical audio."""
    tempo, retrieval, ranking, transition = (
        settings.tempo,
        settings.retrieval,
        settings.ranking,
        settings.transition,
    )
    pool = retrieve_candidates(
        current,
        [paired_track] if paired_track else candidates,
        set(),
        session_bpm=current.native_bpm,
        min_stretch_ratio=tempo.min_stretch_ratio,
        max_stretch_ratio=tempo.max_stretch_ratio,
        max_energy_delta=retrieval.max_energy_delta,
        energy_filter_enabled=strategy == Strategy.FULL and retrieval.energy_filter_enabled,
        require_stable_region=strategy == Strategy.FULL and retrieval.require_stable_region,
        allow_repeats=False,
    )
    if strategy == Strategy.FULL:
        ordered = [
            item.candidate
            for item in rank_candidates(
                current,
                pool,
                session_bpm=current.native_bpm,
                min_stretch_ratio=tempo.min_stretch_ratio,
                max_stretch_ratio=tempo.max_stretch_ratio,
                weight_tempo=ranking.weight_tempo,
                weight_energy=ranking.weight_energy,
                weight_quality=ranking.weight_quality,
            )
        ]
        for candidate in ordered:
            plan = plan_transition(
                current,
                candidate,
                session_bpm=current.native_bpm,
                min_stretch_ratio=tempo.min_stretch_ratio,
                max_stretch_ratio=tempo.max_stretch_ratio,
                outgoing_search_fraction=transition.outgoing_search_fraction,
                incoming_search_fraction=transition.incoming_search_fraction,
                weight_stability=transition.weight_stability,
                weight_energy=transition.weight_energy,
                weight_stretch=transition.weight_stretch,
                weight_position=transition.weight_position,
            )
            if plan is not None:
                return EvaluationChoice(candidate, plan)
        return None
    ordered = baseline_order(
        current,
        pool,
        strategy=strategy,
        seed=seed,
        session_bpm=current.native_bpm,
        min_stretch_ratio=tempo.min_stretch_ratio,
        max_stretch_ratio=tempo.max_stretch_ratio,
        weight_tempo=ranking.weight_tempo,
        weight_energy=ranking.weight_energy,
    )
    if not ordered:
        return None
    candidate = ordered[0]
    fade = transition.crossfade_beats * 60 / current.native_bpm
    margin = transition.margin_beats * 60 / current.native_bpm
    out_time = max(0.0, current.duration_seconds - fade - margin)
    in_time = margin
    # Sentinel beat indices describe a time-based baseline, not detected stable regions.
    out_region = RegionInfo(0, 1, out_time, out_time + fade, 0.0, 0.0, current.energy)
    in_region = RegionInfo(0, 1, in_time, in_time + fade, 0.0, 0.0, candidate.energy)
    plan = TransitionPlan(
        current.track_id,
        candidate.track_id,
        current.native_bpm,
        out_region,
        in_region,
        current.native_bpm / candidate.native_bpm,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
    return EvaluationChoice(candidate, plan, out_time, in_time)


class EvaluationService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def load_candidates(self) -> list[TrackCandidate]:
        if self.session_factory is None:
            raise ValueError("database required to load library candidates")
        with session_scope(self.session_factory) as session:
            rows = TrackRepository(session).list_candidates(
                analysis_version=self.settings.analysis.version
            )
        return [candidate_from_row(row) for row in rows]

    def evaluate(
        self,
        current: TrackCandidate,
        candidates: list[TrackCandidate],
        *,
        strategy: Strategy,
        seed: int,
        output: Path,
        paired_track: TrackCandidate | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        choice = choose_transition(
            self.settings,
            current,
            candidates,
            strategy=strategy,
            seed=seed,
            paired_track=paired_track,
        )
        record: dict[str, Any] = {
            "strategy": str(strategy),
            "seed": seed,
            "track_a_id": current.track_id,
            "track_b_id": choice.track.track_id
            if choice
            else (paired_track.track_id if paired_track else None),
            "planning_seconds": time.perf_counter() - started,
            "status": "FAILED",
            "failure_reason": "NO_PLAN",
            "wav_path": None,
        }
        if choice is None:
            return record
        record.update(
            {
                "plan": asdict(choice.plan),
                "outgoing_seconds": choice.outgoing_seconds,
                "incoming_seconds": choice.incoming_seconds,
                "bpm_delta": abs(current.native_bpm - choice.track.native_bpm),
                "stretch_percent_a": 0.0,
                "stretch_percent_b": 100 * (choice.plan.stretch_ratio - 1),
                "region_stability_a": choice.plan.outgoing_region.score
                if strategy == Strategy.FULL
                else None,
                "region_stability_b": choice.plan.incoming_region.score
                if strategy == Strategy.FULL
                else None,
            }
        )
        started = time.perf_counter()
        published = False
        timing_field = "render_seconds"
        try:
            if output.exists():
                raise FileExistsError(f"evaluation output already exists: {output}")
            mix = self._render(current, choice)
            write_pcm16_wav(output, mix.audio, sample_rate=mix.sample_rate)
            published = True
            record["render_seconds"] = time.perf_counter() - started
            started = time.perf_counter()
            timing_field = "measurement_seconds"
            record.update(self._measure(mix, choice.plan.session_bpm))
            record.update(
                {
                    "measurement_seconds": time.perf_counter() - started,
                    "status": "RENDERED",
                    "failure_reason": None,
                    "wav_path": str(output.resolve()),
                    "peak_dbfs": mix.peak_dbfs,
                    "peak_exceeded": mix.peak_exceeded,
                    "clipped": mix.clipped,
                    "fade_start_sample": mix.fade_start_sample,
                    "fade_frames": mix.fade_frames,
                    "sample_rate": mix.sample_rate,
                    "frames": len(mix.audio),
                }
            )
        except Exception as error:
            if published:
                output.unlink(missing_ok=True)
            record[timing_field] = time.perf_counter() - started
            record["failure_reason"] = (
                str(error.failure)
                if isinstance(error, (SourceError, RenderError))
                else type(error).__name__
            )
            record["failure_detail"] = str(error)
        if self.session_factory is not None:
            try:
                self._persist(choice.plan, record)
            except Exception:
                if published:
                    output.unlink(missing_ok=True)
                raise
        return record

    def _render(self, current: TrackCandidate, choice: EvaluationChoice) -> RenderedMix:
        cfg = self.settings
        tracks = [current, choice.track]
        audio = [
            decode_to_pcm(
                cfg.audio_library_dir / track.audio_path,
                sample_rate=cfg.render.sample_rate,
                channels=cfg.render.channels,
                timeout=cfg.ingestion.subprocess_timeout_seconds,
            )
            for track in tracks
        ]
        plan = choice.plan
        mix = render_transition(
            audio[0],
            audio[1],
            outgoing_beat_times=np.asarray(current.beat_times),
            incoming_beat_times=np.asarray(choice.track.beat_times),
            outgoing_native_bpm=current.native_bpm,
            incoming_native_bpm=choice.track.native_bpm,
            session_bpm=plan.session_bpm,
            outgoing_start_beat=plan.outgoing_region.start_beat,
            outgoing_end_beat=plan.outgoing_region.end_beat,
            incoming_start_beat=plan.incoming_region.start_beat,
            incoming_end_beat=plan.incoming_region.end_beat,
            stretcher=build_stretcher(cfg.tempo.stretch_backend),
            sample_rate=cfg.render.sample_rate,
            channels=cfg.render.channels,
            min_stretch_ratio=cfg.tempo.min_stretch_ratio,
            max_stretch_ratio=cfg.tempo.max_stretch_ratio,
            crossfade_beats=cfg.transition.crossfade_beats,
            margin_beats=cfg.transition.margin_beats,
            align_on_downbeat=cfg.transition.align_on_downbeat,
            peak_ceiling_dbfs=cfg.render.peak_ceiling_dbfs,
            outgoing_start_seconds=choice.outgoing_seconds,
            incoming_start_seconds=choice.incoming_seconds,
            context_seconds=cfg.evaluation.excerpt_seconds,
            retain_overlap=True,
        )
        expected = round(cfg.transition.crossfade_beats * 60 / plan.session_bpm * mix.sample_rate)
        if mix.fade_frames != expected:
            raise RenderError(
                RenderFailure.INSUFFICIENT_AUDIO, "evaluation requires a full overlap"
            )
        return mix

    def _measure(self, mix: RenderedMix, bpm: float) -> dict[str, Any]:
        cfg = self.settings.evaluation
        assert mix.outgoing_overlap is not None and mix.incoming_overlap is not None
        alignment = alignment_error(
            mix.outgoing_overlap,
            mix.incoming_overlap,
            sample_rate=mix.sample_rate,
            hop_ms=cfg.onset_hop_ms,
            max_lag_ms=cfg.alignment_max_lag_ms,
            session_bpm=bpm,
            min_correlation=cfg.alignment_min_correlation,
            silence_floor_dbfs=cfg.silence_floor_dbfs,
        )
        overlap = mix.audio[mix.fade_start_sample : mix.fade_start_sample + mix.fade_frames]
        return {
            "alignment_error_ms": alignment.error_ms,
            "alignment_correlation": alignment.correlation,
            "alignment_unavailable_reason": alignment.reason,
            "energy_discontinuity_db": energy_discontinuity_db(
                overlap,
                sample_rate=mix.sample_rate,
                window_seconds=cfg.energy_window_seconds,
                floor_dbfs=cfg.silence_floor_dbfs,
            ),
        }

    def _persist(self, plan: TransitionPlan, record: dict[str, Any]) -> None:
        assert self.session_factory is not None
        with session_scope(self.session_factory) as session:
            repository = TransitionRepository(session)
            row = repository.save(
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
                status=TransitionStatus(record["status"]),
                config_snapshot=self.settings.snapshot(),
                wav_path=record["wav_path"],
                peak_dbfs=record.get("peak_dbfs"),
                peak_exceeded=record.get("peak_exceeded", False),
                clipped=record.get("clipped", False),
                failure_reason={"reason": record["failure_reason"]}
                if record["failure_reason"]
                else None,
            )
            record["transition_id"] = row.id
            repository.attach_evaluation(row, record)
