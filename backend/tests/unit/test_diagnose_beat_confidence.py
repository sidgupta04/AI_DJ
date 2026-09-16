from __future__ import annotations

import importlib.util
import sys
import wave
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest


def _load_diagnostic_module() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts" / "diagnose_beat_confidence.py"
    spec = importlib.util.spec_from_file_location("diagnose_beat_confidence", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_DIAGNOSTIC_MODULE = _load_diagnostic_module()
overlay_beat_clicks: Callable[..., np.ndarray] = _DIAGNOSTIC_MODULE.overlay_beat_clicks
write_click_overlay_wav: Callable[..., None] = _DIAGNOSTIC_MODULE._write_click_overlay_wav


def test_beat_click_overlay_preserves_audio_and_places_clicks_at_beat_positions() -> None:
    sample_rate = 44_100
    source = np.full(sample_rate, 0.05, dtype=np.float32)
    beats = np.array([0.25, 0.75], dtype=np.float64)

    overlay = overlay_beat_clicks(source, beats, sample_rate=sample_rate)

    assert overlay.dtype == np.float32
    np.testing.assert_array_equal(overlay[:100], source[:100])
    for timestamp in beats:
        start = round(float(timestamp) * sample_rate)
        assert overlay[start] > source[start] + 0.5
        assert np.max(np.abs(overlay[start : start + 100])) > 0.5


def test_beat_click_overlay_peak_normalizes_a_hot_source() -> None:
    sample_rate = 44_100
    source = np.full(sample_rate, 0.9, dtype=np.float32)

    overlay = overlay_beat_clicks(source, np.array([0.5]), sample_rate=sample_rate)

    assert float(np.max(np.abs(overlay))) <= 0.98
    assert float(overlay[100]) > 0.0


def test_click_overlay_writer_creates_mono_pcm_wav_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "track.beats.wav"
    write_click_overlay_wav(path, np.zeros(128, dtype=np.float32), sample_rate=22_050)

    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 22_050
        assert handle.getnframes() == 128

    with pytest.raises(FileExistsError):
        write_click_overlay_wav(path, np.zeros(128, dtype=np.float32), sample_rate=22_050)
