"""Continuous set assembly from already-stretched PCM; no DJ or database types."""

import numpy as np

from autodj.render.fade import equal_power_gains


def append_transition(
    mix: np.ndarray,
    incoming: np.ndarray,
    *,
    exit_sample: int,
    entry_sample: int,
    fade_frames: int,
    earliest_exit: int,
) -> np.ndarray:
    """Retain all preceding audio and the incoming tail; refuse partial/backward fades."""
    if (
        fade_frames < 1
        or exit_sample < earliest_exit
        or entry_sample < 0
        or exit_sample + fade_frames > len(mix)
        or entry_sample + fade_frames > len(incoming)
    ):
        raise ValueError("INSUFFICIENT_SESSION_WINDOW")
    out_gain, in_gain = equal_power_gains(fade_frames)
    overlap = (
        mix[exit_sample : exit_sample + fade_frames] * out_gain[:, None]
        + incoming[entry_sample : entry_sample + fade_frames] * in_gain[:, None]
    )
    return np.concatenate((mix[:exit_sample], overlap, incoming[entry_sample + fade_frames :]))
