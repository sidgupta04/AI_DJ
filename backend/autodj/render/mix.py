"""Compose stretch, alignment, and an equal-power crossfade into one mix.

Inputs are PCM arrays and beat times. The function does not import
``autodj.dj``; the service maps a ``TransitionPlan`` onto these arguments.
"""

from __future__ import annotations

import numpy as np

from autodj.render.align import alignment_beat_index
from autodj.render.fade import equal_power_gains
from autodj.render.stretch import (
    STRETCH_BOUND_ATOL,
    TimeStretcher,
    remap_beat_times,
)
from autodj.render.types import RenderedMix, RenderError, RenderFailure
from autodj.render.write import apply_clip_protection, ensure_channel_layout


def render_transition(
    outgoing: np.ndarray,
    incoming: np.ndarray,
    *,
    outgoing_beat_times: np.ndarray,
    incoming_beat_times: np.ndarray,
    outgoing_native_bpm: float,
    incoming_native_bpm: float,
    session_bpm: float,
    outgoing_start_beat: int,
    outgoing_end_beat: int,
    incoming_start_beat: int,
    incoming_end_beat: int,
    stretcher: TimeStretcher,
    sample_rate: int,
    channels: int,
    min_stretch_ratio: float,
    max_stretch_ratio: float,
    crossfade_beats: int,
    margin_beats: int,
    align_on_downbeat: bool,
    peak_ceiling_dbfs: float,
) -> RenderedMix:
    """Stretch both stems, align the chosen beats, and equal-power crossfade.

    ``outgoing`` and ``incoming`` must already be at ``sample_rate``. The
    crossfade lasts ``crossfade_beats`` intervals at ``session_bpm`` (32 beats
    = 8 bars = 32 × 60 / BPM seconds).
    """
    stretch_a = _validated_stretch(
        session_bpm, outgoing_native_bpm, min_stretch_ratio, max_stretch_ratio, "outgoing"
    )
    stretch_b = _validated_stretch(
        session_bpm, incoming_native_bpm, min_stretch_ratio, max_stretch_ratio, "incoming"
    )

    audio_a = stretcher.stretch(
        ensure_channel_layout(outgoing, channels),
        stretch_ratio=stretch_a,
        sample_rate=sample_rate,
    )
    audio_b = stretcher.stretch(
        ensure_channel_layout(incoming, channels),
        stretch_ratio=stretch_b,
        sample_rate=sample_rate,
    )
    audio_a = ensure_channel_layout(audio_a, channels)
    audio_b = ensure_channel_layout(audio_b, channels)

    beats_a = remap_beat_times(outgoing_beat_times, stretch_a)
    beats_b = remap_beat_times(incoming_beat_times, stretch_b)

    align_a = alignment_beat_index(
        outgoing_start_beat,
        outgoing_end_beat,
        beats_a.size,
        align_on_downbeat=align_on_downbeat,
    )
    align_b = alignment_beat_index(
        incoming_start_beat,
        incoming_end_beat,
        beats_b.size,
        align_on_downbeat=align_on_downbeat,
    )
    _require_beat(align_a, beats_a.size, "outgoing")
    _require_beat(align_b, beats_b.size, "incoming")

    align_a_sample = _seconds_to_samples(float(beats_a[align_a]), sample_rate)
    align_b_sample = _seconds_to_samples(float(beats_b[align_b]), sample_rate)
    fade_samples = _beats_to_samples(crossfade_beats, session_bpm, sample_rate)
    margin_samples = _beats_to_samples(margin_beats, session_bpm, sample_rate)

    available_fade = min(
        audio_a.shape[0] - align_a_sample,
        audio_b.shape[0] - align_b_sample,
    )
    if available_fade < 1 or fade_samples < 1:
        raise RenderError(
            RenderFailure.INSUFFICIENT_AUDIO,
            "not enough samples after the alignment beat for a crossfade",
        )
    fade_samples = min(fade_samples, available_fade)

    pre_samples = min(margin_samples, max(0, align_a_sample))
    post_limit = audio_b.shape[0] - (align_b_sample + fade_samples)
    post_samples = min(margin_samples, max(0, post_limit))

    outgoing_pre = audio_a[align_a_sample - pre_samples : align_a_sample]
    outgoing_fade = audio_a[align_a_sample : align_a_sample + fade_samples]
    incoming_fade = audio_b[align_b_sample : align_b_sample + fade_samples]
    incoming_post = audio_b[
        align_b_sample + fade_samples : align_b_sample + fade_samples + post_samples
    ]

    gains_out, gains_in = equal_power_gains(fade_samples)
    faded = outgoing_fade * gains_out[:, np.newaxis] + incoming_fade * gains_in[:, np.newaxis]
    pieces = [piece for piece in (outgoing_pre, faded, incoming_post) if piece.size]
    if not pieces:
        raise RenderError(RenderFailure.EMPTY_AUDIO, "mix assembled to zero samples")
    mixed = np.concatenate(pieces, axis=0)

    protected, peak_dbfs, peak_exceeded, clipped = apply_clip_protection(
        mixed, peak_ceiling_dbfs=peak_ceiling_dbfs
    )
    return RenderedMix(
        audio=protected,
        sample_rate=sample_rate,
        peak_dbfs=peak_dbfs,
        peak_exceeded=peak_exceeded,
        clipped=clipped,
        stretch_ratio_a=stretch_a,
        stretch_ratio_b=stretch_b,
        fade_start_sample=pre_samples,
        fade_frames=fade_samples,
    )


def _validated_stretch(
    session_bpm: float,
    native_bpm: float,
    min_ratio: float,
    max_ratio: float,
    label: str,
) -> float:
    if session_bpm <= 0.0 or native_bpm <= 0.0:
        raise RenderError(
            RenderFailure.STRETCH_OUT_OF_BOUNDS,
            f"{label} stretch needs positive BPM (session={session_bpm}, native={native_bpm})",
        )
    ratio = session_bpm / native_bpm
    if not (min_ratio - STRETCH_BOUND_ATOL <= ratio <= max_ratio + STRETCH_BOUND_ATOL):
        raise RenderError(
            RenderFailure.STRETCH_OUT_OF_BOUNDS,
            f"{label} stretch {ratio:.6f} is outside [{min_ratio}, {max_ratio}]",
        )
    return ratio


def _require_beat(index: int, count: int, label: str) -> None:
    if index < 0 or index >= count:
        raise RenderError(
            RenderFailure.MISSING_BEAT,
            f"{label} alignment beat {index} is outside [0, {count})",
        )


def _seconds_to_samples(seconds: float, sample_rate: int) -> int:
    return int(round(seconds * sample_rate))


def _beats_to_samples(beats: int, bpm: float, sample_rate: int) -> int:
    """Convert ``beats`` *intervals* at ``bpm`` to a sample count.

    A 32-beat / 8-bar crossfade is 32 inter-beat periods, not 32 timestamps
    (which would span 31 periods). The half-open slice
    ``[align, align + count)`` then lasts ``count / sample_rate`` seconds.
    """
    if beats <= 0 or bpm <= 0.0:
        return 0
    return max(1, int(round(beats * 60.0 / bpm * sample_rate)))
