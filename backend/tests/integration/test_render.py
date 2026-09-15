"""End-to-end: ingest, analyse, plan, and render two synthetic click tracks."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fixtures.audio import write_click_wav
from sqlalchemy.orm import Session, sessionmaker

from autodj.config.settings import Settings
from autodj.persistence.models import AnalysisStatus, TransitionStatus
from autodj.persistence.repositories import TrackRepository, TransitionRepository
from autodj.services.analysis import LibraryAnalysisService
from autodj.services.ingestion import LibraryIngestionService
from autodj.services.render import RenderService
from autodj.services.selection import SelectionService

pytestmark = pytest.mark.usefixtures("require_ffmpeg")

ANALYSIS_SECONDS = 36.0


@pytest.fixture
def render_settings(fast_settings: Settings, tmp_path: Path) -> Settings:
    transition = fast_settings.transition.model_copy(
        update={
            "crossfade_beats": 8,
            "margin_beats": 2,
            "align_on_downbeat": False,
            # Short click tracks keep few regions; this test covers render, not M4 windows.
            "outgoing_search_fraction": (0.0, 1.0),
            "incoming_search_fraction": (0.0, 1.0),
        }
    )
    return fast_settings.model_copy(
        update={"transition": transition, "render_cache_dir": tmp_path / "render_cache"}
    )


def test_plan_and_render_two_click_tracks(
    render_settings: Settings,
    session_factory: sessionmaker[Session],
    library_dir: Path,
) -> None:
    write_click_wav(library_dir / "a.wav", bpm=124.0, seconds=ANALYSIS_SECONDS)
    write_click_wav(library_dir / "b.wav", bpm=120.0, seconds=ANALYSIS_SECONDS)

    LibraryIngestionService(render_settings, session_factory).scan()
    report = LibraryAnalysisService(render_settings, session_factory).analyze()
    assert report.failed == 0
    assert report.completed == 2

    with session_factory() as session:
        tracks = TrackRepository(session).list_tracks(statuses=[AnalysisStatus.COMPLETE])
        by_path = {track.audio_path: track for track in tracks}
    current = by_path["a.wav"]
    assert current.native_bpm is not None

    selection = SelectionService(render_settings, session_factory).select_next(current.id)
    assert selection.plan is not None
    assert selection.plan.track_b_id == by_path["b.wav"].id
    assert 0.95 <= selection.plan.stretch_ratio <= 1.05

    rendered = RenderService(render_settings, session_factory).render_plan(selection.plan)
    assert rendered.status is TransitionStatus.RENDERED
    assert rendered.wav_path is not None and rendered.wav_path.is_file()
    with wave.open(str(rendered.wav_path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == render_settings.render.sample_rate
        assert handle.getnframes() > render_settings.render.sample_rate

    with session_factory() as session:
        row = TransitionRepository(session).get_by_id(rendered.transition_id)
    assert row is not None
    assert row.stretch_ratio == pytest.approx(selection.plan.stretch_ratio)
    assert row.peak_dbfs is not None
