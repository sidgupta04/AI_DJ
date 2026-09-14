"""Selection service: orchestrates candidate retrieval, ranking, and transition planning.

This is the only layer that composes persistence with the pure ``autodj.dj`` modules.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from autodj.config.settings import Settings
from autodj.dj.plan import plan_transition
from autodj.dj.rank import rank_candidates
from autodj.dj.retrieve import retrieve_candidates
from autodj.dj.types import (
    RankedCandidate,
    RegionInfo,
    TrackCandidate,
    TransitionPlan,
)
from autodj.logging_config import get_logger
from autodj.persistence.database import session_scope
from autodj.persistence.repositories import TrackRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Outcome of a full selection run: next track and transition plan."""

    current_track: TrackCandidate
    ranked: list[RankedCandidate]
    plan: TransitionPlan | None
    relaxed: bool


class SelectionService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._session_factory = session_factory

    def select_next(
        self,
        current_track_id: int,
        played_ids: set[int] | None = None,
        *,
        session_bpm: float | None = None,
    ) -> SelectionResult:
        """Choose the next track and plan the transition from ``current_track_id``.

        ``session_bpm`` defaults to the current track's native BPM (V1 default).
        ``played_ids`` should include every track already played in the session.
        """
        if played_ids is None:
            played_ids = set()

        all_candidates = self._load_candidates()

        current_track = _find_track(all_candidates, current_track_id)
        if current_track is None:
            raise ValueError(f"current track {current_track_id} is not a COMPLETE analysed track")

        if session_bpm is None:
            session_bpm = current_track.native_bpm

        retrieval_cfg = self._settings.retrieval
        tempo_cfg = self._settings.tempo

        retrieved = retrieve_candidates(
            current_track,
            all_candidates,
            played_ids,
            session_bpm=session_bpm,
            min_stretch_ratio=tempo_cfg.min_stretch_ratio,
            max_stretch_ratio=tempo_cfg.max_stretch_ratio,
            max_energy_delta=retrieval_cfg.max_energy_delta,
            energy_filter_enabled=retrieval_cfg.energy_filter_enabled,
            require_stable_region=retrieval_cfg.require_stable_region,
            allow_repeats=retrieval_cfg.allow_repeats,
        )

        relaxed = (
            len(retrieved) > 0
            and all(
                abs(c.energy - current_track.energy) > retrieval_cfg.max_energy_delta
                for c in retrieved
            )
            if retrieval_cfg.energy_filter_enabled
            else False
        )

        ranking_cfg = self._settings.ranking
        ranked = rank_candidates(
            current_track,
            retrieved,
            session_bpm=session_bpm,
            min_stretch_ratio=tempo_cfg.min_stretch_ratio,
            max_stretch_ratio=tempo_cfg.max_stretch_ratio,
            weight_tempo=ranking_cfg.weight_tempo,
            weight_energy=ranking_cfg.weight_energy,
            weight_quality=ranking_cfg.weight_quality,
        )

        transition_cfg = self._settings.transition
        plan: TransitionPlan | None = None
        planned_id: int | None = None
        for ranked_candidate in ranked:
            plan = plan_transition(
                track_a=current_track,
                track_b=ranked_candidate.candidate,
                session_bpm=session_bpm,
                min_stretch_ratio=tempo_cfg.min_stretch_ratio,
                max_stretch_ratio=tempo_cfg.max_stretch_ratio,
                outgoing_search_fraction=transition_cfg.outgoing_search_fraction,
                incoming_search_fraction=transition_cfg.incoming_search_fraction,
                weight_stability=transition_cfg.weight_stability,
                weight_energy=transition_cfg.weight_energy,
                weight_stretch=transition_cfg.weight_stretch,
                weight_position=transition_cfg.weight_position,
            )
            if plan is not None:
                planned_id = ranked_candidate.candidate.track_id
                break

        logger.info(
            "selection_completed",
            current_track_id=current_track_id,
            session_bpm=round(session_bpm, 3),
            candidates_total=len(all_candidates),
            candidates_retrieved=len(retrieved),
            candidates_ranked=len(ranked),
            relaxed=relaxed,
            plan_found=plan is not None,
            best_track_id=planned_id,
            best_cost=round(ranked[0].total_cost, 4) if ranked else None,
        )

        return SelectionResult(
            current_track=current_track,
            ranked=ranked,
            plan=plan,
            relaxed=relaxed,
        )

    def _load_candidates(self) -> list[TrackCandidate]:
        with session_scope(self._session_factory) as session:
            repository = TrackRepository(session)
            rows = repository.list_candidates(
                analysis_version=self._settings.analysis.version,
            )
        return [_row_to_candidate(row) for row in rows]


def _find_track(candidates: list[TrackCandidate], track_id: int) -> TrackCandidate | None:
    for c in candidates:
        if c.track_id == track_id:
            return c
    return None


def _row_to_candidate(row: dict[str, object]) -> TrackCandidate:
    """Convert a repository dict to a pure dataclass."""
    raw_regions = row["stable_regions"]
    assert isinstance(raw_regions, list)
    regions = [
        RegionInfo(
            start_beat=int(r["start_beat"]),
            end_beat=int(r["end_beat"]),
            start_time=float(r["start_time"]),
            end_time=float(r["end_time"]),
            score=float(r["score"]),
            ibi_cv=float(r["ibi_cv"]),
            mean_energy=float(r["mean_energy"]),
        )
        for r in raw_regions
    ]
    raw_beats = row["beat_times"]
    assert isinstance(raw_beats, list)

    return TrackCandidate(
        track_id=_as_int(row["track_id"]),
        audio_path=str(row["audio_path"]),
        native_bpm=_as_float(row["native_bpm"]),
        energy=_as_float(row["energy"]),
        analysis_confidence=_as_float(row["analysis_confidence"]),
        analysis_version=_as_int(row["analysis_version"]),
        duration_seconds=_as_float(row["duration_seconds"]),
        stable_regions=regions,
        beat_times=[float(t) for t in raw_beats],
        beat_count=_as_int(row["beat_count"]),
    )


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected int, got {type(value).__name__}")
    return value


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"expected float, got {type(value).__name__}")
    return float(value)
