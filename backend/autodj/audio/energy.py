"""Per-track energy curve.

Takes mono PCM and returns a 10 Hz energy signal plus an aggregated scalar. RMS (dBFS
mapped through a fixed window) and onset strength are each put on ``[0, 1]`` *before*
they are mixed: ``E(t) = alpha * R(t) + (1 - alpha) * O(t)``. Adding a raw dBFS number
to a raw onset number would let units, not musical weight, decide the mix.

Library-wide 5th/95th scaling of the aggregated scalar is a persistence concern: this
module only sees one track.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

RMS_EPSILON = 1e-12
PERCENTILE_SPAN_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class EnergyAnalysis:
    """Combined energy curve at ``curve_hz``, plus the hop-rate unit onset used by regions."""

    curve: np.ndarray
    curve_hz: float
    scalar: float
    onset_unit: np.ndarray
    sample_rate: int
    hop_length: int


def analyze_energy(
    samples: np.ndarray,
    *,
    sample_rate: int,
    hop_length: int,
    alpha: float,
    rms_floor_db: float,
    rms_ceiling_db: float,
    curve_hz: float,
    aggregation: str,
    onset_low_percentile: float,
    onset_high_percentile: float,
) -> EnergyAnalysis:
    """Build a combined energy curve from mono float PCM."""
    if samples.ndim != 1:
        raise ValueError("analyze_energy expects mono samples with shape (n,)")
    if samples.size == 0:
        empty = np.zeros(0, dtype=np.float64)
        return EnergyAnalysis(
            curve=empty,
            curve_hz=curve_hz,
            scalar=0.0,
            onset_unit=empty,
            sample_rate=sample_rate,
            hop_length=hop_length,
        )

    onset = np.asarray(
        librosa.onset.onset_strength(y=samples, sr=sample_rate, hop_length=hop_length),
        dtype=np.float64,
    )
    frame_length = min(2 * hop_length, int(samples.size))
    frame_length = max(frame_length, 1)
    rms = np.asarray(
        librosa.feature.rms(y=samples, frame_length=frame_length, hop_length=hop_length)[0],
        dtype=np.float64,
    )
    length = min(onset.size, rms.size)
    onset = onset[:length]
    rms = rms[:length]
    rms_unit = _map_dbfs_to_unit(rms, floor_db=rms_floor_db, ceiling_db=rms_ceiling_db)
    onset_unit = _map_by_percentiles(
        onset, low_percentile=onset_low_percentile, high_percentile=onset_high_percentile
    )
    combined = alpha * rms_unit + (1.0 - alpha) * onset_unit
    hop_times = librosa.frames_to_time(np.arange(length), sr=sample_rate, hop_length=hop_length)
    curve = _resample_curve(
        combined,
        hop_times,
        sample_count=samples.size,
        sample_rate=sample_rate,
        curve_hz=curve_hz,
    )
    return EnergyAnalysis(
        curve=curve,
        curve_hz=curve_hz,
        scalar=_aggregate(curve, aggregation),
        onset_unit=onset_unit,
        sample_rate=sample_rate,
        hop_length=hop_length,
    )


def _map_dbfs_to_unit(rms: np.ndarray, *, floor_db: float, ceiling_db: float) -> np.ndarray:
    """Linear map of RMS dBFS through ``[floor_db, ceiling_db]``, clamped to ``[0, 1]``."""
    rms_db = 20.0 * np.log10(np.maximum(rms, RMS_EPSILON))
    span = ceiling_db - floor_db
    if span <= 0:
        raise ValueError("rms_ceiling_db must be above rms_floor_db")
    return np.clip((rms_db - floor_db) / span, 0.0, 1.0)


def _map_by_percentiles(
    values: np.ndarray, *, low_percentile: float, high_percentile: float
) -> np.ndarray:
    """Robust per-track map onto ``[0, 1]``. A zero span (silence) stays at 0."""
    if values.size == 0:
        return values.astype(np.float64, copy=True)
    low = float(np.percentile(values, low_percentile))
    high = float(np.percentile(values, high_percentile))
    span = high - low
    if span <= PERCENTILE_SPAN_EPSILON:
        return np.zeros(values.size, dtype=np.float64)
    return np.clip((values - low) / span, 0.0, 1.0)


def _resample_curve(
    values: np.ndarray,
    times: np.ndarray,
    *,
    sample_count: int,
    sample_rate: int,
    curve_hz: float,
) -> np.ndarray:
    duration = sample_count / sample_rate
    if duration <= 0 or values.size == 0:
        return np.zeros(0, dtype=np.float64)
    step = 1.0 / curve_hz
    grid = np.arange(0.0, duration, step, dtype=np.float64)
    if times.size == 1:
        return np.full(grid.size, float(values[0]), dtype=np.float64)
    return np.interp(grid, times, values).astype(np.float64, copy=False)


def _aggregate(curve: np.ndarray, method: str) -> float:
    if curve.size == 0:
        return 0.0
    if method == "mean":
        return float(np.mean(curve))
    if method == "median":
        return float(np.median(curve))
    if method == "p90":
        return float(np.percentile(curve, 90))
    raise ValueError(f"unknown energy aggregation {method!r}")
