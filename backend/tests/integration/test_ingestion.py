"""End-to-end ingestion against PostgreSQL, using synthetic files with real-world filenames."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.audio import make_mp3, write_corrupt_mp3, write_empty_file, write_text_file
from sqlalchemy.orm import Session, sessionmaker

from autodj.audio.decode import SourceFailure
from autodj.audio.naming import MetadataSource
from autodj.config.settings import Settings
from autodj.persistence.models import AnalysisStatus, Track
from autodj.persistence.repositories import TrackRepository
from autodj.services.ingestion import FileStatus, LibraryIngestionService

pytestmark = pytest.mark.usefixtures("require_ffmpeg")


@pytest.fixture
def service(
    fast_settings: Settings, session_factory: sessionmaker[Session]
) -> LibraryIngestionService:
    return LibraryIngestionService(fast_settings, session_factory)


def _tracks(session_factory: sessionmaker[Session]) -> list[Track]:
    with session_factory() as session:
        return TrackRepository(session).list_tracks()


def _track(session_factory: sessionmaker[Session], audio_path: str) -> Track:
    with session_factory() as session:
        track = TrackRepository(session).get_by_path(audio_path)
    assert track is not None, f"no track row for {audio_path}"
    return track


def test_embedded_tags_are_preferred_over_the_filename(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    make_mp3(
        library_dir,
        "Drake - Nice For What (Lyrics) 320kbps.mp3",
        tags={"title": "Nice For What", "artist": "Drake"},
    )

    report = service.scan()

    assert (report.scanned, report.added, report.failed) == (1, 1, 0)
    track = _track(session_factory, "Drake - Nice For What (Lyrics) 320kbps.mp3")
    assert track.title == "Nice For What"
    assert track.artist == "Drake"
    assert track.metadata_source is MetadataSource.TAGS
    assert track.analysis_status is AnalysisStatus.PENDING
    assert track.failure_reason is None
    assert track.duration_seconds is not None and track.duration_seconds > 1.0
    assert track.native_sample_rate == 22050
    assert track.channels == 1
    assert track.codec_name == "mp3"
    assert len(track.content_hash) == 64


def test_untagged_messy_filenames_fall_back_to_the_filename(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    make_mp3(library_dir, "Bad Bunny, Drake - MIA (Official Video).mp3")
    make_mp3(library_dir, "Fisher - Losing It (Extended Mix).mp3")
    make_mp3(library_dir, "just_a_weird_export_2019.mp3")

    report = service.scan()

    assert (report.scanned, report.added, report.failed) == (3, 3, 0)
    by_path = {track.audio_path: track for track in _tracks(session_factory)}

    mia = by_path["Bad Bunny, Drake - MIA (Official Video).mp3"]
    assert (mia.artist, mia.title) == ("Bad Bunny, Drake", "MIA")
    assert mia.metadata_source is MetadataSource.FILENAME

    fisher = by_path["Fisher - Losing It (Extended Mix).mp3"]
    assert (fisher.artist, fisher.title) == ("Fisher", "Losing It (Extended Mix)")

    export = by_path["just_a_weird_export_2019.mp3"]
    assert export.artist is None
    assert export.title == "just a weird export 2019"


def test_awkward_filenames_round_trip_through_the_database(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    long_name = "Artist - " + "A Very Long Title Indeed " * 8
    filenames = [
        "Tiësto, Ava Max - The Motto (Don't Stop) [Official Video].mp3",
        "-leading dash, commas & 100% punctuation!.mp3",
        "Sigur Rós - Hoppípolla (Official Audio).mp3",
        f"{long_name.strip()}.mp3",
    ]
    for filename in filenames:
        make_mp3(library_dir, filename)

    report = service.scan()

    assert (report.scanned, report.added, report.failed) == (4, 4, 0)
    stored = {track.audio_path for track in _tracks(session_factory)}
    assert stored == set(filenames)


def test_nested_files_are_stored_relative_to_the_library_root(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    make_mp3(library_dir / "House" / "2019 rips", "Peggy Gou - Starry Night.mp3")

    service.scan()

    track = _track(session_factory, "House/2019 rips/Peggy Gou - Starry Night.mp3")
    assert track.title == "Starry Night"


def test_rescanning_is_idempotent(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    make_mp3(library_dir, "Bicep - Glue.mp3")

    first = service.scan()
    second = service.scan()

    assert (first.added, first.unchanged) == (1, 0)
    assert (second.added, second.updated, second.unchanged) == (0, 0, 1)
    assert len(_tracks(session_factory)) == 1


def test_recheck_revalidates_unchanged_files(
    service: LibraryIngestionService, library_dir: Path
) -> None:
    make_mp3(library_dir, "Bicep - Glue.mp3")
    service.scan()

    report = service.scan(recheck=True)

    assert (report.updated, report.unchanged, report.failed) == (1, 0, 0)


def test_changed_content_updates_the_hash_and_resets_analysis_state(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    filename = "Jamie xx - Gosh.mp3"
    make_mp3(library_dir, filename, frequency=220.0)
    service.scan()
    original_hash = _track(session_factory, filename).content_hash

    with session_factory() as session:
        track = TrackRepository(session).get_by_path(filename)
        assert track is not None
        track.analysis_status = AnalysisStatus.COMPLETE
        session.commit()

    make_mp3(library_dir, filename, frequency=440.0, seconds=2.5)
    report = service.scan()

    assert (report.updated, report.added) == (1, 0)
    refreshed = _track(session_factory, filename)
    assert refreshed.content_hash != original_hash
    assert refreshed.analysis_status is AnalysisStatus.PENDING
    assert len(_tracks(session_factory)) == 1


def test_corrupt_file_is_recorded_as_failed_and_the_scan_continues(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    write_corrupt_mp3(library_dir / "Drake - Corrupt Download (Lyrics).mp3")
    make_mp3(library_dir, "Working Track - Fine.mp3")

    report = service.scan()

    assert (report.scanned, report.added, report.failed) == (2, 1, 1)
    assert report.failures[0][0] == "Drake - Corrupt Download (Lyrics).mp3"

    failed = _track(session_factory, "Drake - Corrupt Download (Lyrics).mp3")
    assert failed.analysis_status is AnalysisStatus.FAILED
    assert failed.failure_reason is not None
    assert failed.failure_reason["reason"] in {
        str(SourceFailure.PROBE_FAILED),
        str(SourceFailure.NO_AUDIO_STREAM),
        str(SourceFailure.INVALID_DURATION),
        str(SourceFailure.DECODE_FAILED),
    }
    assert failed.failure_reason["detail"]
    # Naming still comes from the filename so a failed track is identifiable in the library.
    assert failed.title == "Corrupt Download"
    assert failed.artist == "Drake"

    assert _track(session_factory, "Working Track - Fine.mp3").analysis_status is (
        AnalysisStatus.PENDING
    )


def test_empty_and_non_audio_files_are_recorded_as_failed(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    write_empty_file(library_dir / "zero bytes.mp3")
    write_text_file(library_dir / "definitely not audio.mp3")

    report = service.scan()

    assert (report.scanned, report.failed) == (2, 2)
    for track in _tracks(session_factory):
        assert track.analysis_status is AnalysisStatus.FAILED
        assert track.failure_reason is not None


def test_short_files_are_rejected_by_the_duration_gate(
    fast_settings: Settings, session_factory: sessionmaker[Session], library_dir: Path
) -> None:
    strict = fast_settings.model_copy(
        update={
            "ingestion": fast_settings.ingestion.model_copy(update={"min_duration_seconds": 30.0})
        }
    )
    make_mp3(library_dir, "jingle.mp3", seconds=2.0)

    report = LibraryIngestionService(strict, session_factory).scan()

    assert (report.failed, report.added) == (1, 0)
    track = _track(session_factory, "jingle.mp3")
    assert track.failure_reason is not None
    assert track.failure_reason["reason"] == str(SourceFailure.TOO_SHORT)


def test_files_silent_all_the_way_through_are_rejected(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    make_mp3(library_dir, "silence.mp3", seconds=2.0, silent=True)

    report = service.scan()

    assert (report.failed, report.added) == (1, 0)
    track = _track(session_factory, "silence.mp3")
    assert track.failure_reason is not None
    assert track.failure_reason["reason"] == str(SourceFailure.SILENT_AUDIO)


def test_a_silent_opening_does_not_reject_a_usable_track(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    """A long intro must not be mistaken for a broken file."""
    filename = "Jon Hopkins - Immunity (Ambient Intro).mp3"
    # fast_settings validates only the first second, which is entirely silent here.
    make_mp3(library_dir, filename, seconds=4.0, silence_lead_seconds=2.0)

    report = service.scan()

    assert (report.added, report.failed) == (1, 0)
    track = _track(session_factory, filename)
    assert track.analysis_status is AnalysisStatus.PENDING
    assert track.failure_reason is None


def test_the_silence_fallback_is_bounded_by_its_own_setting(
    fast_settings: Settings, session_factory: sessionmaker[Session], library_dir: Path
) -> None:
    """Widening the window is what saves the track, not luck: narrow it and the file is rejected."""
    filename = "Slow Build - Track.mp3"
    make_mp3(library_dir, filename, seconds=4.0, silence_lead_seconds=2.0)
    narrow = fast_settings.model_copy(
        update={
            "ingestion": fast_settings.ingestion.model_copy(update={"silence_scan_seconds": 1.0})
        }
    )

    report = LibraryIngestionService(narrow, session_factory).scan()

    assert (report.failed, report.added) == (1, 0)
    track = _track(session_factory, filename)
    assert track.failure_reason is not None
    assert track.failure_reason["reason"] == str(SourceFailure.SILENT_AUDIO)


def test_a_failed_track_recovers_when_the_file_is_replaced(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    filename = "Fixed Later - Track.mp3"
    write_corrupt_mp3(library_dir / filename)
    service.scan()
    assert _track(session_factory, filename).analysis_status is AnalysisStatus.FAILED

    make_mp3(library_dir, filename)
    report = service.scan()

    assert report.updated == 1
    recovered = _track(session_factory, filename)
    assert recovered.analysis_status is AnalysisStatus.PENDING
    assert recovered.failure_reason is None
    assert len(_tracks(session_factory)) == 1


def test_ingesting_a_single_file_reports_its_outcome(
    service: LibraryIngestionService, library_dir: Path
) -> None:
    path = make_mp3(library_dir, "Duke Dumont - Ocean Drive.mp3")

    outcome = service.ingest_file(path)

    assert outcome.status is FileStatus.ADDED
    assert outcome.audio_path == "Duke Dumont - Ocean Drive.mp3"
    assert outcome.failure is None


def test_preview_resolves_naming_without_writing_rows(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    make_mp3(library_dir, "Kendrick Lamar - HUMBLE. [Official Audio].mp3")
    write_corrupt_mp3(library_dir / "broken.mp3")

    previews = sorted(service.preview(), key=lambda preview: preview.audio_path)

    assert [preview.audio_path for preview in previews] == [
        "Kendrick Lamar - HUMBLE. [Official Audio].mp3",
        "broken.mp3",
    ]
    good, broken = previews
    assert good.naming is not None
    assert (good.naming.artist, good.naming.title) == ("Kendrick Lamar", "HUMBLE.")
    assert good.failure is None
    assert broken.failure is not None
    assert _tracks(session_factory) == []


def test_an_empty_library_is_not_an_error(service: LibraryIngestionService) -> None:
    report = service.scan()

    assert (report.scanned, report.added, report.failed) == (0, 0, 0)
    assert report.elapsed_seconds >= 0.0


def test_identical_audio_at_two_paths_stays_two_tracks(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    """content_hash detects change; it never deduplicates. The path is the identity."""
    original = make_mp3(library_dir, "Peggy Gou - Starry Night.mp3")
    copy = library_dir / "Playlists" / "starry night (copy).mp3"
    copy.parent.mkdir()
    copy.write_bytes(original.read_bytes())

    report = service.scan()

    assert (report.added, report.failed) == (2, 0)
    tracks = _tracks(session_factory)
    assert [track.audio_path for track in tracks] == [
        "Peggy Gou - Starry Night.mp3",
        "Playlists/starry night (copy).mp3",
    ]
    assert tracks[0].content_hash == tracks[1].content_hash

    with session_factory() as session:
        matches = TrackRepository(session).list_by_content_hash(tracks[0].content_hash)
    assert len(matches) == 2


def test_moving_a_file_adds_a_track_and_leaves_the_old_row_behind(
    service: LibraryIngestionService, library_dir: Path, session_factory: sessionmaker[Session]
) -> None:
    """Documents a known M1 limitation: nothing prunes rows whose file has gone."""
    original = make_mp3(library_dir, "Bicep - Glue.mp3")
    service.scan()

    moved = library_dir / "Sorted" / "Bicep - Glue.mp3"
    moved.parent.mkdir()
    original.rename(moved)
    report = service.scan()

    assert (report.added, report.unchanged) == (1, 0)
    assert [track.audio_path for track in _tracks(session_factory)] == [
        "Bicep - Glue.mp3",
        "Sorted/Bicep - Glue.mp3",
    ]
