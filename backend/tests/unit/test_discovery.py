"""File discovery and content hashing, neither of which needs a database."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.audio import write_text_file, write_wav

from autodj.config.settings import Settings
from autodj.services.ingestion import LibraryIngestionService, compute_content_hash


def _service(settings: Settings) -> LibraryIngestionService:
    # discover() and hashing never open a session, so the factory is deliberately unusable.
    return LibraryIngestionService(settings, None)  # type: ignore[arg-type]


def test_discovery_finds_audio_recursively_and_deterministically(
    fast_settings: Settings, library_dir: Path
) -> None:
    write_wav(library_dir / "b track.wav", seconds=0.2)
    write_wav(library_dir / "a track.wav", seconds=0.2)
    write_wav(library_dir / "nested" / "deep" / "c track.wav", seconds=0.2)

    found = _service(fast_settings).discover()

    assert [path.name for path in found] == ["a track.wav", "b track.wav", "c track.wav"]
    assert found == _service(fast_settings).discover()


def test_discovery_skips_non_audio_and_hidden_files(
    fast_settings: Settings, library_dir: Path
) -> None:
    write_wav(library_dir / "keep me.wav", seconds=0.2)
    write_text_file(library_dir / "notes.txt")
    write_text_file(library_dir / "cover.jpg")
    write_wav(library_dir / ".hidden.wav", seconds=0.2)

    found = _service(fast_settings).discover()

    assert [path.name for path in found] == ["keep me.wav"]


def test_discovery_matches_extensions_case_insensitively(
    fast_settings: Settings, library_dir: Path
) -> None:
    write_wav(library_dir / "SHOUTING.WAV", seconds=0.2)

    assert [path.name for path in _service(fast_settings).discover()] == ["SHOUTING.WAV"]


def test_missing_library_directory_is_reported_clearly(
    fast_settings: Settings, tmp_path: Path
) -> None:
    missing = tmp_path / "not there"

    with pytest.raises(NotADirectoryError, match="audio library directory not found"):
        _service(fast_settings).discover(missing)


def test_content_hash_is_stable_and_changes_with_content(tmp_path: Path) -> None:
    """The hash depends on bytes alone: same content hashes alike whatever the file is called."""
    first = tmp_path / "one.bin"
    first.write_bytes(b"identical bytes")
    second = tmp_path / "two.bin"
    second.write_bytes(b"identical bytes")

    assert compute_content_hash(first) == compute_content_hash(second)
    assert len(compute_content_hash(first)) == 64

    first.write_bytes(b"different bytes")
    assert compute_content_hash(first) != compute_content_hash(second)
