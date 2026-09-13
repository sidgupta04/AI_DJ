"""Compare analysis at 22.05 kHz vs 44.1 kHz on synthetic click tracks.

Usage:
    uv run python scripts/experiment_analysis_sample_rate.py

Hop length stays at the configured 512 samples so the comparison matches the
question in the technical plan: does doubling the sample rate buy beat accuracy,
or does precision follow the onset-envelope frame rate?

Results belong in docs/experiments.md.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import numpy as np

from autodj.audio.beats import BeatAnalysis, analyze_beats
from autodj.config.settings import AnalysisSettings, load_settings

BPMS = (100.0, 120.0, 124.0, 128.0, 140.0)
SECONDS = 16.0
SAMPLE_RATES = (22050, 44100)


@dataclass(frozen=True, slots=True)
class RateResult:
    sample_rate: int
    bpm: float
    measured_bpm: float
    bpm_error: float
    mean_abs_error_ms: float
    p95_error_ms: float
    elapsed_seconds: float


def click_track(bpm: float, *, seconds: float, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    frame_count = int(seconds * sample_rate)
    signal = np.zeros(frame_count, dtype=np.float32)
    interval = 60.0 / bpm
    beat_times = np.arange(0.0, seconds, interval, dtype=np.float64)
    click = np.linspace(1.0, 0.0, 64, dtype=np.float32)
    for time_s in beat_times:
        start = int(round(time_s * sample_rate))
        if start >= frame_count:
            continue
        end = min(start + 64, frame_count)
        signal[start:end] = click[: end - start]
    return signal, beat_times[beat_times < seconds]


def timing_errors_ms(detected: np.ndarray, truth: np.ndarray) -> np.ndarray:
    errors = np.empty(detected.size, dtype=np.float64)
    for index, time_s in enumerate(detected):
        errors[index] = abs(time_s - truth[int(np.argmin(np.abs(truth - time_s)))])
    return 1000.0 * errors


def _analyze(samples: np.ndarray, sample_rate: int, analysis: AnalysisSettings) -> BeatAnalysis:
    return analyze_beats(
        samples,
        sample_rate=sample_rate,
        hop_length=analysis.hop_length,
        refine_hop_length=analysis.refine_hop_length,
        start_bpm=analysis.start_bpm,
        min_bpm=analysis.min_bpm,
        max_bpm=analysis.max_bpm,
        min_beats=analysis.min_beats,
        max_ibi_cv=analysis.max_ibi_cv,
        min_onset_contrast=analysis.min_onset_contrast,
        min_confidence=analysis.min_confidence,
        refine_search_radius_frames=analysis.refine_search_radius_frames,
    )


def run_comparison() -> list[RateResult]:
    settings = load_settings(env_file=None)
    analysis = settings.analysis

    warmup, _truth = click_track(124.0, seconds=SECONDS, sample_rate=22050)
    _analyze(warmup, 22050, analysis)

    results: list[RateResult] = []
    for sample_rate in SAMPLE_RATES:
        for bpm in BPMS:
            samples, truth = click_track(bpm, seconds=SECONDS, sample_rate=sample_rate)
            started = time.perf_counter()
            analysis_result = _analyze(samples, sample_rate, analysis)
            elapsed = time.perf_counter() - started
            errors = timing_errors_ms(analysis_result.beat_times, truth)
            results.append(
                RateResult(
                    sample_rate=sample_rate,
                    bpm=bpm,
                    measured_bpm=analysis_result.native_bpm,
                    bpm_error=analysis_result.native_bpm - bpm,
                    mean_abs_error_ms=float(np.mean(errors)),
                    p95_error_ms=float(np.percentile(errors, 95)),
                    elapsed_seconds=elapsed,
                )
            )
    return results


def _print(results: list[RateResult]) -> None:
    print(
        f"{'sr':>6} {'true':>6} {'measured':>8} {'bpm_err':>8} "
        f"{'mae_ms':>8} {'p95_ms':>8} {'sec':>7}"
    )
    for row in results:
        print(
            f"{row.sample_rate:6d} {row.bpm:6.0f} {row.measured_bpm:8.2f} "
            f"{row.bpm_error:8.2f} {row.mean_abs_error_ms:8.2f} "
            f"{row.p95_error_ms:8.2f} {row.elapsed_seconds:7.3f}"
        )
    print()
    for sample_rate in SAMPLE_RATES:
        group = [row for row in results if row.sample_rate == sample_rate]
        print(
            f"sr={sample_rate}: mean |bpm_err|={np.mean([abs(r.bpm_error) for r in group]):.3f} "
            f"mean mae_ms={np.mean([r.mean_abs_error_ms for r in group]):.2f} "
            f"mean sec={np.mean([r.elapsed_seconds for r in group]):.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    _print(run_comparison())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
