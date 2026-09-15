from __future__ import annotations

import numpy as np
import pytest

from autodj.render.stretch import PedalboardStretcher, build_stretcher, remap_beat_times
from autodj.render.types import RenderError, RenderFailure


def test_pedalboard_shortens_audio_when_stretch_ratio_is_above_one() -> None:
    sample_rate = 44100
    seconds = 1.0
    times = np.arange(int(seconds * sample_rate), dtype=np.float32) / sample_rate
    tone = np.sin(2 * np.pi * 440.0 * times).astype(np.float32)
    stereo = np.stack([tone, tone], axis=1)

    stretched = PedalboardStretcher().stretch(stereo, stretch_ratio=1.05, sample_rate=sample_rate)

    expected = stereo.shape[0] / 1.05
    assert stretched.ndim == 2
    assert stretched.shape[1] == 2
    assert stretched.shape[0] == pytest.approx(expected, rel=0.03)


def test_identity_ratio_returns_a_copy_without_resampling() -> None:
    audio = np.linspace(-0.5, 0.5, 1000, dtype=np.float32).reshape(1000, 1)
    stretched = PedalboardStretcher().stretch(audio, stretch_ratio=1.0, sample_rate=44100)
    assert stretched.shape == audio.shape
    np.testing.assert_array_equal(stretched, audio)
    assert stretched is not audio


def test_remap_beat_times_divides_by_stretch_ratio() -> None:
    times = np.array([0.0, 0.5, 1.0, 1.5], dtype=np.float64)
    remapped = remap_beat_times(times, 1.25)
    np.testing.assert_allclose(remapped, times / 1.25)


def test_unsupported_backend_is_a_named_failure() -> None:
    with pytest.raises(RenderError) as error:
        build_stretcher("phase_vocoder")
    assert error.value.failure is RenderFailure.BACKEND_UNSUPPORTED
