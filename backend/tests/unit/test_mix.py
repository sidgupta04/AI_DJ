from __future__ import annotations

import numpy as np
import pytest

from autodj.render.mix import render_transition
from autodj.render.types import RenderError, RenderFailure


class _CopyStretcher:
    def stretch(self, audio: np.ndarray, *, stretch_ratio: float, sample_rate: int) -> np.ndarray:
        del stretch_ratio, sample_rate
        return np.array(audio, copy=True, dtype=np.float32)


def _grid(bpm: float, beats: int) -> np.ndarray:
    return np.arange(beats, dtype=np.float64) * (60.0 / bpm)


def _tone(
    seconds: float, sample_rate: int, *, amplitude: float = 0.4, frequency: float = 220.0
) -> np.ndarray:
    times = np.arange(int(seconds * sample_rate), dtype=np.float64) / sample_rate
    mono = (amplitude * np.sin(2 * np.pi * frequency * times)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_mix_places_the_outgoing_alignment_beat_at_the_fade_start() -> None:
    sample_rate = 8000
    bpm = 120.0
    seconds = 8.0
    beats = _grid(bpm, 16)
    audio_a = np.zeros((int(seconds * sample_rate), 2), dtype=np.float32)
    audio_b = np.zeros((int(seconds * sample_rate), 2), dtype=np.float32)
    align_a = int(round(beats[8] * sample_rate))
    audio_a[align_a] = 1.0

    mix = render_transition(
        audio_a,
        audio_b,
        outgoing_beat_times=beats,
        incoming_beat_times=beats,
        outgoing_native_bpm=bpm,
        incoming_native_bpm=bpm,
        session_bpm=bpm,
        outgoing_start_beat=8,
        outgoing_end_beat=12,
        incoming_start_beat=0,
        incoming_end_beat=4,
        stretcher=_CopyStretcher(),
        sample_rate=sample_rate,
        channels=2,
        min_stretch_ratio=0.95,
        max_stretch_ratio=1.05,
        crossfade_beats=4,
        margin_beats=2,
        align_on_downbeat=False,
        peak_ceiling_dbfs=-1.0,
    )

    assert mix.stretch_ratio_a == pytest.approx(1.0)
    assert mix.stretch_ratio_b == pytest.approx(1.0)
    peak_at_fade = float(np.max(np.abs(mix.audio[mix.fade_start_sample])))
    assert peak_at_fade == pytest.approx(1.0, abs=1e-5)
    expected_margin = int(round(2 * 60.0 / bpm * sample_rate))
    assert mix.fade_start_sample == expected_margin


def test_mix_is_stereo_and_covers_margin_plus_fade() -> None:
    sample_rate = 8000
    bpm = 120.0
    mix = render_transition(
        _tone(6.0, sample_rate),
        _tone(6.0, sample_rate, frequency=330.0),
        outgoing_beat_times=_grid(bpm, 16),
        incoming_beat_times=_grid(bpm, 16),
        outgoing_native_bpm=bpm,
        incoming_native_bpm=bpm,
        session_bpm=bpm,
        outgoing_start_beat=4,
        outgoing_end_beat=8,
        incoming_start_beat=0,
        incoming_end_beat=4,
        stretcher=_CopyStretcher(),
        sample_rate=sample_rate,
        channels=2,
        min_stretch_ratio=0.95,
        max_stretch_ratio=1.05,
        crossfade_beats=4,
        margin_beats=2,
        align_on_downbeat=False,
        peak_ceiling_dbfs=-1.0,
    )
    fade = int(round(4 * 60.0 / bpm * sample_rate))
    margin = int(round(2 * 60.0 / bpm * sample_rate))
    assert mix.audio.shape[1] == 2
    assert mix.audio.shape[0] == margin + fade + margin
    assert mix.audio.dtype == np.float32
    assert mix.clipped is False


def test_thirty_two_beat_crossfade_is_exactly_thirty_two_intervals() -> None:
    """32 beats means 32 inter-beat periods, not 31 (timestamp count − 1)."""
    sample_rate = 44100
    bpm = 120.0
    crossfade_beats = 32
    # Long enough for align at beat 8 plus 32-beat fade plus margin.
    seconds = 30.0
    beats = _grid(bpm, 80)
    expected_fade = int(round(crossfade_beats * 60.0 / bpm * sample_rate))
    assert expected_fade == 705_600  # 32 × 0.5 s × 44100
    # Interval span equals beat[align+32] − beat[align] on a perfect grid.
    assert beats[8 + crossfade_beats] - beats[8] == pytest.approx(crossfade_beats * 60.0 / bpm)

    mix = render_transition(
        _tone(seconds, sample_rate),
        _tone(seconds, sample_rate, frequency=330.0),
        outgoing_beat_times=beats,
        incoming_beat_times=beats,
        outgoing_native_bpm=bpm,
        incoming_native_bpm=bpm,
        session_bpm=bpm,
        outgoing_start_beat=8,
        outgoing_end_beat=16,
        incoming_start_beat=0,
        incoming_end_beat=8,
        stretcher=_CopyStretcher(),
        sample_rate=sample_rate,
        channels=2,
        min_stretch_ratio=0.95,
        max_stretch_ratio=1.05,
        crossfade_beats=crossfade_beats,
        margin_beats=0,
        align_on_downbeat=False,
        peak_ceiling_dbfs=-1.0,
    )

    assert mix.fade_frames == expected_fade
    assert mix.fade_start_sample == 0
    assert mix.audio.shape[0] == expected_fade
    # Half-open [align, align + fade): last fade sample is exclusive of the end beat.
    align_sample = int(round(float(beats[8]) * sample_rate))
    end_sample = align_sample + mix.fade_frames
    assert end_sample - align_sample == expected_fade
    assert end_sample == int(round(float(beats[8 + crossfade_beats]) * sample_rate))


def test_refuses_a_stretch_outside_the_hard_bound() -> None:
    sample_rate = 8000
    audio = _tone(2.0, sample_rate)
    beats = _grid(120.0, 8)
    with pytest.raises(RenderError) as error:
        render_transition(
            audio,
            audio,
            outgoing_beat_times=beats,
            incoming_beat_times=beats,
            outgoing_native_bpm=120.0,
            incoming_native_bpm=110.0,
            session_bpm=120.0,
            outgoing_start_beat=0,
            outgoing_end_beat=4,
            incoming_start_beat=0,
            incoming_end_beat=4,
            stretcher=_CopyStretcher(),
            sample_rate=sample_rate,
            channels=2,
            min_stretch_ratio=0.95,
            max_stretch_ratio=1.05,
            crossfade_beats=4,
            margin_beats=1,
            align_on_downbeat=False,
            peak_ceiling_dbfs=-1.0,
        )
    assert error.value.failure is RenderFailure.STRETCH_OUT_OF_BOUNDS
    # 120/110 ≈ 1.0909, outside ±5%.
    assert 120.0 / 110.0 > 1.05
