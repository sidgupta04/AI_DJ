"""Unit tests for transition planning."""

from __future__ import annotations

from typing import Any

import pytest

from autodj.dj.plan import plan_transition
from autodj.dj.types import RegionInfo, TrackCandidate


def _region(
    start_beat: int = 0,
    end_beat: int = 32,
    start_time: float = 0.0,
    end_time: float = 15.5,
    score: float = 0.8,
    mean_energy: float = 0.5,
) -> RegionInfo:
    return RegionInfo(
        start_beat=start_beat,
        end_beat=end_beat,
        start_time=start_time,
        end_time=end_time,
        score=score,
        ibi_cv=0.02,
        mean_energy=mean_energy,
    )


def _candidate(
    track_id: int = 1,
    native_bpm: float = 124.0,
    energy: float = 0.5,
    confidence: float = 0.7,
    regions: list[RegionInfo] | None = None,
    duration: float = 200.0,
) -> TrackCandidate:
    return TrackCandidate(
        track_id=track_id,
        audio_path=f"track_{track_id}.mp3",
        native_bpm=native_bpm,
        energy=energy,
        analysis_confidence=confidence,
        analysis_version=2,
        duration_seconds=duration,
        stable_regions=regions if regions is not None else [],
        beat_times=[i * 60.0 / native_bpm for i in range(100)],
        beat_count=100,
    )


_DEFAULT_KWARGS: dict[str, Any] = {
    "session_bpm": 124.0,
    "min_stretch_ratio": 0.95,
    "max_stretch_ratio": 1.05,
    "outgoing_search_fraction": (0.65, 0.95),
    "incoming_search_fraction": (0.0, 0.35),
    "weight_stability": 0.40,
    "weight_energy": 0.30,
    "weight_stretch": 0.20,
    "weight_position": 0.10,
}


class TestBasicPlanning:
    def test_valid_pair_produces_plan(self) -> None:
        # Outgoing region at 80% of 200s = 160s midpoint
        out_region = _region(
            start_beat=60,
            end_beat=92,
            start_time=150.0,
            end_time=170.0,
            score=0.9,
        )
        # Incoming region at 10% of 200s = 20s midpoint
        in_region = _region(start_beat=4, end_beat=36, start_time=10.0, end_time=30.0, score=0.85)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.track_a_id == 1
        assert plan.track_b_id == 2
        assert plan.outgoing_region == out_region
        assert plan.incoming_region == in_region
        assert plan.stretch_ratio == pytest.approx(1.0)
        assert plan.session_bpm == pytest.approx(124.0)

    def test_plan_contains_all_fields(self) -> None:
        out_region = _region(start_beat=60, end_beat=92, start_time=150.0, end_time=170.0)
        in_region = _region(start_beat=4, end_beat=36, start_time=10.0, end_time=30.0)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert hasattr(plan, "stability_cost")
        assert hasattr(plan, "energy_cost")
        assert hasattr(plan, "stretch_cost")
        assert hasattr(plan, "position_cost")
        assert hasattr(plan, "pair_cost")


