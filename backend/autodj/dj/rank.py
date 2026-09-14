"""Candidate ranking: which plausible next track is best?

Pure weighted-cost ranking on structured features. No database, no HTTP.

Each cost component is in [0, 1] (lower is better). The total cost is a weighted
sum of tempo, energy, and quality costs with configured weights that must sum to 1.

Deterministic: ties are broken by ``track_id`` ascending.
"""

from __future__ import annotations

from autodj.dj.types import RankedCandidate, TrackCandidate


def rank_candidates(
    current_track: TrackCandidate,
    candidates: list[TrackCandidate],
    *,
    session_bpm: float,
    min_stretch_ratio: float,
    max_stretch_ratio: float,
    weight_tempo: float,
    weight_energy: float,
    weight_quality: float,
) -> list[RankedCandidate]:
    """Rank candidates by weighted compatibility cost.  Lower cost is better.

    Returns a list sorted by ``(total_cost, track_id)`` ascending.
    """
    max_stretch_deviation = _max_stretch_deviation(min_stretch_ratio, max_stretch_ratio)

    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        tempo_cost = _tempo_cost(session_bpm, candidate.native_bpm, max_stretch_deviation)
        energy_cost = _energy_cost(current_track.energy, candidate.energy)
        quality_cost = _quality_cost(candidate.analysis_confidence)

        total_cost = (
            weight_tempo * tempo_cost + weight_energy * energy_cost + weight_quality * quality_cost
        )

        ranked.append(
            RankedCandidate(
                candidate=candidate,
                total_cost=total_cost,
                tempo_cost=tempo_cost,
                energy_cost=energy_cost,
                quality_cost=quality_cost,
            )
        )

    ranked.sort(key=lambda r: (r.total_cost, r.candidate.track_id))
    return ranked


def _tempo_cost(session_bpm: float, native_bpm: float, max_stretch_deviation: float) -> float:
    """Normalised distance from unity stretch.  0 = exact match, 1 = at the hard limit."""
    if max_stretch_deviation <= 0:
        return 0.0
    if native_bpm <= 0:
        return 1.0
    stretch_ratio = session_bpm / native_bpm
    return min(1.0, abs(stretch_ratio - 1.0) / max_stretch_deviation)


def _energy_cost(current_energy: float, candidate_energy: float) -> float:
    """Absolute library-normalised energy delta.  Already in [0, 1]."""
    return abs(candidate_energy - current_energy)


def _quality_cost(analysis_confidence: float) -> float:
    """Monotonic penalty for lower-confidence analysis.

    ``1 - confidence``: a track with confidence 0.6 costs 0.4.  The maximum
    depends on ``analysis.min_confidence`` (default 0.25 → max cost 0.75), not
    on any calibrated probability.
    """
    return 1.0 - analysis_confidence


def _max_stretch_deviation(min_stretch_ratio: float, max_stretch_ratio: float) -> float:
    return max(max_stretch_ratio - 1.0, 1.0 - min_stretch_ratio)
