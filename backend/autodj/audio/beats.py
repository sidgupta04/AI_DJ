"""BPM and beat-grid analysis.

Takes mono PCM and returns a tempo, a refined beat grid, and a heuristic quality score
derived from that grid. No files, no database: the service layer decodes and persists.

BPM is the median inter-beat interval of the chosen grid, not librosa's global tempo
estimate. Octave errors (half-time / double-time) are resolved by scoring 0.5x / 1x / 2x
candidates against the onset envelope and keeping the one whose beats land on onsets
without also landing on the midpoints. ``start_bpm`` is a weak prior: it seeds librosa's
tempo estimator and breaks exact octave-score ties. It does not pull a clearly better
grid toward 124. See ``docs/algorithms.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import librosa
import numpy as np

ONSET_EPSILON = 1e-12


class AnalysisFailure(StrEnum):
    """Structured reasons beat tracking cannot produce a usable grid."""

    EMPTY_ONSET_ENVELOPE = "EMPTY_ONSET_ENVELOPE"
    TOO_FEW_BEATS = "TOO_FEW_BEATS"
    TEMPO_OUT_OF_RANGE = "TEMPO_OUT_OF_RANGE"
    IRREGULAR_BEAT_GRID = "IRREGULAR_BEAT_GRID"
    WEAK_ONSET_ALIGNMENT = "WEAK_ONSET_ALIGNMENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class BeatTrackingError(Exception):
    """Beat tracking failed with a machine-readable reason and a human-readable detail."""

    def __init__(self, failure: AnalysisFailure, detail: str) -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail

    def as_dict(self) -> dict[str, str]:
        return {"reason": str(self.failure), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class BeatAnalysis:
    """Result of beat tracking.

    ``confidence`` is a deterministic quality score in ``[0, 1]``
    (``tempo_regularity * onset_contrast``). It is not a calibrated probability
    that the BPM is correct.
    """

    native_bpm: float
    beat_times: np.ndarray
    confidence: float
    ibi_cv: float
    onset_contrast: float
    tempo_octave_factor: float
    sample_rate: int
    hop_length: int
    refine_hop_length: int


@dataclass(frozen=True, slots=True)
class _GridCandidate:
    times: np.ndarray
    bpm: float
    octave_factor: float
    onset_contrast: float
    mean_onbeat: float
    ibi_cv: float

    @property
    def score(self) -> float:
        """Higher means beats lock to onsets and not to the gaps between them."""
        return self.mean_onbeat * max(0.0, self.onset_contrast)


def analyze_beats(
    samples: np.ndarray,
    *,
    sample_rate: int,
    hop_length: int,
    refine_hop_length: int,
    start_bpm: float,
    min_bpm: float,
    max_bpm: float,
    min_beats: int,
    max_ibi_cv: float,
    min_onset_contrast: float,
    min_confidence: float,
    refine_search_radius_frames: int,
) -> BeatAnalysis:
    """Estimate BPM and a refined beat grid from mono float PCM."""
    if samples.ndim != 1:
        raise ValueError("analyze_beats expects mono samples with shape (n,)")
    if samples.size == 0:
        raise BeatTrackingError(AnalysisFailure.EMPTY_ONSET_ENVELOPE, "no audio samples")

    onset = librosa.onset.onset_strength(y=samples, sr=sample_rate, hop_length=hop_length)
    if onset.size == 0 or not bool(np.isfinite(onset).all()):
        raise BeatTrackingError(
            AnalysisFailure.EMPTY_ONSET_ENVELOPE, "onset envelope is empty or non-finite"
        )

    # start_bpm is librosa's tempo-estimator prior (a log-normal around this value).
    # It biases the first grid; it does not force the final BPM. Octave selection
    # below uses onset evidence and consults start_bpm only to break exact ties.
    _, raw_beats = librosa.beat.beat_track(
        onset_envelope=onset,
        sr=sample_rate,
        hop_length=hop_length,
        start_bpm=start_bpm,
        units="time",
    )
    raw_beats = np.asarray(raw_beats, dtype=np.float64)
    if raw_beats.size < 2:
        raise BeatTrackingError(
            AnalysisFailure.TOO_FEW_BEATS,
            f"librosa returned {raw_beats.size} beat(s); need at least 2 to form a tempo",
        )

    candidate = _choose_octave(
        raw_beats,
        onset,
        sample_rate=sample_rate,
        hop_length=hop_length,
        start_bpm=start_bpm,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
    )

    fine_onset = librosa.onset.onset_strength(
        y=samples, sr=sample_rate, hop_length=refine_hop_length
    )
    refined = refine_beat_times(
        candidate.times,
        fine_onset,
        sample_rate=sample_rate,
        hop_length=refine_hop_length,
        search_radius=refine_search_radius_frames,
    )
    if refined.size < min_beats:
        raise BeatTrackingError(
            AnalysisFailure.TOO_FEW_BEATS,
            f"{refined.size} refined beat(s) is below the {min_beats} minimum",
        )

    native_bpm = _bpm_from_times(refined)
    ibi_cv = _ibi_cv(refined)
    onset_contrast, _mean_onbeat = _onset_alignment(
        refined, fine_onset, sample_rate=sample_rate, hop_length=refine_hop_length
    )

    if not (min_bpm <= native_bpm <= max_bpm):
        raise BeatTrackingError(
            AnalysisFailure.TEMPO_OUT_OF_RANGE,
            f"refined tempo {native_bpm:.2f} BPM is outside [{min_bpm:g}, {max_bpm:g}]",
        )
    if ibi_cv > max_ibi_cv:
        raise BeatTrackingError(
            AnalysisFailure.IRREGULAR_BEAT_GRID,
            f"inter-beat interval CV {ibi_cv:.3f} exceeds {max_ibi_cv:g}",
        )
    if onset_contrast < min_onset_contrast:
        raise BeatTrackingError(
            AnalysisFailure.WEAK_ONSET_ALIGNMENT,
            f"onset contrast {onset_contrast:.3f} is below {min_onset_contrast:g}",
        )

    regularity = max(0.0, 1.0 - ibi_cv / max_ibi_cv)
    # Heuristic quality, not P(BPM is correct). See BeatAnalysis and docs/algorithms.md.
    confidence = regularity * max(0.0, onset_contrast)
    if confidence < min_confidence:
        raise BeatTrackingError(
            AnalysisFailure.LOW_CONFIDENCE,
            f"quality score {confidence:.3f} is below {min_confidence:g} "
            f"(regularity={regularity:.3f}, contrast={onset_contrast:.3f})",
        )
    return BeatAnalysis(
        native_bpm=native_bpm,
        beat_times=refined,
        confidence=float(confidence),
        ibi_cv=ibi_cv,
        onset_contrast=onset_contrast,
        tempo_octave_factor=candidate.octave_factor,
        sample_rate=sample_rate,
        hop_length=hop_length,
        refine_hop_length=refine_hop_length,
    )


def refine_beat_times(
    beat_times: np.ndarray,
    fine_onset: np.ndarray,
    *,
    sample_rate: int,
    hop_length: int,
    search_radius: int,
) -> np.ndarray:
    """Nudge each beat to the interpolated peak of a finer onset envelope.

    Coarse beat tracking quantizes times to ``hop_length`` frames. This searches a small
    window on a shorter-hop envelope, then fits a parabola through the peak and its
    neighbours so the time can sit between frames.
    """
    if fine_onset.size < 3 or beat_times.size == 0:
        return np.asarray(beat_times, dtype=np.float64)

    refined = np.empty(beat_times.size, dtype=np.float64)
    last_frame = fine_onset.size - 2
    for index, time in enumerate(beat_times):
        center = int(round(time * sample_rate / hop_length))
        low = max(1, center - search_radius)
        high = min(last_frame + 1, center + search_radius + 1)
        if high <= low:
            refined[index] = time
            continue
        peak = low + int(np.argmax(fine_onset[low:high]))
        peak = min(max(peak, 1), last_frame)
        delta = _parabolic_offset(
            float(fine_onset[peak - 1]),
            float(fine_onset[peak]),
            float(fine_onset[peak + 1]),
        )
        refined[index] = (peak + delta) * hop_length / sample_rate

    return _dedupe_sorted(refined)


def _choose_octave(
    beat_times: np.ndarray,
    onset: np.ndarray,
    *,
    sample_rate: int,
    hop_length: int,
    start_bpm: float,
    min_bpm: float,
    max_bpm: float,
) -> _GridCandidate:
    """Pick 0.5x, 1x or 2x of the raw grid by onset alignment, then apply the BPM band."""
    measured_bpm = _bpm_from_times(beat_times)
    candidates = [
        _evaluate_grid(
            times,
            onset,
            sample_rate=sample_rate,
            hop_length=hop_length,
            octave_factor=factor,
        )
        for factor, times in _octave_grids(beat_times)
    ]
    best = _preferred_octave(candidates, start_bpm=start_bpm)
    if not (min_bpm <= best.bpm <= max_bpm):
        in_range = [item.bpm for item in candidates if min_bpm <= item.bpm <= max_bpm]
        extra = f"; in-range alternatives: {in_range}" if in_range else ""
        raise BeatTrackingError(
            AnalysisFailure.TEMPO_OUT_OF_RANGE,
            f"best-scoring tempo is {best.bpm:.2f} BPM "
            f"(raw grid {measured_bpm:.2f} x {best.octave_factor:g}), "
            f"outside [{min_bpm:g}, {max_bpm:g}]{extra}",
        )
    return best


def _preferred_octave(candidates: Sequence[_GridCandidate], *, start_bpm: float) -> _GridCandidate:
    """Highest onset-alignment score wins. ``start_bpm`` breaks only exact ties.

    Musical evidence dominates. Example: 87 vs 174 BPM with equal scores and
    ``start_bpm=124`` prefers 87 (closer to 124). If 174's score is even slightly
    higher, 174 wins — the prior never outweighs a better lock.
    """
    return max(candidates, key=lambda item: (item.score, -abs(item.bpm - start_bpm)))


def _octave_grids(beat_times: np.ndarray) -> list[tuple[float, np.ndarray]]:
    grids: list[tuple[float, np.ndarray]] = [(1.0, beat_times)]
    even = beat_times[0::2]
    odd = beat_times[1::2]
    if even.size >= 2:
        grids.append((0.5, even))
    if odd.size >= 2:
        grids.append((0.5, odd))
    if beat_times.size >= 2:
        midpoints = (beat_times[:-1] + beat_times[1:]) / 2.0
        grids.append((2.0, np.sort(np.concatenate([beat_times, midpoints]))))
    return grids


def _evaluate_grid(
    times: np.ndarray,
    onset: np.ndarray,
    *,
    sample_rate: int,
    hop_length: int,
    octave_factor: float,
) -> _GridCandidate:
    contrast, mean_onbeat = _onset_alignment(
        times, onset, sample_rate=sample_rate, hop_length=hop_length
    )
    return _GridCandidate(
        times=times,
        bpm=_bpm_from_times(times),
        octave_factor=octave_factor,
        onset_contrast=contrast,
        mean_onbeat=mean_onbeat,
        ibi_cv=_ibi_cv(times),
    )


def _onset_alignment(
    times: np.ndarray,
    onset: np.ndarray,
    *,
    sample_rate: int,
    hop_length: int,
) -> tuple[float, float]:
    """Return (contrast, mean onset at beats).

    Contrast is ``(onbeat - offbeat) / (onbeat + offbeat)``: 1 when the envelope is
    concentrated on the grid, 0 when beats and midpoints are interchangeable, negative
    when the grid sits in the gaps.
    """
    if times.size < 2 or onset.size == 0:
        return 0.0, 0.0
    on_frames = _times_to_frames(
        times, sample_rate=sample_rate, hop_length=hop_length, limit=onset.size
    )
    midpoints = (times[:-1] + times[1:]) / 2.0
    off_frames = _times_to_frames(
        midpoints, sample_rate=sample_rate, hop_length=hop_length, limit=onset.size
    )
    onbeat = float(np.mean(onset[on_frames]))
    offbeat = float(np.mean(onset[off_frames]))
    contrast = (onbeat - offbeat) / (onbeat + offbeat + ONSET_EPSILON)
    return contrast, onbeat


def _times_to_frames(
    times: np.ndarray, *, sample_rate: int, hop_length: int, limit: int
) -> np.ndarray:
    frames = np.rint(times * sample_rate / hop_length).astype(int)
    return np.clip(frames, 0, limit - 1)


def _bpm_from_times(times: np.ndarray) -> float:
    intervals = _positive_intervals(times)
    return float(60.0 / np.median(intervals))


def _ibi_cv(times: np.ndarray) -> float:
    intervals = _positive_intervals(times)
    if intervals.size < 2:
        return float("inf")
    mean = float(np.mean(intervals))
    if mean <= 0:
        return float("inf")
    return float(np.std(intervals, ddof=1) / mean)


def _positive_intervals(times: np.ndarray) -> np.ndarray:
    if times.size < 2:
        return np.empty(0, dtype=np.float64)
    intervals = np.diff(np.asarray(times, dtype=np.float64))
    return intervals[intervals > 0]


def _parabolic_offset(y_left: float, y_peak: float, y_right: float) -> float:
    """Sub-frame offset of a peak, in frames, from a 3-point parabola.

    ``0.5 * (y[i-1] - y[i+1]) / (y[i-1] - 2 y[i] + y[i+1])``. A flat or convex
    neighbourhood returns 0 so the integer peak is left alone.
    """
    denom = y_left - 2.0 * y_peak + y_right
    if denom >= 0 or not np.isfinite(denom):
        return 0.0
    offset = 0.5 * (y_left - y_right) / denom
    if not np.isfinite(offset):
        return 0.0
    return float(np.clip(offset, -0.5, 0.5))


def _dedupe_sorted(times: np.ndarray, *, min_gap_seconds: float = 1e-4) -> np.ndarray:
    ordered = np.sort(times)
    keep = [ordered[0]]
    for time in ordered[1:]:
        if time - keep[-1] >= min_gap_seconds:
            keep.append(time)
    return np.asarray(keep, dtype=np.float64)
