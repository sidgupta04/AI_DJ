from __future__ import annotations

from dataclasses import replace
from typing import Any

from autodj.config.settings import Settings
from autodj.dj.baselines import Strategy, baseline_order
from autodj.dj.types import RegionInfo, TrackCandidate
from autodj.services.evaluation import choose_transition


def candidate(identifier: int, bpm: float = 120, energy: float = 0.5) -> TrackCandidate:
    times = [i * 60 / bpm for i in range(200)]
    regions = [RegionInfo(i, i + 32, times[i], times[i + 31], 0.9, 0.01, energy) for i in (8, 140)]
    return TrackCandidate(
        identifier, f"{identifier}.wav", bpm, energy, 0.9, 2, 100, regions, times, 200
    )


def test_random_order_is_seeded_and_input_order_independent() -> None:
    tracks = [candidate(i) for i in range(1, 10)]
    kwargs: dict[str, Any] = dict(
        strategy=Strategy.RANDOM,
        seed=11,
        session_bpm=120,
        min_stretch_ratio=0.95,
        max_stretch_ratio=1.05,
        weight_tempo=0.6,
        weight_energy=0.35,
    )
    assert baseline_order(candidate(0), tracks, **kwargs) == baseline_order(
        candidate(0), tracks[::-1], **kwargs
    )


def test_nearest_bpm_and_energy_model_can_choose_different_tracks(settings: Settings) -> None:
    current, near, smooth = (
        candidate(1, energy=0.1),
        candidate(2, energy=0.9),
        candidate(3, 121, 0.1),
    )
    b = choose_transition(settings, current, [near, smooth], strategy=Strategy.NEAREST_BPM, seed=1)
    c = choose_transition(settings, current, [near, smooth], strategy=Strategy.BPM_ENERGY, seed=1)
    assert b and c
    assert b.track.track_id == 2 and c.track.track_id == 3
    assert b.outgoing_seconds is not None and c.incoming_seconds is not None


def test_full_uses_regions_and_preserves_hard_bound(settings: Settings) -> None:
    current, other = candidate(1), candidate(2)
    d = choose_transition(settings, current, [other], strategy=Strategy.FULL, seed=1)
    assert d and d.outgoing_seconds is None
    assert d.plan.outgoing_region.start_beat == 140
    for strategy in Strategy:
        assert (
            choose_transition(settings, current, [candidate(3, 150)], strategy=strategy, seed=1)
            is None
        )


def test_blind_pair_never_substitutes_a_different_candidate(settings: Settings) -> None:
    current, missing, good = candidate(1), replace(candidate(2), stable_regions=[]), candidate(3)
    assert (
        choose_transition(
            settings, current, [good], strategy=Strategy.FULL, seed=1, paired_track=missing
        )
        is None
    )
