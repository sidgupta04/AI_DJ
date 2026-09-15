"""Transition planning: where should track A exit and track B enter?

Pure region-pair scoring on structured features.  No database, no HTTP.

Enumerates outgoing regions from A (late in the track) and incoming regions from B
(early in the track) within their configured search windows, scores every valid pair,
and returns the cheapest plan.  If no valid pair exists, returns ``None``.

Energy cost is the absolute gap between the two regions' ``mean_energy`` values
(the local [0, 1] curve means M3 stored for this purpose). Stretch cost uses the
hard renderer bound. Deterministic ties: ``(outgoing.start_beat, incoming.start_beat)``.
"""

from __future__ import annotations

from autodj.dj.types import RegionInfo, TrackCandidate, TransitionPlan

STRETCH_BOUND_ATOL = 1e-12


def plan_transition(
    track_a: TrackCandidate,
    track_b: TrackCandidate,
    *,
    session_bpm: float,
    min_stretch_ratio: float,
    max_stretch_ratio: float,
    outgoing_search_fraction: tuple[float, float],
    incoming_search_fraction: tuple[float, float],
    weight_stability: float,
    weight_energy: float,
    weight_stretch: float,
    weight_position: float,
) -> TransitionPlan | None:
    """Choose the cheapest outgoing/incoming region pair, or ``None``.

    Returns ``None`` when the stretch ratio is outside the hard bound, when
    either track has no qualifying region in its search window, or when no
    valid pair can be formed.
    """
    if track_b.native_bpm <= 0 or session_bpm <= 0:
        return None
    stretch_ratio = session_bpm / track_b.native_bpm
    if not (
        min_stretch_ratio - STRETCH_BOUND_ATOL
        <= stretch_ratio
        <= max_stretch_ratio + STRETCH_BOUND_ATOL
    ):
        return None

    max_deviation = max(max_stretch_ratio - 1.0, 1.0 - min_stretch_ratio)
    stretch_cost = abs(stretch_ratio - 1.0) / max_deviation if max_deviation > 0 else 0.0
    if stretch_cost > 1.0:
        stretch_cost = 1.0

    outgoing_regions = _regions_in_window(
        track_a.stable_regions, track_a.duration_seconds, outgoing_search_fraction
    )
    incoming_regions = _regions_in_window(
        track_b.stable_regions, track_b.duration_seconds, incoming_search_fraction
    )

    if not outgoing_regions or not incoming_regions:
        return None

    out_center, out_half = _window_center_half(outgoing_search_fraction)
    in_center, in_half = _window_center_half(incoming_search_fraction)

    best: tuple[float, int, int, RegionInfo, RegionInfo] | None = None

    for out_region in outgoing_regions:
        out_pos = _normalised_pos(out_region, track_a.duration_seconds)
        out_deviation = abs(out_pos - out_center) / out_half if out_half > 0 else 0.0

        for in_region in incoming_regions:
            in_pos = _normalised_pos(in_region, track_b.duration_seconds)
            in_deviation = abs(in_pos - in_center) / in_half if in_half > 0 else 0.0

            stability_cost = 1.0 - (out_region.score + in_region.score) / 2.0
            stability_cost = max(0.0, min(1.0, stability_cost))
            energy_cost = abs(out_region.mean_energy - in_region.mean_energy)
            position_cost = (out_deviation + in_deviation) / 2.0

            pair_cost = (
                weight_stability * stability_cost
                + weight_energy * energy_cost
                + weight_stretch * stretch_cost
                + weight_position * position_cost
            )

            key = (pair_cost, out_region.start_beat, in_region.start_beat)
            if best is None or key < (best[0], best[1], best[2]):
                best = (
                    pair_cost,
                    out_region.start_beat,
                    in_region.start_beat,
                    out_region,
                    in_region,
                )

    if best is None:
        return None

    pair_cost, _, _, chosen_out, chosen_in = best

    # Recompute individual costs for the chosen pair for reporting.
    stability_cost = 1.0 - (chosen_out.score + chosen_in.score) / 2.0
    stability_cost = max(0.0, min(1.0, stability_cost))
    energy_cost = abs(chosen_out.mean_energy - chosen_in.mean_energy)

    out_pos = _normalised_pos(chosen_out, track_a.duration_seconds)
    in_pos = _normalised_pos(chosen_in, track_b.duration_seconds)
    position_cost = (
        (abs(out_pos - out_center) / out_half if out_half > 0 else 0.0)
        + (abs(in_pos - in_center) / in_half if in_half > 0 else 0.0)
    ) / 2.0

    return TransitionPlan(
        track_a_id=track_a.track_id,
        track_b_id=track_b.track_id,
        session_bpm=session_bpm,
        outgoing_region=chosen_out,
        incoming_region=chosen_in,
        stretch_ratio=stretch_ratio,
        pair_cost=pair_cost,
        stability_cost=stability_cost,
        energy_cost=energy_cost,
        stretch_cost=stretch_cost,
        position_cost=position_cost,
    )


def _normalised_pos(region: RegionInfo, track_duration: float) -> float:
    """Normalised midpoint of a region within its track."""
    if track_duration <= 0:
        return 0.0
    return region.midpoint_time / track_duration


def _regions_in_window(
    regions: list[RegionInfo],
    track_duration: float,
    search_fraction: tuple[float, float],
) -> list[RegionInfo]:
    """Return regions whose normalised midpoint falls within the search window."""
    if track_duration <= 0:
        return []
    low, high = search_fraction
    return [r for r in regions if low <= r.midpoint_time / track_duration <= high]


def _window_center_half(search_fraction: tuple[float, float]) -> tuple[float, float]:
    """Return (center, half_width) of a search window."""
    low, high = search_fraction
    center = (low + high) / 2.0
    half = (high - low) / 2.0
    return center, half
