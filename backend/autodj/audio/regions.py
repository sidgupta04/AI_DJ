"""Stable mixable regions on a beat grid.

Sliding 32-beat windows, stepped 4 beats, gated on inter-beat-interval regularity and
onset strength, then reduced by non-maximum suppression. A track that has a tempo but
no surviving window is not mixable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

INTERVAL_EPSILON = 1e-12


class RegionFailure(StrEnum):
    """Structured reason a beat grid has no mixable passage."""

    NO_STABLE_REGION = "NO_STABLE_REGION"


class RegionDetectionError(Exception):
    """Region detection failed with a machine-readable reason and a human-readable detail."""

    def __init__(self, failure: RegionFailure, detail: str) -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"reason": str(self.failure), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class StableRegion:
    start_beat: int
    end_beat: int
    start_time: float
    end_time: float
    score: float
    ibi_cv: float
    in_tolerance_fraction: float
    mean_onset: float
    mean_energy: float

    def overlaps(self, other: StableRegion) -> bool:
        return self.start_beat < other.end_beat and other.start_beat < self.end_beat

    def as_dict(self) -> dict[str, float | int]:
        return {
            "start_beat": self.start_beat,
            "end_beat": self.end_beat,
            "start_time": round(self.start_time, 6),
            "end_time": round(self.end_time, 6),
            "score": round(self.score, 6),
            "ibi_cv": round(self.ibi_cv, 6),
            "in_tolerance_fraction": round(self.in_tolerance_fraction, 6),
            "mean_onset": round(self.mean_onset, 6),
            "mean_energy": round(self.mean_energy, 6),
        }


def detect_stable_regions(
    beat_times: np.ndarray,
    *,
    onset_unit: np.ndarray,
    sample_rate: int,
    hop_length: int,
    energy_curve: np.ndarray,
    energy_curve_hz: float,
    window_beats: int,
    step_beats: int,
    ibi_cv_max: float,
    ibi_tolerance: float,
    in_tolerance_fraction_min: float,
    onset_strength_floor: float,
    max_regions_per_track: int,
    weight_tempo_consistency: float,
    weight_onset_strength: float,
    weight_in_tolerance: float,
) -> list[StableRegion]:
    """Return up to ``max_regions_per_track`` non-overlapping mixable windows.

    Raises ``RegionDetectionError`` when no window clears the gates: a tempo without a
    mixable passage is not a completed analysis.
    """
    times = np.asarray(beat_times, dtype=np.float64)
    if times.size < window_beats:
        raise RegionDetectionError(
            RegionFailure.NO_STABLE_REGION,
            f"{times.size} beat(s) cannot host a {window_beats}-beat mix window",
        )

    candidates: list[StableRegion] = []
    last_start = times.size - window_beats
    for start in range(0, last_start + 1, step_beats):
        end = start + window_beats
        window = times[start:end]
        intervals = np.diff(window)
        if intervals.size == 0 or not bool(np.all(intervals > 0)):
            continue
        ibi_cv = _ibi_cv(intervals)
        if ibi_cv > ibi_cv_max:
            continue
        median_ibi = float(np.median(intervals))
        in_tolerance = float(np.mean(np.abs(intervals - median_ibi) <= ibi_tolerance * median_ibi))
        if in_tolerance < in_tolerance_fraction_min:
            continue
        mean_onset = _mean_at_times(
            window, onset_unit, sample_rate=sample_rate, hop_length=hop_length
        )
        if mean_onset < onset_strength_floor:
            continue
        tempo_consistency = max(0.0, 1.0 - ibi_cv / ibi_cv_max)
        score = (
            weight_tempo_consistency * tempo_consistency
            + weight_onset_strength * mean_onset
            + weight_in_tolerance * in_tolerance
        )
        candidates.append(
            StableRegion(
                start_beat=start,
                end_beat=end,
                start_time=float(window[0]),
                end_time=float(window[-1]),
                score=float(score),
                ibi_cv=ibi_cv,
                in_tolerance_fraction=in_tolerance,
                mean_onset=float(mean_onset),
                mean_energy=_mean_energy(window, energy_curve, energy_curve_hz),
            )
        )

    kept = _non_maximum_suppression(candidates, max_regions=max_regions_per_track)
    if not kept:
        raise RegionDetectionError(
            RegionFailure.NO_STABLE_REGION,
            f"no {window_beats}-beat window cleared the stability gates "
            f"(ibi_cv_max={ibi_cv_max:g}, onset_floor={onset_strength_floor:g})",
        )
    return kept


def _non_maximum_suppression(
    candidates: list[StableRegion], *, max_regions: int
) -> list[StableRegion]:
    ordered = sorted(candidates, key=lambda region: (-region.score, region.start_beat))
    kept: list[StableRegion] = []
    for region in ordered:
        if any(region.overlaps(existing) for existing in kept):
            continue
        kept.append(region)
        if len(kept) >= max_regions:
            break
    kept.sort(key=lambda region: region.start_beat)
    return kept


def _ibi_cv(intervals: np.ndarray) -> float:
    mean = float(np.mean(intervals))
    if mean <= INTERVAL_EPSILON:
        return float("inf")
    if intervals.size < 2:
        return 0.0
    return float(np.std(intervals, ddof=1) / mean)


def _mean_at_times(
    times: np.ndarray, values: np.ndarray, *, sample_rate: int, hop_length: int
) -> float:
    if times.size == 0 or values.size == 0:
        return 0.0
    frames = np.clip(np.rint(times * sample_rate / hop_length).astype(int), 0, values.size - 1)
    return float(np.mean(values[frames]))


def _mean_energy(times: np.ndarray, curve: np.ndarray, curve_hz: float) -> float:
    if times.size == 0 or curve.size == 0 or curve_hz <= 0:
        return 0.0
    grid = np.arange(curve.size, dtype=np.float64) / curve_hz
    return float(np.mean(np.interp(times, grid, curve)))
