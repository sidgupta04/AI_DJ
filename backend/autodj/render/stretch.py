"""Pitch-preserving constant time stretch.

``stretch_ratio`` is ``session_bpm / native_bpm``: values above 1.0 play the
audio faster and shorter, matching ``pedalboard.time_stretch`` and the M4
planner. Beat times then map linearly as ``t' = t / stretch_ratio``.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pedalboard

from autodj.render.types import RenderError, RenderFailure

STRETCH_BOUND_ATOL = 1e-12
IDENTITY_STRETCH_ATOL = 1e-12


class TimeStretcher(Protocol):
    def stretch(
        self,
        audio: np.ndarray,
        *,
        stretch_ratio: float,
        sample_rate: int,
    ) -> np.ndarray:
        """Return ``audio`` stretched by ``stretch_ratio``. Shape ``(n, c)``."""
        ...


class PedalboardStretcher:
    """Rubber Band via pedalboard. The V1 default backend."""

    def stretch(
        self,
        audio: np.ndarray,
        *,
        stretch_ratio: float,
        sample_rate: int,
    ) -> np.ndarray:
        layout = _ensure_sample_first(audio)
        if abs(stretch_ratio - 1.0) <= IDENTITY_STRETCH_ATOL:
            return np.array(layout, copy=True, dtype=np.float32)
        channel_first = np.ascontiguousarray(layout.T, dtype=np.float32)
        stretched = pedalboard.time_stretch(
            channel_first,
            float(sample_rate),
            stretch_factor=float(stretch_ratio),
        )
        return _ensure_sample_first(stretched)


def build_stretcher(backend: str) -> TimeStretcher:
    """Return the configured stretcher. Only ``pedalboard`` is implemented in M5."""
    if backend == "pedalboard":
        return PedalboardStretcher()
    raise RenderError(
        RenderFailure.BACKEND_UNSUPPORTED,
        f"{backend!r} is a documented swap path, not implemented; use pedalboard",
    )


def remap_beat_times(beat_times: np.ndarray, stretch_ratio: float) -> np.ndarray:
    """Map original beat times through a constant stretch: ``t' = t / stretch``."""
    if stretch_ratio <= 0.0:
        raise RenderError(
            RenderFailure.STRETCH_OUT_OF_BOUNDS,
            f"stretch_ratio must be positive, got {stretch_ratio}",
        )
    times = np.asarray(beat_times, dtype=np.float64)
    return times / stretch_ratio


def _ensure_sample_first(audio: np.ndarray) -> np.ndarray:
    """Normalise to ``(n_samples, n_channels)`` float32."""
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 1:
        return array[:, np.newaxis]
    if array.ndim != 2:
        raise ValueError(f"audio must be 1-D or 2-D, got shape {array.shape}")
    rows, cols = array.shape
    if rows <= 8 and cols > rows:
        return np.ascontiguousarray(array.T, dtype=np.float32)
    return np.ascontiguousarray(array, dtype=np.float32)
