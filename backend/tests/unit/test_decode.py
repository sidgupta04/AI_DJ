"""The decode boundary: real files in, PCM and metadata out, structured failures for the rest."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fixtures.audio import (
    make_mp3,
    write_corrupt_mp3,
    write_empty_file,
    write_text_file,
    write_wav,
)

from autodj.audio.decode import (
    SourceError,
    SourceFailure,
    decode_to_mono,
    decode_to_pcm,
    probe_source,
)

pytestmark = pytest.mark.usefixtures("require_ffmpeg")


def test_probe_reads_duration_channels_and_tags(tmp_path: Path) -> None:
    path = make_mp3(
        tmp_path,
        "Drake - Nice For What (Lyrics).mp3",
        seconds=2.0,
        tags={"title": "Nice For What", "artist": "Drake"},
    )

    metadata = probe_source(path)

    assert metadata.duration_seconds == pytest.approx(2.0, abs=0.2)
    assert metadata.sample_rate == 22050
    assert metadata.channels == 1
    assert metadata.codec_name == "mp3"
    assert metadata.tags["title"] == "Nice For What"
    assert metadata.tags["artist"] == "Drake"


def test_probe_returns_empty_tags_for_untagged_files(tmp_path: Path) -> None:
    path = make_mp3(tmp_path, "no tags here.mp3", seconds=1.0)

    metadata = probe_source(path)

    assert "title" not in metadata.tags
    assert "artist" not in metadata.tags


def test_decode_returns_finite_mono_samples_at_the_requested_rate(tmp_path: Path) -> None:
    path = make_mp3(tmp_path, "tone.mp3", seconds=2.0)

    samples = decode_to_mono(path, sample_rate=22050)

    assert samples.dtype == np.float32
    assert samples.size == pytest.approx(2.0 * 22050, rel=0.1)
    assert bool(np.isfinite(samples).all())
    assert float(np.max(np.abs(samples))) > 0.01


def test_decode_to_pcm_returns_stereo_frames(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "stereo.wav", seconds=1.0, sample_rate=22050, channels=2)

    samples = decode_to_pcm(path, sample_rate=22050, channels=2)

    assert samples.dtype == np.float32
    assert samples.ndim == 2
    assert samples.shape[1] == 2
    assert samples.shape[0] == pytest.approx(22050, rel=0.1)


def test_decode_to_pcm_resamples_to_the_requested_rate(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "native48k.wav", seconds=1.0, sample_rate=48000, channels=2)

    samples = decode_to_pcm(path, sample_rate=44100, channels=2)

    assert samples.ndim == 2
    assert samples.shape[1] == 2
    assert samples.shape[0] == pytest.approx(44100, abs=2000)


def test_decode_can_be_limited_to_a_window(tmp_path: Path) -> None:
    path = make_mp3(tmp_path, "long tone.mp3", seconds=3.0)

    samples = decode_to_mono(path, sample_rate=22050, max_seconds=1.0)

    assert samples.size == pytest.approx(22050, rel=0.15)


def test_filenames_with_spaces_punctuation_and_quotes_need_no_escaping(tmp_path: Path) -> None:
    filename = "Bad Bunny, Drake - MIA (Official Video) [feat. Someone's Friend] 100%.mp3"
    path = make_mp3(tmp_path, filename, seconds=1.0)

    metadata = probe_source(path)
    samples = decode_to_mono(path, sample_rate=22050, max_seconds=1.0)

    assert metadata.duration_seconds > 0.5
    assert samples.size > 0


def test_filename_starting_with_a_dash_is_not_read_as_an_option(tmp_path: Path) -> None:
    path = make_mp3(tmp_path, "-weird leading dash.mp3", seconds=1.0)

    assert probe_source(path).duration_seconds > 0.5
    assert decode_to_mono(path, sample_rate=22050, max_seconds=1.0).size > 0


def test_corrupt_file_fails_with_a_structured_reason(tmp_path: Path) -> None:
    path = write_corrupt_mp3(tmp_path / "corrupt.mp3")

    with pytest.raises(SourceError) as error:
        probe_source(path)

    assert error.value.failure in {
        SourceFailure.PROBE_FAILED,
        SourceFailure.NO_AUDIO_STREAM,
        SourceFailure.INVALID_DURATION,
    }
    assert error.value.as_dict()["reason"] == str(error.value.failure)
    assert error.value.as_dict()["detail"]


def test_empty_file_fails(tmp_path: Path) -> None:
    path = write_empty_file(tmp_path / "empty.mp3")

    with pytest.raises(SourceError):
        probe_source(path)


def test_non_audio_file_with_an_audio_extension_fails(tmp_path: Path) -> None:
    path = write_text_file(tmp_path / "definitely not audio.mp3")

    with pytest.raises(SourceError):
        probe_source(path)


def test_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(SourceError) as error:
        probe_source(tmp_path / "nothing here.mp3")

    assert error.value.failure is SourceFailure.PROBE_FAILED


def test_wav_sources_are_supported_too(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "clip.wav", seconds=1.0, channels=2)

    metadata = probe_source(path)

    assert metadata.channels == 2
    assert decode_to_mono(path, sample_rate=22050).size > 0
