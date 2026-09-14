"""Unit tests for candidate ranking."""

from __future__ import annotations

from typing import Any

import pytest

from autodj.dj.rank import rank_candidates
from autodj.dj.types import RegionInfo, TrackCandidate


def _region() -> RegionInfo:
    return RegionInfo(
        start_beat=0,
        end_beat=32,
        start_time=0.0,
        end_time=15.5,
        score=0.8,
        ibi_cv=0.02,
        mean_energy=0.5,
    )


def _candidate(
    track_id: int = 1,
    native_bpm: float = 124.0,
    energy: float = 0.5,
    confidence: float = 0.7,
) -> TrackCandidate:
    return TrackCandidate(
        track_id=track_id,
        audio_path=f"track_{track_id}.mp3",
        native_bpm=native_bpm,
        energy=energy,
        analysis_confidence=confidence,
        analysis_version=2,
        duration_seconds=180.0,
        stable_regions=[_region()],
        beat_times=[i * 60.0 / native_bpm for i in range(64)],
        beat_count=64,
    )


_DEFAULT_KWARGS: dict[str, Any] = {
    "session_bpm": 124.0,
    "min_stretch_ratio": 0.95,
    "max_stretch_ratio": 1.05,
    "weight_tempo": 0.60,
    "weight_energy": 0.35,
    "weight_quality": 0.05,
}


class TestTempoRanking:
    def test_closer_bpm_ranks_higher(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        close = _candidate(track_id=2, native_bpm=125.0, energy=0.5)
        far = _candidate(track_id=3, native_bpm=130.0, energy=0.5)

        ranked = rank_candidates(current, [far, close], **_DEFAULT_KWARGS)

        assert ranked[0].candidate.track_id == 2
        assert ranked[1].candidate.track_id == 3

    def test_exact_bpm_match_has_zero_tempo_cost(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        match = _candidate(track_id=2, native_bpm=124.0)

        ranked = rank_candidates(current, [match], **_DEFAULT_KWARGS)

        assert ranked[0].tempo_cost == pytest.approx(0.0)

    def test_tempo_cost_at_stretch_limit(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        # session_bpm / native_bpm = 124 / (124/1.05) ≈ 1.05 → cost should be ~1.0
        at_limit = _candidate(track_id=2, native_bpm=124.0 / 1.05)

        ranked = rank_candidates(current, [at_limit], **_DEFAULT_KWARGS)

        assert ranked[0].tempo_cost == pytest.approx(1.0, abs=0.01)


class TestEnergyRanking:
    def test_energy_difference_affects_ranking(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0, energy=0.5)
        close_e = _candidate(track_id=2, native_bpm=124.0, energy=0.5)
        far_e = _candidate(track_id=3, native_bpm=124.0, energy=0.9)

        ranked = rank_candidates(current, [far_e, close_e], **_DEFAULT_KWARGS)

        assert ranked[0].candidate.track_id == 2
        assert ranked[0].energy_cost < ranked[1].energy_cost

    def test_zero_energy_delta_has_zero_energy_cost(self) -> None:
        current = _candidate(track_id=1, energy=0.5)
        match = _candidate(track_id=2, energy=0.5)

        ranked = rank_candidates(current, [match], **_DEFAULT_KWARGS)

        assert ranked[0].energy_cost == pytest.approx(0.0)

    def test_energy_cost_is_absolute_delta(self) -> None:
        current = _candidate(track_id=1, energy=0.3)
        candidate = _candidate(track_id=2, energy=0.7)

        ranked = rank_candidates(current, [candidate], **_DEFAULT_KWARGS)

        assert ranked[0].energy_cost == pytest.approx(0.4)


class TestQualityRanking:
    def test_quality_affects_ranking_weakly(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0, energy=0.5)
        high_q = _candidate(track_id=2, native_bpm=124.0, energy=0.5, confidence=0.9)
        low_q = _candidate(track_id=3, native_bpm=124.0, energy=0.5, confidence=0.3)

        ranked = rank_candidates(current, [low_q, high_q], **_DEFAULT_KWARGS)

        # With equal tempo and energy, quality should break the tie.
        assert ranked[0].candidate.track_id == 2
        # But the cost difference is small (0.05 weight).
        diff = ranked[1].total_cost - ranked[0].total_cost
        assert diff == pytest.approx(0.05 * (0.7 - 0.1), abs=1e-6)

    def test_quality_cost_semantics(self) -> None:
        current = _candidate(track_id=1)
        high = _candidate(track_id=2, confidence=0.9)
        low = _candidate(track_id=3, confidence=0.3)

        ranked = rank_candidates(current, [high, low], **_DEFAULT_KWARGS)

        high_ranked = next(r for r in ranked if r.candidate.track_id == 2)
        low_ranked = next(r for r in ranked if r.candidate.track_id == 3)

        assert high_ranked.quality_cost == pytest.approx(0.1)
        assert low_ranked.quality_cost == pytest.approx(0.7)


class TestDeterminism:
    def test_ties_broken_by_track_id(self) -> None:
        current = _candidate(track_id=1)
        # Two candidates with identical features.
        a = _candidate(track_id=10, native_bpm=124.0, energy=0.5, confidence=0.7)
        b = _candidate(track_id=5, native_bpm=124.0, energy=0.5, confidence=0.7)

        ranked = rank_candidates(current, [a, b], **_DEFAULT_KWARGS)

        assert ranked[0].candidate.track_id == 5
        assert ranked[1].candidate.track_id == 10

    def test_ordering_is_stable(self) -> None:
        current = _candidate(track_id=1)
        candidates = [
            _candidate(track_id=i, native_bpm=124.0 + i * 0.1, energy=0.5) for i in range(2, 12)
        ]

        first = rank_candidates(current, candidates, **_DEFAULT_KWARGS)
        second = rank_candidates(current, list(reversed(candidates)), **_DEFAULT_KWARGS)

        assert [r.candidate.track_id for r in first] == [r.candidate.track_id for r in second]


class TestTotalCost:
    def test_total_cost_is_weighted_sum(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0, energy=0.5)
        candidate = _candidate(track_id=2, native_bpm=126.0, energy=0.7, confidence=0.8)

        ranked = rank_candidates(current, [candidate], **_DEFAULT_KWARGS)

        r = ranked[0]
        expected = 0.60 * r.tempo_cost + 0.35 * r.energy_cost + 0.05 * r.quality_cost
        assert r.total_cost == pytest.approx(expected)

    def test_empty_candidates_returns_empty(self) -> None:
        current = _candidate(track_id=1)
        ranked = rank_candidates(current, [], **_DEFAULT_KWARGS)
        assert ranked == []


class TestAfterRelaxation:
    def test_energy_still_orders_candidates_outside_the_energy_gate(self) -> None:
        from autodj.dj.retrieve import retrieve_candidates

        current = _candidate(track_id=1, energy=0.1)
        closer = _candidate(track_id=2, energy=0.5)
        farther = _candidate(track_id=3, energy=0.9)
        retrieved = retrieve_candidates(
            current,
            [farther, closer],
            set(),
            session_bpm=124.0,
            min_stretch_ratio=0.95,
            max_stretch_ratio=1.05,
            max_energy_delta=0.25,
            energy_filter_enabled=True,
            require_stable_region=True,
            allow_repeats=False,
        )
        assert {c.track_id for c in retrieved} == {2, 3}

        ranked = rank_candidates(current, retrieved, **_DEFAULT_KWARGS)

        assert ranked[0].candidate.track_id == 2
        assert ranked[0].energy_cost < ranked[1].energy_cost
