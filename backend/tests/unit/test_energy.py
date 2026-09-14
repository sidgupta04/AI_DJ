"""Energy curve on in-memory synthetic audio. No files, no database."""

from __future__ import annotations

import numpy as np
import pytest
from fixtures.audio import click_track, pulsed_tone

from autodj.audio.energy import _map_by_percentiles, _map_dbfs_to_unit, analyze_energy
from autodj.config.settings import Settings


def _kwargs(settings: Settings, **overrides: object) -> dict[str, object]:
    energy = settings.energy
    values: dict[str, object] = {
        "sample_rate": settings.analysis.sample_rate,
        "hop_length": settings.analysis.hop_length,
        "alpha": energy.alpha,
        "rms_floor_db": energy.rms_floor_db,
        "rms_ceiling_db": energy.rms_ceiling_db,
        "curve_hz": energy.curve_hz,
        "aggregation": energy.aggregation,
        "onset_low_percentile": energy.normalization_low_percentile,
        "onset_high_percentile": energy.normalization_high_percentile,
    }
    values.update(overrides)
    return values


def test_rms_dbfs_and_onset_are_mapped_to_unit_before_mixing() -> None:
    """Raw dBFS (~-20) plus raw onset (~1) would be dominated by the onset scale."""
    rms = np.array([0.1, 0.1, 0.1], dtype=np.float64)
    mapped_rms = _map_dbfs_to_unit(rms, floor_db=-60.0, ceiling_db=0.0)
    mapped_onset = _map_by_percentiles(
        np.array([0.0, 5.0, 10.0], dtype=np.float64),
        low_percentile=0.0,
        high_percentile=100.0,
    )
    assert np.all((mapped_rms >= 0.0) & (mapped_rms <= 1.0))
    assert mapped_onset[0] == pytest.approx(0.0)
    assert mapped_onset[-1] == pytest.approx(1.0)
    mixed = 0.6 * mapped_rms + 0.4 * mapped_onset
    assert np.all((mixed >= 0.0) & (mixed <= 1.0))
    # Unnormalized mix is ~4, not a comparable energy.
    raw_mix = 0.6 * (20.0 * np.log10(rms)) + 0.4 * np.array([0.0, 5.0, 10.0])
    assert float(np.max(np.abs(raw_mix))) > 1.0


def test_energy_curve_is_unit_interval_at_configured_rate(settings: Settings) -> None:
    seconds = 8.0
    samples, _truth = click_track(124.0, seconds=seconds, sample_rate=settings.analysis.sample_rate)

    result = analyze_energy(samples, **_kwargs(settings))  # type: ignore[arg-type]

    assert result.curve_hz == pytest.approx(settings.energy.curve_hz)
    assert result.curve.size == pytest.approx(seconds * settings.energy.curve_hz, abs=1)
    assert result.curve.size > 0
    assert float(np.min(result.curve)) >= 0.0
    assert float(np.max(result.curve)) <= 1.0
    assert 0.0 <= result.scalar <= 1.0
    assert result.onset_unit.size > 0
    assert float(np.min(result.onset_unit)) >= 0.0
    assert float(np.max(result.onset_unit)) <= 1.0


def test_median_resists_loud_intro_and_outro_better_than_mean_or_p90(settings: Settings) -> None:
    sample_rate = settings.analysis.sample_rate
    body = pulsed_tone(124.0, seconds=24.0, sample_rate=sample_rate, amplitude=0.15)
    spiked = pulsed_tone(
        124.0,
        seconds=24.0,
        sample_rate=sample_rate,
        amplitude=0.15,
        intro_seconds=2.0,
        intro_amplitude=0.99,
        outro_seconds=2.0,
        outro_amplitude=0.99,
    )
    kwargs = _kwargs(settings)
    body_median = analyze_energy(body, **kwargs)  # type: ignore[arg-type]
    spiked_median = analyze_energy(spiked, **kwargs)  # type: ignore[arg-type]
    spiked_mean = analyze_energy(spiked, **{**kwargs, "aggregation": "mean"})  # type: ignore[arg-type]
    spiked_p90 = analyze_energy(spiked, **{**kwargs, "aggregation": "p90"})  # type: ignore[arg-type]

    median_shift = abs(spiked_median.scalar - body_median.scalar)
    mean_shift = abs(spiked_mean.scalar - body_median.scalar)
    p90_shift = abs(spiked_p90.scalar - body_median.scalar)
    assert median_shift < mean_shift
    assert median_shift < p90_shift


def test_louder_pulse_has_higher_energy_scalar_than_a_quiet_one(settings: Settings) -> None:
    sample_rate = settings.analysis.sample_rate
    quiet = pulsed_tone(124.0, seconds=8.0, sample_rate=sample_rate, amplitude=0.05)
    loud = pulsed_tone(124.0, seconds=8.0, sample_rate=sample_rate, amplitude=0.8)

    quiet_energy = analyze_energy(quiet, **_kwargs(settings))  # type: ignore[arg-type]
    loud_energy = analyze_energy(loud, **_kwargs(settings))  # type: ignore[arg-type]

    assert loud_energy.scalar > quiet_energy.scalar
