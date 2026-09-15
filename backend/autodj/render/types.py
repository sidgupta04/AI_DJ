"""Dataclasses and failure reasons for audio rendering.

Array-in, values-out. No database, no HTTP, no ``autodj.dj`` types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class RenderFailure(StrEnum):
    """Named reasons a mix cannot be rendered. Persisted on ``transitions.failure_reason``."""

    STRETCH_OUT_OF_BOUNDS = "STRETCH_OUT_OF_BOUNDS"
    BACKEND_UNSUPPORTED = "BACKEND_UNSUPPORTED"
    MISSING_BEAT = "MISSING_BEAT"
    INSUFFICIENT_AUDIO = "INSUFFICIENT_AUDIO"
    EMPTY_AUDIO = "EMPTY_AUDIO"
    MISSING_FILE = "MISSING_FILE"
    MISSING_TRACK = "MISSING_TRACK"
    DECODE_FAILED = "DECODE_FAILED"
    WRITE_FAILED = "WRITE_FAILED"


class RenderError(Exception):
    """A render-time failure with a machine-readable reason."""

    def __init__(self, failure: RenderFailure, detail: str) -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"reason": str(self.failure), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class RenderedMix:
    """A mixed transition in float32 PCM, plus peak diagnostics.

    ``audio`` is shape ``(n_samples, channels)``, already clip-protected into
    ``[-1, 1]``. ``peak_dbfs`` is measured *before* that protection.
    """

    audio: np.ndarray
    sample_rate: int
    peak_dbfs: float
    peak_exceeded: bool
    clipped: bool
    stretch_ratio_a: float
    stretch_ratio_b: float
    fade_start_sample: int
    fade_frames: int
