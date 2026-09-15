"""RenderService writes a WAV and a transitions row from a planted plan."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fixtures.audio import write_wav
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.naming import MetadataSource
from autodj.config.settings import Settings
from autodj.dj.types import RegionInfo, TransitionPlan
from autodj.persistence.models import (
    AnalysisStatus,
    Track,
    TrackAnalysis,
    Transition,
    TransitionStatus,
)
from autodj.persistence.repositories import TransitionRepository
from autodj.services.render import RenderService


def _region(start_beat: int, bpm: float) -> RegionInfo:
    start_time = start_beat * 60.0 / bpm
    return RegionInfo(
        start_beat=start_beat,
        end_beat=start_beat + 4,
        start_time=start_time,
        end_time=start_time + 4 * 60.0 / bpm,
        score=0.8,
        ibi_cv=0.01,
        mean_energy=0.5,
    )


def _plan(track_a: int, track_b: int, bpm: float) -> TransitionPlan:
    return TransitionPlan(
        track_a_id=track_a,
        track_b_id=track_b,
        session_bpm=bpm,
        outgoing_region=_region(8, bpm),
        incoming_region=_region(0, bpm),
        stretch_ratio=1.0,
        pair_cost=0.1,
        stability_cost=0.2,
        energy_cost=0.0,
        stretch_cost=0.0,
        position_cost=0.1,
    )


def _insert_track(
    session: Session,
    *,
    path: str,
    bpm: float,
    seconds: float,
) -> Track:
    beat_times = [i * 60.0 / bpm for i in range(int(seconds * bpm / 60.0) + 1)]
    track = Track(
        audio_path=path,
        content_hash="b" * 64,
        title=path,
        artist=None,
        metadata_source=MetadataSource.FILENAME,
        duration_seconds=seconds,
        analysis_status=AnalysisStatus.COMPLETE,
        native_bpm=bpm,
        analysis_confidence=0.9,
        analysis_version=2,
        energy=0.5,
    )
    session.add(track)
    session.flush()
    session.add(
        TrackAnalysis(
            track_id=track.id,
            beat_times=beat_times,
            beat_count=len(beat_times),
            sample_rate=22050,
            hop_length=512,
            refine_hop_length=256,
            median_ibi_seconds=60.0 / bpm,
            ibi_cv=0.01,
            onset_contrast=0.8,
            tempo_octave_factor=1.0,
            energy_curve=[0.5],
            energy_curve_hz=10.0,
            energy_scalar=0.5,
            stable_regions=[],
        )
    )
    return track


@pytest.fixture
def render_settings(fast_settings: Settings, tmp_path: Path) -> Settings:
    transition = fast_settings.transition.model_copy(
        update={"crossfade_beats": 4, "margin_beats": 2, "align_on_downbeat": False}
    )
    return fast_settings.model_copy(
        update={
            "transition": transition,
            "render_cache_dir": tmp_path / "render_cache",
        }
    )


def test_render_service_writes_wav_and_persists_a_rendered_row(
    render_settings: Settings,
    session_factory: sessionmaker[Session],
    library_dir: Path,
) -> None:
    bpm = 120.0
    seconds = 8.0
    write_wav(library_dir / "a.wav", seconds=seconds, sample_rate=44100, channels=2)
    write_wav(
        library_dir / "b.wav",
        seconds=seconds,
        sample_rate=44100,
        channels=2,
        frequency=330.0,
    )
    with session_factory() as session:
        track_a = _insert_track(session, path="a.wav", bpm=bpm, seconds=seconds)
        track_b = _insert_track(session, path="b.wav", bpm=bpm, seconds=seconds)
        session.commit()
        plan = _plan(track_a.id, track_b.id, bpm)

    result = RenderService(render_settings, session_factory).render_plan(plan)

    assert result.status is TransitionStatus.RENDERED
    assert result.failure is None
    assert result.wav_path is not None and result.wav_path.is_file()
    assert result.clipped is False
    with wave.open(str(result.wav_path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 44100
        assert handle.getnframes() > 0

    with session_factory() as session:
        row = TransitionRepository(session).get_by_id(result.transition_id)
    assert row is not None
    assert row.status is TransitionStatus.RENDERED
    assert row.track_a_id == plan.track_a_id
    assert row.track_b_id == plan.track_b_id
    assert row.wav_path is not None
    assert row.config_snapshot["tempo"]["stretch_backend"] == "pedalboard"


def test_render_service_persists_failure_when_the_source_is_missing(
    render_settings: Settings,
    session_factory: sessionmaker[Session],
) -> None:
    bpm = 120.0
    with session_factory() as session:
        track_a = _insert_track(session, path="missing-a.wav", bpm=bpm, seconds=8.0)
        track_b = _insert_track(session, path="missing-b.wav", bpm=bpm, seconds=8.0)
        session.commit()
        plan = _plan(track_a.id, track_b.id, bpm)

    result = RenderService(render_settings, session_factory).render_plan(plan)

    assert result.status is TransitionStatus.FAILED
    assert result.failure is not None
    assert result.failure["reason"] == "MISSING_FILE"
    with session_factory() as session:
        row = TransitionRepository(session).get_by_id(result.transition_id)
    assert row is not None
    assert row.status is TransitionStatus.FAILED
    assert row.wav_path is None


def test_stems_with_different_native_rates_are_resampled_to_render_rate(
    render_settings: Settings,
    session_factory: sessionmaker[Session],
    library_dir: Path,
) -> None:
    bpm = 120.0
    seconds = 8.0
    write_wav(library_dir / "a.wav", seconds=seconds, sample_rate=22050, channels=2)
    write_wav(
        library_dir / "b.wav",
        seconds=seconds,
        sample_rate=48000,
        channels=2,
        frequency=330.0,
    )
    with session_factory() as session:
        track_a = _insert_track(session, path="a.wav", bpm=bpm, seconds=seconds)
        track_b = _insert_track(session, path="b.wav", bpm=bpm, seconds=seconds)
        session.commit()
        plan = _plan(track_a.id, track_b.id, bpm)

    result = RenderService(render_settings, session_factory).render_plan(plan)

    assert result.status is TransitionStatus.RENDERED
    assert result.wav_path is not None
    with wave.open(str(result.wav_path), "rb") as handle:
        assert handle.getframerate() == render_settings.render.sample_rate
        assert handle.getnchannels() == render_settings.render.channels
        # Mix length is margin+fade+margin at session tempo; must be at render rate.
        assert handle.getnframes() > 0


def test_persist_failure_after_write_discards_wav_and_leaves_no_rendered_row(
    render_settings: Settings,
    session_factory: sessionmaker[Session],
    library_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bpm = 120.0
    seconds = 8.0
    write_wav(library_dir / "a.wav", seconds=seconds, sample_rate=44100, channels=2)
    write_wav(library_dir / "b.wav", seconds=seconds, sample_rate=44100, channels=2)
    with session_factory() as session:
        track_a = _insert_track(session, path="a.wav", bpm=bpm, seconds=seconds)
        track_b = _insert_track(session, path="b.wav", bpm=bpm, seconds=seconds)
        session.commit()
        plan = _plan(track_a.id, track_b.id, bpm)

    service = RenderService(render_settings, session_factory)
    destination = service._default_wav_path(plan)

    def _fail_rendered(*_args: object, **kwargs: object) -> object:
        if kwargs.get("status") is TransitionStatus.RENDERED:
            raise RuntimeError("database unavailable")
        raise AssertionError("unexpected persist call before RENDERED")

    monkeypatch.setattr(service, "_persist", _fail_rendered)

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.render_plan(plan)

    assert not destination.exists()
    assert list(destination.parent.glob(f".{destination.name}.*.tmp")) == []
    with session_factory() as session:
        rendered = list(
            session.scalars(
                select(Transition).where(
                    Transition.track_a_id == plan.track_a_id,
                    Transition.track_b_id == plan.track_b_id,
                    Transition.status == TransitionStatus.RENDERED,
                )
            )
        )
    assert rendered == []
