"""Shared dataclasses for candidate selection and transition planning.

Pure data: no database, no HTTP, no filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegionInfo:
    """Lightweight representation of a stable region for planning.

    ``mean_energy`` is the mean of the per-track [0, 1] energy curve in this window.
    RMS in that curve is absolute (dBFS); onset is per-track. The mix is the local
    gap M3 stored the curve for. Track-level ``TrackCandidate.energy`` is the
    library-normalised scalar used by retrieval and ranking, not by pair energy.
    """

    start_beat: int
    end_beat: int
    start_time: float
    end_time: float
    score: float
    ibi_cv: float
    mean_energy: float

    @property
    def midpoint_time(self) -> float:
        return (self.start_time + self.end_time) / 2.0


@dataclass(frozen=True, slots=True)
class TrackCandidate:
    """A track with all features needed for retrieval, ranking, and planning.

    ``energy`` is the library-normalised [0, 1] scalar from ``tracks.energy``.
    ``analysis_confidence`` is a heuristic quality score, not a probability.
    """

    track_id: int
    audio_path: str
    native_bpm: float
    energy: float
    analysis_confidence: float
    analysis_version: int
    duration_seconds: float
    stable_regions: list[RegionInfo]
    beat_times: list[float]
    beat_count: int


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """A candidate with an explicit, decomposed compatibility cost.

    Lower ``total_cost`` is better.
    """

    candidate: TrackCandidate
    total_cost: float
    tempo_cost: float
    energy_cost: float
    quality_cost: float


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    """Where track A should exit and track B should enter.

    Contains enough information for M5 to render the transition (tempo adjustment,
    beat-grid alignment, window extraction, equal-power crossfade) but does not
    perform those operations.
    """

    track_a_id: int
    track_b_id: int
    session_bpm: float
    outgoing_region: RegionInfo
    incoming_region: RegionInfo
    stretch_ratio: float
    pair_cost: float
    stability_cost: float
    energy_cost: float
    stretch_cost: float
    position_cost: float