class TestStretchBound:
    def test_stretch_outside_bound_returns_none(self) -> None:
        out_region = _region(start_time=150.0, end_time=170.0)
        in_region = _region(start_time=10.0, end_time=30.0)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        # 124 / 100 = 1.24 >> 1.05
        track_b = _candidate(track_id=2, native_bpm=100.0, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is None


class TestRegionWindows:
    def test_outgoing_region_outside_window_excluded(self) -> None:
        # Region at 30% of track — outside [0.65, 0.95]
        out_region = _region(start_time=50.0, end_time=70.0)
        in_region = _region(start_time=10.0, end_time=30.0)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is None

    def test_incoming_region_outside_window_excluded(self) -> None:
        # Outgoing at 80% (good), incoming at 80% (outside [0, 0.35])
        out_region = _region(start_time=150.0, end_time=170.0)
        in_region = _region(start_time=150.0, end_time=170.0)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is None


class TestNoValidPair:
    def test_no_outgoing_regions_returns_none(self) -> None:
        in_region = _region(start_time=10.0, end_time=30.0)

        track_a = _candidate(track_id=1, regions=[], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is None

    def test_no_incoming_regions_returns_none(self) -> None:
        out_region = _region(start_time=150.0, end_time=170.0)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is None


class TestCostComponents:
    def test_stability_cost_decreases_with_higher_scores(self) -> None:
        high = _region(start_time=150.0, end_time=170.0, score=0.95)
        low = _region(start_time=150.0, end_time=170.0, score=0.5)
        in_region = _region(start_time=10.0, end_time=30.0, score=0.8)

        track_a_high = _candidate(track_id=1, regions=[high], duration=200.0)
        track_a_low = _candidate(track_id=3, regions=[low], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan_high = plan_transition(track_a_high, track_b, **_DEFAULT_KWARGS)
        plan_low = plan_transition(track_a_low, track_b, **_DEFAULT_KWARGS)

        assert plan_high is not None
        assert plan_low is not None
        assert plan_high.stability_cost < plan_low.stability_cost

    def test_energy_cost_uses_local_region_mean_energy(self) -> None:
        out_region = _region(start_time=150.0, end_time=170.0, mean_energy=0.3)
        in_region = _region(start_time=10.0, end_time=30.0, mean_energy=0.9)

        # Track-level energy is close; the local region gap is what planning scores.
        track_a = _candidate(track_id=1, energy=0.5, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, energy=0.52, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.energy_cost == pytest.approx(0.6)

    def test_stretch_cost_is_zero_at_unity(self) -> None:
        out_region = _region(start_time=150.0, end_time=170.0)
        in_region = _region(start_time=10.0, end_time=30.0)

        track_a = _candidate(track_id=1, native_bpm=124.0, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, native_bpm=124.0, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.stretch_cost == pytest.approx(0.0)

    def test_position_cost_zero_at_center(self) -> None:
        # Outgoing center is 0.80 of track A. 0.80 * 200 = 160.
        # Incoming center is 0.175 of track B. 0.175 * 200 = 35.
        out_region = _region(start_time=155.0, end_time=165.0)  # midpoint 160
        in_region = _region(start_time=30.0, end_time=40.0)  # midpoint 35

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.position_cost == pytest.approx(0.0, abs=0.02)

    def test_position_cost_increases_toward_edge(self) -> None:
        # Region at the edge of outgoing window (0.65 * 200 = 130)
        edge_out = _region(start_time=125.0, end_time=135.0)  # midpoint 130
        # Region at the center of outgoing window (0.80 * 200 = 160)
        center_out = _region(start_beat=1, end_beat=33, start_time=155.0, end_time=165.0)
        in_region = _region(start_time=30.0, end_time=40.0)

        track_a_edge = _candidate(track_id=1, regions=[edge_out], duration=200.0)
        track_a_center = _candidate(track_id=3, regions=[center_out], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan_edge = plan_transition(track_a_edge, track_b, **_DEFAULT_KWARGS)
        plan_center = plan_transition(track_a_center, track_b, **_DEFAULT_KWARGS)

        assert plan_edge is not None
        assert plan_center is not None
        assert plan_edge.position_cost > plan_center.position_cost

    def test_pair_cost_is_weighted_sum(self) -> None:
        out_region = _region(start_time=150.0, end_time=170.0, score=0.8)
        in_region = _region(start_time=10.0, end_time=30.0, score=0.7)

        track_a = _candidate(track_id=1, energy=0.5, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, energy=0.6, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        expected = (
            0.40 * plan.stability_cost
            + 0.30 * plan.energy_cost
            + 0.20 * plan.stretch_cost
            + 0.10 * plan.position_cost
        )
        assert plan.pair_cost == pytest.approx(expected)


class TestCheapestPairSelection:
    def test_cheapest_pair_is_chosen(self) -> None:
        # Two outgoing regions: one with high score, one with low.
        good_out = _region(start_beat=60, end_beat=92, start_time=155.0, end_time=165.0, score=0.95)
        bad_out = _region(start_beat=70, end_beat=102, start_time=165.0, end_time=185.0, score=0.3)
        in_region = _region(start_beat=4, end_beat=36, start_time=10.0, end_time=30.0, score=0.9)

        track_a = _candidate(track_id=1, regions=[good_out, bad_out], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.outgoing_region.start_beat == 60  # the high-score one


class TestTieBreaking:
    def test_ties_broken_by_beat_positions(self) -> None:
        # Two outgoing regions with the same score at different beats.
        out_a = _region(start_beat=60, end_beat=92, start_time=155.0, end_time=165.0, score=0.8)
        out_b = _region(start_beat=64, end_beat=96, start_time=157.0, end_time=167.0, score=0.8)
        in_region = _region(start_beat=4, end_beat=36, start_time=10.0, end_time=30.0, score=0.8)

        track_a = _candidate(track_id=1, regions=[out_b, out_a], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        # With identical scores and similar positions, the earlier beat wins.
        assert plan.outgoing_region.start_beat == 60

    def test_local_energy_gap_selects_the_closer_incoming_region(self) -> None:
        out_region = _region(
            start_beat=60, end_beat=92, start_time=155.0, end_time=165.0, mean_energy=0.5
        )
        close_in = _region(
            start_beat=4, end_beat=36, start_time=10.0, end_time=30.0, mean_energy=0.52
        )
        far_in = _region(
            start_beat=8, end_beat=40, start_time=20.0, end_time=40.0, mean_energy=0.95
        )

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[far_in, close_in], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.incoming_region.start_beat == 4
        assert plan.energy_cost == pytest.approx(0.02)

    def test_position_cost_is_one_at_the_search_window_edge(self) -> None:
        # Outgoing window [0.65, 0.95]: midpoint 0.65 is |0.65-0.80|/0.15 = 1.
        # Incoming window centre 0.175 so midpoint 35 s on a 200 s track is ~0.
        out_region = _region(start_time=125.0, end_time=135.0)
        in_region = _region(start_time=30.0, end_time=40.0)

        track_a = _candidate(track_id=1, regions=[out_region], duration=200.0)
        track_b = _candidate(track_id=2, regions=[in_region], duration=200.0)

        plan = plan_transition(track_a, track_b, **_DEFAULT_KWARGS)

        assert plan is not None
        assert plan.position_cost == pytest.approx(0.5, abs=0.02)
