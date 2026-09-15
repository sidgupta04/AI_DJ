"""Selection service composition: retrieve, rank, then the first plannable pair."""

from __future__ import annotations

from autodj.config.settings import Settings
from autodj.dj.types import RegionInfo, TrackCandidate
from autodj.services.selection import SelectionService


def _region(
    *,
    start_beat: int,
    start_time: float,
    end_time: float,
    mean_energy: float = 0.5,
    score: float = 0.8,
) -> RegionInfo:
    return RegionInfo(
        start_beat=start_beat,
        end_beat=start_beat + 32,
        start_time=start_time,
        end_time=end_time,
        score=score,
        ibi_cv=0.02,
        mean_energy=mean_energy,
    )


def _candidate(
    track_id: int,
    *,
    energy: float = 0.5,
    regions: list[RegionInfo],
) -> TrackCandidate:
    return TrackCandidate(
        track_id=track_id,
        audio_path=f"track_{track_id}.mp3",
        native_bpm=124.0,
        energy=energy,
        analysis_confidence=0.8,
        analysis_version=2,
        duration_seconds=200.0,
        stable_regions=regions,
        beat_times=[i * 60.0 / 124.0 for i in range(100)],
        beat_count=100,
    )


def test_select_next_plans_the_first_ranked_track_that_has_a_valid_pair(
    settings: Settings,
) -> None:
    current = _candidate(
        1,
        regions=[_region(start_beat=60, start_time=155.0, end_time=165.0)],
    )
    # Ranked first (identical energy) but only has a late region — cannot enter.
    unplannable = _candidate(
        2,
        energy=0.5,
        regions=[_region(start_beat=60, start_time=155.0, end_time=165.0)],
    )
    plannable = _candidate(
        3,
        energy=0.52,
        regions=[_region(start_beat=4, start_time=10.0, end_time=30.0)],
    )
    service = SelectionService(settings, session_factory=None)  # type: ignore[arg-type]
    service._load_candidates = lambda: [current, unplannable, plannable]  # type: ignore[method-assign]

    result = service.select_next(1)

    assert [row.candidate.track_id for row in result.ranked] == [2, 3]
    assert result.plan is not None
    assert result.plan.track_b_id == 3
