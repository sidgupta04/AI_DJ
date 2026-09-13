"""Ingest, then analyse, against PostgreSQL using synthetic click and noise files."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.audio import write_click_wav, write_noise_wav
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.beats import AnalysisFailure
from autodj.config.settings import Settings
from autodj.persistence.models import AnalysisStatus, Track
from autodj.persistence.repositories import TrackRepository
from autodj.services.analysis import (
    AnalysisOutcomeStatus,
    LibraryAnalysisService,
    PipelineFailure,
)
from autodj.services.ingestion import LibraryIngestionService

pytestmark = pytest.mark.usefixtures("require_ffmpeg")


@pytest.fixture
def ingestion(
    fast_settings: Settings, session_factory: sessionmaker[Session]
) -> LibraryIngestionService:
    return LibraryIngestionService(fast_settings, session_factory)


@pytest.fixture
def analysis(
    fast_settings: Settings, session_factory: sessionmaker[Session]
) -> LibraryAnalysisService:
    return LibraryAnalysisService(fast_settings, session_factory)


def _track(session_factory: sessionmaker[Session], audio_path: str) -> Track:
    with session_factory() as session:
        track = TrackRepository(session).get_by_path(audio_path)
        assert track is not None, f"no track row for {audio_path}"
        return track


def test_a_pending_click_track_is_analysed_and_persisted(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
    fast_settings: Settings,
) -> None:
    write_click_wav(library_dir / "Fisher - Losing It.wav", bpm=124.0)
    ingestion.scan()

    report = analysis.analyze()

    assert (report.selected, report.completed, report.failed) == (1, 1, 0)
    track = _track(session_factory, "Fisher - Losing It.wav")
    assert track.analysis_status is AnalysisStatus.COMPLETE
    assert track.native_bpm == pytest.approx(124.0, abs=1.0)
    assert track.analysis_confidence is not None and track.analysis_confidence > 0.7
    assert track.analysis_version == fast_settings.analysis.version
    assert track.failure_reason is None

    with session_factory() as session:
        row = TrackRepository(session).get_analysis(track.id)
    assert row is not None
    assert row.beat_count == len(row.beat_times)
    assert row.beat_count >= fast_settings.analysis.min_beats
    assert row.sample_rate == fast_settings.analysis.sample_rate
    assert row.hop_length == fast_settings.analysis.hop_length
    assert row.refine_hop_length == fast_settings.analysis.refine_hop_length
    bpm = track.native_bpm
    assert bpm is not None
    assert row.median_ibi_seconds == pytest.approx(60.0 / bpm)
    assert row.beat_times == sorted(row.beat_times)


def test_a_processing_track_left_by_a_crash_is_retried(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    """PROCESSING is the crash residue: the next run must pick the row back up."""
    write_click_wav(library_dir / "interrupted.wav", bpm=124.0)
    ingestion.scan()
    with session_factory() as session:
        track = TrackRepository(session).get_by_path("interrupted.wav")
        assert track is not None
        track.analysis_status = AnalysisStatus.PROCESSING
        session.commit()
    assert _track(session_factory, "interrupted.wav").analysis_status is AnalysisStatus.PROCESSING

    report = analysis.analyze()

    assert (report.selected, report.completed, report.failed) == (1, 1, 0)
    recovered = _track(session_factory, "interrupted.wav")
    assert recovered.analysis_status is AnalysisStatus.COMPLETE
    assert recovered.native_bpm == pytest.approx(124.0, abs=1.0)


def test_a_second_run_skips_complete_tracks(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
) -> None:
    write_click_wav(library_dir / "Bicep - Glue.wav", bpm=128.0)
    ingestion.scan()
    first = analysis.analyze()
    second = analysis.analyze()

    assert first.completed == 1
    assert (second.selected, second.completed, second.skipped) == (0, 0, 0)


def test_reanalyze_rewrites_a_complete_row(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    write_click_wav(library_dir / "Bicep - Glue.wav", bpm=128.0)
    ingestion.scan()
    analysis.analyze()

    report = analysis.analyze(reanalyze=True)

    assert report.completed == 1
    track = _track(session_factory, "Bicep - Glue.wav")
    assert track.analysis_status is AnalysisStatus.COMPLETE
    assert track.native_bpm == pytest.approx(128.0, abs=1.0)


def test_stale_analysis_version_is_reprocessed_without_reanalyze(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    write_click_wav(library_dir / "Jamie xx - Gosh.wav", bpm=120.0)
    ingestion.scan()
    analysis.analyze()
    with session_factory() as session:
        track = TrackRepository(session).get_by_path("Jamie xx - Gosh.wav")
        assert track is not None
        track.analysis_version = 0
        session.commit()

    report = analysis.analyze()

    assert report.completed == 1
    assert _track(session_factory, "Jamie xx - Gosh.wav").analysis_version == 1


def test_white_noise_is_recorded_as_failed_and_the_batch_continues(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    write_noise_wav(library_dir / "static.wav")
    write_click_wav(library_dir / "working.wav", bpm=124.0)
    ingestion.scan()

    report = analysis.analyze()

    assert (report.selected, report.completed, report.failed) == (2, 1, 1)
    assert report.failures[0][0] == "static.wav"
    failed = _track(session_factory, "static.wav")
    assert failed.analysis_status is AnalysisStatus.FAILED
    assert failed.native_bpm is None
    assert failed.analysis_confidence is None
    assert failed.failure_reason is not None
    assert failed.failure_reason["reason"] in {item.value for item in AnalysisFailure}
    assert failed.failure_reason["detail"]
    assert _track(session_factory, "working.wav").analysis_status is AnalysisStatus.COMPLETE


def test_a_missing_source_file_fails_without_aborting(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    path = library_dir / "vanished.wav"
    write_click_wav(path, bpm=124.0)
    ingestion.scan()
    path.unlink()

    report = analysis.analyze()

    assert (report.completed, report.failed) == (0, 1)
    track = _track(session_factory, "vanished.wav")
    assert track.analysis_status is AnalysisStatus.FAILED
    assert track.failure_reason is not None
    assert track.failure_reason["reason"] == str(PipelineFailure.MISSING_FILE)


def test_reingest_clears_stale_analysis(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    path = library_dir / "replaced.wav"
    write_click_wav(path, bpm=120.0)
    ingestion.scan()
    analysis.analyze()
    assert _track(session_factory, "replaced.wav").native_bpm is not None

    write_click_wav(path, bpm=128.0, seconds=16.5)
    ingestion.scan()

    refreshed = _track(session_factory, "replaced.wav")
    assert refreshed.analysis_status is AnalysisStatus.PENDING
    assert refreshed.native_bpm is None
    assert refreshed.analysis_confidence is None
    assert refreshed.analysis_version is None
    with session_factory() as session:
        assert TrackRepository(session).get_analysis(refreshed.id) is None


def test_analyze_path_selects_one_track(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
    session_factory: sessionmaker[Session],
) -> None:
    write_click_wav(library_dir / "one.wav", bpm=120.0)
    write_click_wav(library_dir / "two.wav", bpm=128.0)
    ingestion.scan()

    report = analysis.analyze(audio_path="two.wav")

    assert (report.selected, report.completed) == (1, 1)
    assert _track(session_factory, "two.wav").analysis_status is AnalysisStatus.COMPLETE
    assert _track(session_factory, "one.wav").analysis_status is AnalysisStatus.PENDING


def test_limit_caps_the_queue(
    ingestion: LibraryIngestionService,
    analysis: LibraryAnalysisService,
    library_dir: Path,
) -> None:
    write_click_wav(library_dir / "a.wav", bpm=120.0)
    write_click_wav(library_dir / "b.wav", bpm=124.0)
    ingestion.scan()

    report = analysis.analyze(limit=1)

    assert report.selected == 1
    assert report.completed == 1


def test_an_unknown_path_selects_nothing(
    analysis: LibraryAnalysisService,
) -> None:
    report = analysis.analyze(audio_path="missing.wav")

    assert (report.selected, report.completed, report.failed) == (0, 0, 0)


def test_outcome_status_values_are_stable() -> None:
    assert AnalysisOutcomeStatus.COMPLETED == "completed"
    assert PipelineFailure.MISSING_FILE == "MISSING_FILE"
