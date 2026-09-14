"""Calibrate stable-region IBI CV and onset-floor gates on synthetic grids.

Usage:
    uv run python scripts/experiment_region_thresholds.py

Measures IBI CV for a perfect 124 BPM grid versus jittered grids, and whether
the default gates keep a strong-onset window while rejecting a sparse one.
Results belong in docs/experiments.md.
"""

from __future__ import annotations

import argparse

import numpy as np

from autodj.audio.regions import RegionDetectionError, detect_stable_regions
from autodj.config.settings import load_settings


def _beats(count: int, bpm: float = 124.0) -> np.ndarray:
    return np.arange(count, dtype=np.float64) * (60.0 / bpm)


def _ibi_cv(times: np.ndarray) -> float:
    intervals = np.diff(times)
    mean = float(np.mean(intervals))
    return float(np.std(intervals, ddof=1) / mean)


def _detect(times: np.ndarray, onset_value: float) -> str:
    settings = load_settings(env_file=None)
    sample_rate = settings.analysis.sample_rate
    hop = settings.analysis.hop_length
    last_frame = int(np.ceil(times[-1] * sample_rate / hop)) + 1
    onset = np.zeros(last_frame, dtype=np.float64)
    frames = np.clip(np.rint(times * sample_rate / hop).astype(int), 0, last_frame - 1)
    onset[frames] = onset_value
    curve = np.full(max(1, int(np.ceil((times[-1] + 0.5) * settings.energy.curve_hz))), 0.5)
    regions = settings.stable_regions
    try:
        found = detect_stable_regions(
            times,
            onset_unit=onset,
            sample_rate=sample_rate,
            hop_length=hop,
            energy_curve=curve,
            energy_curve_hz=settings.energy.curve_hz,
            window_beats=regions.window_beats,
            step_beats=regions.step_beats,
            ibi_cv_max=regions.ibi_cv_max,
            ibi_tolerance=regions.ibi_tolerance,
            in_tolerance_fraction_min=regions.in_tolerance_fraction_min,
            onset_strength_floor=regions.onset_strength_floor,
            max_regions_per_track=regions.max_regions_per_track,
            weight_tempo_consistency=regions.weight_tempo_consistency,
            weight_onset_strength=regions.weight_onset_strength,
            weight_in_tolerance=regions.weight_in_tolerance,
        )
    except RegionDetectionError as error:
        return f"FAIL {error.failure}"
    return f"PASS n={len(found)} score={found[0].score:.3f} cv={found[0].ibi_cv:.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    settings = load_settings(env_file=None)
    print(f"ibi_cv_max={settings.stable_regions.ibi_cv_max}")
    print(f"onset_strength_floor={settings.stable_regions.onset_strength_floor}")
    print()
    print(f"{'grid':<22} {'ibi_cv':>8}")
    perfect = _beats(48)
    print(f"{'perfect 124':<22} {_ibi_cv(perfect):8.4f}")
    rng = np.random.default_rng(0)
    for label, scale in (("2% jitter", 0.02), ("5% jitter", 0.05), ("8% jitter", 0.08)):
        interval = 60.0 / 124.0
        jittered = np.sort(perfect + rng.uniform(-scale, scale, size=perfect.size) * interval)
        print(f"{label:<22} {_ibi_cv(jittered):8.4f}")
    print()
    print("detect perfect + strong onset:", _detect(perfect, 1.0))
    print("detect perfect + sparse onset:", _detect(perfect, 0.05))
    jitter_2 = np.sort(perfect + rng.uniform(-0.02, 0.02, size=perfect.size) * (60.0 / 124.0))
    print("detect 2% jitter + strong onset:", _detect(jitter_2, 1.0))
    jitter_5 = np.sort(perfect + rng.uniform(-0.05, 0.05, size=perfect.size) * (60.0 / 124.0))
    print("detect 5% jitter + strong onset:", _detect(jitter_5, 1.0))
    jitter_8 = np.sort(perfect + rng.uniform(-0.08, 0.08, size=perfect.size) * (60.0 / 124.0))
    print("detect 8% jitter + strong onset:", _detect(jitter_8, 1.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
