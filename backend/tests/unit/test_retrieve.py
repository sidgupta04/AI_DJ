"""Unit tests for candidate retrieval."""

from __future__ import annotations

from typing import Any

from autodj.dj.retrieve import retrieve_candidates
from autodj.dj.types import RegionInfo, TrackCandidate


def _region(
    start_beat: int = 0,
    end_beat: int = 32,
    start_time: float = 0.0,
    end_time: float = 15.5,
    score: float = 0.8,
) -> RegionInfo:
    return RegionInfo(
        start_beat=start_beat,
        end_beat=end_beat,
        start_time=start_time,
        end_time=end_time,
        score=score,
        ibi_cv=0.02,
        mean_energy=0.5,
    )


def _candidate(
    track_id: int = 1,
    native_bpm: float = 124.0,
    energy: float = 0.5,
    confidence: float = 0.7,
    regions: list[RegionInfo] | None = None,
    duration: float = 180.0,
) -> TrackCandidate:
    return TrackCandidate(
        track_id=track_id,
        audio_path=f"track_{track_id}.mp3",
        native_bpm=native_bpm,
        energy=energy,
        analysis_confidence=confidence,
        analysis_version=2,
        duration_seconds=duration,
        stable_regions=regions if regions is not None else [_region()],
        beat_times=[i * 60.0 / native_bpm for i in range(64)] if native_bpm > 0 else [],
        beat_count=64,
    )


_DEFAULT_KWARGS: dict[str, Any] = {
    "session_bpm": 124.0,
    "min_stretch_ratio": 0.95,
    "max_stretch_ratio": 1.05,
    "max_energy_delta": 0.25,
    "energy_filter_enabled": True,
    "require_stable_region": True,
    "allow_repeats": False,
}


class TestExcludeCurrentTrack:
    def test_current_track_is_excluded(self) -> None:
        current = _candidate(track_id=1)
        candidates = [_candidate(track_id=1), _candidate(track_id=2)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert [c.track_id for c in result] == [2]


class TestExcludePlayedTracks:
    def test_played_tracks_excluded(self) -> None:
        current = _candidate(track_id=1)
        candidates = [_candidate(track_id=2), _candidate(track_id=3)]
        result = retrieve_candidates(current, candidates, {2}, **_DEFAULT_KWARGS)
        assert [c.track_id for c in result] == [3]

    def test_allow_repeats_includes_played(self) -> None:
        current = _candidate(track_id=1)
        candidates = [_candidate(track_id=2)]
        kwargs = {**_DEFAULT_KWARGS, "allow_repeats": True}
        result = retrieve_candidates(current, candidates, {2}, **kwargs)
        assert [c.track_id for c in result] == [2]


class TestStableRegionFilter:
    def test_no_stable_regions_excluded(self) -> None:
        current = _candidate(track_id=1)
        candidates = [_candidate(track_id=2, regions=[])]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert result == []

    def test_no_region_requirement_keeps_regionless(self) -> None:
        current = _candidate(track_id=1)
        candidates = [_candidate(track_id=2, regions=[])]
        kwargs = {**_DEFAULT_KWARGS, "require_stable_region": False}
        result = retrieve_candidates(current, candidates, set(), **kwargs)
        assert [c.track_id for c in result] == [2]


class TestStretchBound:
    def test_within_stretch_bound_passes(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        # 4% stretch required: 124 / 119.23 ≈ 1.04
        candidates = [_candidate(track_id=2, native_bpm=119.23)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert len(result) == 1

    def test_exceeds_stretch_bound_excluded(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        # 6% stretch required: 124 / 117.0 ≈ 1.06 > 1.05
        candidates = [_candidate(track_id=2, native_bpm=117.0)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert result == []

    def test_exactly_at_lower_bound_passes(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        # stretch = 124 / (124 / 0.95) = 0.95
        bpm_at_lower = 124.0 / 0.95
        candidates = [_candidate(track_id=2, native_bpm=bpm_at_lower)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert len(result) == 1

    def test_exactly_at_upper_bound_passes(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        # stretch = 124 / (124 / 1.05) = 1.05
        bpm_at_upper = 124.0 / 1.05
        candidates = [_candidate(track_id=2, native_bpm=bpm_at_upper)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert len(result) == 1


class TestEnergyFilter:
    def test_energy_within_delta_passes(self) -> None:
        current = _candidate(track_id=1, energy=0.5)
        candidates = [_candidate(track_id=2, energy=0.7)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert len(result) == 1

    def test_energy_beyond_delta_dropped_when_a_closer_candidate_exists(self) -> None:
        current = _candidate(track_id=1, energy=0.5)
        closer = _candidate(track_id=2, energy=0.6)
        far = _candidate(track_id=3, energy=0.9)
        result = retrieve_candidates(current, [closer, far], set(), **_DEFAULT_KWARGS)
        assert [c.track_id for c in result] == [2]

    def test_energy_filter_disabled_keeps_all(self) -> None:
        current = _candidate(track_id=1, energy=0.5)
        candidates = [_candidate(track_id=2, energy=0.9)]
        kwargs = {**_DEFAULT_KWARGS, "energy_filter_enabled": False}
        result = retrieve_candidates(current, candidates, set(), **kwargs)
        assert len(result) == 1


class TestRelaxation:
    def test_relaxation_drops_energy_filter(self) -> None:
        current = _candidate(track_id=1, energy=0.1)
        # Both candidates outside energy delta but inside stretch bound.
        candidates = [
            _candidate(track_id=2, energy=0.8),
            _candidate(track_id=3, energy=0.9),
        ]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert len(result) == 2

    def test_non_positive_bpm_is_excluded(self) -> None:
        current = _candidate(track_id=1)
        candidates = [_candidate(track_id=2, native_bpm=0.0)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert result == []

    def test_relaxation_keeps_stretch_bound(self) -> None:
        current = _candidate(track_id=1, energy=0.1, native_bpm=124.0)
        # Outside energy delta AND outside stretch bound.
        candidates = [_candidate(track_id=2, energy=0.8, native_bpm=100.0)]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert result == []


class TestNoCandidates:
    def test_empty_candidate_list(self) -> None:
        current = _candidate(track_id=1)
        result = retrieve_candidates(current, [], set(), **_DEFAULT_KWARGS)
        assert result == []

    def test_all_candidates_fail_all_filters(self) -> None:
        current = _candidate(track_id=1, native_bpm=124.0)
        candidates = [_candidate(track_id=2, native_bpm=200.0, regions=[])]
        result = retrieve_candidates(current, candidates, set(), **_DEFAULT_KWARGS)
        assert result == []
