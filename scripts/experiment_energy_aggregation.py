"""Compare mean, median, and p90 energy aggregation on a spiked synthetic loop.

Usage:
    uv run python scripts/experiment_energy_aggregation.py

Question: does a loud intro and outro pull the track scalar away from the body?
Results belong in docs/experiments.md.
"""

from __future__ import annotations

import argparse

import numpy as np

from autodj.audio.energy import analyze_energy
from autodj.config.settings import EnergySettings, load_settings

SECONDS = 24.0
BPM = 124.0


def pulsed_tone(
    *,
    sample_rate: int,
    amplitude: float,
    intro_seconds: float = 0.0,
    intro_amplitude: float = 1.0,
    outro_seconds: float = 0.0,
    outro_amplitude: float = 1.0,
) -> np.ndarray:
    frame_count = int(SECONDS * sample_rate)
    times = np.arange(frame_count, dtype=np.float64) / sample_rate
    tone = amplitude * np.sin(2 * np.pi * 220.0 * times)
    interval = 60.0 / BPM
    gate = np.zeros(frame_count, dtype=np.float64)
    onset = 0.0
    while onset < SECONDS:
        start = int(round(onset * sample_rate))
        end = min(int(round((onset + 0.5 * interval) * sample_rate)), frame_count)
        if start < frame_count:
            gate[start:end] = 1.0
        onset += interval
    signal = (tone * gate).astype(np.float32)
    if intro_seconds > 0:
        intro_end = min(int(round(intro_seconds * sample_rate)), frame_count)
        intro = intro_amplitude * np.sin(2 * np.pi * 220.0 * times[:intro_end])
        signal[:intro_end] = intro.astype(np.float32)
    if outro_seconds > 0:
        outro_start = max(0, frame_count - int(round(outro_seconds * sample_rate)))
        outro = outro_amplitude * np.sin(2 * np.pi * 220.0 * times[outro_start:])
        signal[outro_start:] = outro.astype(np.float32)
    return signal


def energy_scalar(
    samples: np.ndarray,
    sample_rate: int,
    hop_length: int,
    energy: EnergySettings,
    method: str,
) -> float:
    result = analyze_energy(
        samples,
        sample_rate=sample_rate,
        hop_length=hop_length,
        alpha=energy.alpha,
        rms_floor_db=energy.rms_floor_db,
        rms_ceiling_db=energy.rms_ceiling_db,
        curve_hz=energy.curve_hz,
        aggregation=method,
        onset_low_percentile=energy.normalization_low_percentile,
        onset_high_percentile=energy.normalization_high_percentile,
    )
    return result.scalar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    settings = load_settings(env_file=None)
    sample_rate = settings.analysis.sample_rate
    hop = settings.analysis.hop_length
    energy = settings.energy

    body = pulsed_tone(sample_rate=sample_rate, amplitude=0.15)
    spiked = pulsed_tone(
        sample_rate=sample_rate,
        amplitude=0.15,
        intro_seconds=2.0,
        intro_amplitude=0.99,
        outro_seconds=2.0,
        outro_amplitude=0.99,
    )

    print(f"{'method':<8} {'body':>8} {'spiked':>8} {'delta':>8}")
    for method in ("median", "mean", "p90"):
        body_scalar = energy_scalar(body, sample_rate, hop, energy, method)
        spiked_scalar = energy_scalar(spiked, sample_rate, hop, energy, method)
        print(
            f"{method:<8} {body_scalar:8.4f} {spiked_scalar:8.4f} "
            f"{spiked_scalar - body_scalar:8.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
