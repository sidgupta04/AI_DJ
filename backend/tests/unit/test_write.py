from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from autodj.render.write import apply_clip_protection, peak_dbfs, write_pcm16_wav


def test_clip_protection_scales_peaks_above_unity_and_flags_them() -> None:
    audio = np.full((4, 2), 1.5, dtype=np.float32)
    protected, peak_db, exceeded, clipped = apply_clip_protection(audio, peak_ceiling_dbfs=-1.0)
    assert clipped is True
    assert exceeded is True
    assert peak_db == pytest.approx(20.0 * np.log10(1.5))
    assert float(np.max(np.abs(protected))) == pytest.approx(1.0)


def test_peak_below_ceiling_is_not_flagged() -> None:
    audio = np.full((8, 2), 0.5, dtype=np.float32)
    protected, peak_db, exceeded, clipped = apply_clip_protection(audio, peak_ceiling_dbfs=-1.0)
    assert clipped is False
    assert exceeded is False
    assert peak_db == pytest.approx(20.0 * np.log10(0.5))
    np.testing.assert_array_equal(protected, audio)


def test_write_pcm16_wav_is_stereo_sixteen_bit(tmp_path: Path) -> None:
    audio = np.zeros((100, 2), dtype=np.float32)
    audio[10] = 0.5
    path = tmp_path / "mix.wav"
    write_pcm16_wav(path, audio, sample_rate=44100)

    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 2
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 44100
        assert handle.getnframes() == 100


def test_failed_write_leaves_neither_destination_nor_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mix.wav"
    audio = np.zeros((100, 2), dtype=np.float32)

    def _boom(target: Path, payload: np.ndarray, *, sample_rate: int) -> None:
        del payload, sample_rate
        target.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr("autodj.render.write._write_pcm16_wav", _boom)

    with pytest.raises(OSError, match="disk full"):
        write_pcm16_wav(path, audio, sample_rate=44100)

    assert not path.exists()
    assert list(tmp_path.glob(".mix.wav.*.tmp")) == []


def test_silent_audio_has_a_finite_peak_dbfs() -> None:
    assert peak_dbfs(np.zeros((16, 2), dtype=np.float32)) == -120.0
