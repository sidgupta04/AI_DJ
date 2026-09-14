"""Candidate retrieval: which tracks are plausible next?

Pure filtering on structured features. No database, no HTTP.

The hard stretch bound (``tempo.min_stretch_ratio`` / ``tempo.max_stretch_ratio``)
is never relaxed — it represents a physical constraint of the renderer. When no
candidate survives all filters, relaxation drops the energy gate but keeps the
stretch bound.
"""

from __future__ import annotations

from autodj.dj.types import TrackCandidate

STRETCH_BOUND_ATOL = 1e-12


def retrieve_candidates(
    current_track: TrackCandidate,
    candidates: list[TrackCandidate],
    played_ids: set[int],
    *,
    session_bpm: float,
    min_stretch_ratio: float,
    max_stretch_ratio: float,
    max_energy_delta: float,
    energy_filter_enabled: bool,
    require_stable_region: bool,
    allow_repeats: bool,
) -> list[TrackCandidate]:
    """Return candidates that survive the compatibility filters.

    If the strict filters yield nothing, the energy gate is dropped and the
    remaining hard filters are re-evaluated. The stretch bound is never relaxed.
    """
    hard_filtered = _apply_hard_filters(
        current_track,
        candidates,
        played_ids,
        session_bpm=session_bpm,
        min_stretch_ratio=min_stretch_ratio,
        max_stretch_ratio=max_stretch_ratio,
        require_stable_region=require_stable_region,
        allow_repeats=allow_repeats,
    )

    if energy_filter_enabled:
        strict = _apply_energy_filter(hard_filtered, current_track.energy, max_energy_delta)
        if strict:
            return strict

    # Relaxation: return hard-filtered candidates without the energy gate.
    return hard_filtered


def _apply_hard_filters(
    current_track: TrackCandidate,
    candidates: list[TrackCandidate],
    played_ids: set[int],
    *,
    session_bpm: float,
    min_stretch_ratio: float,
    max_stretch_ratio: float,
    require_stable_region: bool,
    allow_repeats: bool,
) -> list[TrackCandidate]:
    """Filters that are never relaxed."""
    result: list[TrackCandidate] = []
    for candidate in candidates:
        if candidate.track_id == current_track.track_id:
            continue
        if not allow_repeats and candidate.track_id in played_ids:
            continue
        if require_stable_region and not candidate.stable_regions:
            continue
        if candidate.native_bpm <= 0 or session_bpm <= 0:
            continue
        stretch_ratio = session_bpm / candidate.native_bpm
        if not _stretch_in_bound(stretch_ratio, min_stretch_ratio, max_stretch_ratio):
            continue
        result.append(candidate)
    return result


def _apply_energy_filter(
    candidates: list[TrackCandidate],
    current_energy: float,
    max_energy_delta: float,
) -> list[TrackCandidate]:
    return [c for c in candidates if abs(c.energy - current_energy) <= max_energy_delta]


def _stretch_in_bound(ratio: float, min_ratio: float, max_ratio: float) -> bool:
    """Inclusive hard bound with a float tolerance so exact 0.95 / 1.05 constructions pass."""
    return min_ratio - STRETCH_BOUND_ATOL <= ratio <= max_ratio + STRETCH_BOUND_ATOL
