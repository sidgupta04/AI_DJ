"""Measured transition diagnostics. Pure arrays in, values out; no render/DJ imports."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AlignmentMeasurement:
    error_ms: float | None
    correlation: float | None
    reason: str | None


def onset_envelope(audio: np.ndarray, *, hop_samples: int) -> np.ndarray:
    """Positive first difference of block RMS, combining channel power (no phase cancellation)."""
    values = np.asarray(audio, dtype=np.float64)
    if values.ndim == 1:
        values = values[:, None]
    if values.ndim != 2 or not np.isfinite(values).all() or hop_samples < 1:
        raise ValueError("expected finite mono/stereo PCM and a positive hop")
    count = len(values) // hop_samples
    if count < 2:
        return np.array([], dtype=np.float64)
    blocks = values[: count * hop_samples].reshape(count, -1)
    rms = np.sqrt(np.mean(blocks**2, axis=1))
    return np.maximum(0.0, np.diff(rms, prepend=rms[0]))


def alignment_error(
    outgoing: np.ndarray,
    incoming: np.ndarray,
    *,
    sample_rate: int,
    hop_ms: float,
    max_lag_ms: float,
    session_bpm: float,
    min_correlation: float,
    silence_floor_dbfs: float,
) -> AlignmentMeasurement:
    """Absolute best lag from normalized onset correlation of actual, unfaded overlap PCM.

    A single lag estimates average phase offset, not tempo drift or true downbeat correctness.
    Search below half a beat to avoid reporting the next periodic beat as the matched beat.
    """
    if sample_rate <= 0 or session_bpm <= 0 or hop_ms <= 0 or max_lag_ms <= 0:
        raise ValueError("rate, BPM, hop and lag must be positive")
    hop = max(1, round(sample_rate * hop_ms / 1000))
    a = onset_envelope(outgoing, hop_samples=hop)
    b = onset_envelope(incoming, hop_samples=hop)
    count = min(len(a), len(b))
    if count < 3:
        return AlignmentMeasurement(None, None, "INSUFFICIENT_ONSETS")
    a, b = a[:count], b[:count]
    floor = 10 ** (silence_floor_dbfs / 20)
    if max(a) <= floor or max(b) <= floor:
        return AlignmentMeasurement(None, None, "SILENT_OR_CONSTANT_OVERLAP")
    # Center once so lag-dependent means cannot make very short tails look perfect.
    a, b = a - np.mean(a), b - np.mean(b)
    max_lag = min(
        int(max_lag_ms * sample_rate / (1000 * hop)),
        max(0, int(30 * sample_rate / (session_bpm * hop)) - 1),
        (count - 1) // 2,
    )
    scores: list[tuple[float, int]] = []
    for lag in range(-max_lag, max_lag + 1):
        x, y = (a[-lag:], b[: count + lag]) if lag < 0 else (a[: count - lag], b[lag:])
        norm = float(np.linalg.norm(x) * np.linalg.norm(y))
        score = float(np.dot(x, y) / norm) if norm > 0 else 0.0
        scores.append((score, lag))
    score, lag = max(scores, key=lambda item: (item[0], -abs(item[1]), -item[1]))
    score = float(np.clip(score, -1, 1))
    if score < min_correlation:
        return AlignmentMeasurement(None, score, "WEAK_CORRELATION")
    return AlignmentMeasurement(abs(lag) * hop * 1000 / sample_rate, score, None)


def energy_discontinuity_db(
    overlap: np.ndarray, *, sample_rate: int, window_seconds: float, floor_dbfs: float
) -> float | None:
    """Absolute dB RMS difference between equal first/last windows of the mixed overlap."""
    values = np.asarray(overlap, dtype=np.float64)
    if not np.isfinite(values).all() or sample_rate <= 0 or window_seconds <= 0:
        raise ValueError("expected finite PCM and positive sample rate/window")
    count = min(round(window_seconds * sample_rate), len(values) // 2)
    if count < 1:
        return None
    floor = 10 ** (floor_dbfs / 20)
    first = max(floor, float(np.sqrt(np.mean(values[:count] ** 2))))
    last = max(floor, float(np.sqrt(np.mean(values[-count:] ** 2))))
    return abs(20 * float(np.log10(last / first)))
