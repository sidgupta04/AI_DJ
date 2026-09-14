"""Stable-region detection on synthetic beat grids. No files, no database."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from fixtures.audio import click_track

from autodj.audio.energy import analyze_energy
from autodj.audio.regions import (
    RegionDetectionError,
    RegionFailure,
    detect_stable_regions,
)
from autodj.config.settings import Settings


def _beats(count: int, bpm: float = 124.0) -> np.ndarray:
    interval = 60.0 / bpm
    return np.arange(count, dtype=np.float64) * interval


def _onset_at_beats(
    times: np.ndarray, *, sample_rate: int, hop_length: int, value: float = 1.0
) -> np.ndarray:
    last_frame = int(np.ceil(times[-1] * sample_rate / hop_length)) + 1
    onset = np.zeros(last_frame, dtype=np.float64)
    frames = np.clip(np.rint(times * sample_rate / hop_length).astype(int), 0, last_frame - 1)
    onset[frames] = value
    return onset


def _energy_curve(times: np.ndarray, *, curve_hz: float, value: float = 0.5) -> np.ndarray:
    duration = float(times[-1]) + 60.0 / 124.0
    return np.full(max(1, int(np.ceil(duration * curve_hz))), value, dtype=np.float64)


def _region_kwargs(settings: Settings, **overrides: Any) -> dict[str, Any]:
    regions = settings.stable_regions
    energy = settings.energy
    values: dict[str, object] = {
        "sample_rate": settings.analysis.sample_rate,
        "hop_length": settings.analysis.hop_length,
        "energy_curve_hz": energy.curve_hz,
        "window_beats": regions.window_beats,
        "step_beats": regions.step_beats,
        "ibi_cv_max": regions.ibi_cv_max,
        "ibi_tolerance": regions.ibi_tolerance,
        "in_tolerance_fraction_min": regions.in_tolerance_fraction_min,
        "onset_strength_floor": regions.onset_strength_floor,
        "max_regions_per_track": regions.max_regions_per_track,
        "weight_tempo_consistency": regions.weight_tempo_consistency,
        "weight_onset_strength": regions.weight_onset_strength,
        "weight_in_tolerance": regions.weight_in_tolerance,
    }
    values.update(overrides)
    return values


def test_regular_grid_with_strong_onsets_yields_mixable_regions(settings: Settings) -> None:
    times = _beats(48)
    onset = _onset_at_beats(
        times, sample_rate=settings.analysis.sample_rate, hop_length=settings.analysis.hop_length
    )
    curve = _energy_curve(times, curve_hz=settings.energy.curve_hz)

    regions = detect_stable_regions(
        times, onset_unit=onset, energy_curve=curve, **_region_kwargs(settings)
    )

    assert 1 <= len(regions) <= settings.stable_regions.max_regions_per_track
    assert regions == sorted(regions, key=lambda region: region.start_beat)
    for region in regions:
        assert region.end_beat - region.start_beat == settings.stable_regions.window_beats
        assert region.score > 0.0
        assert region.ibi_cv <= settings.stable_regions.ibi_cv_max
        assert region.mean_onset >= settings.stable_regions.onset_strength_floor
    for left, right in zip(regions, regions[1:], strict=False):
        assert not left.overlaps(right)


def test_too_few_beats_for_a_window_is_not_a_mixable_track(settings: Settings) -> None:
    times = _beats(20)
    onset = _onset_at_beats(
        times, sample_rate=settings.analysis.sample_rate, hop_length=settings.analysis.hop_length
    )
    curve = _energy_curve(times, curve_hz=settings.energy.curve_hz)

    with pytest.raises(RegionDetectionError) as error:
        detect_stable_regions(
            times, onset_unit=onset, energy_curve=curve, **_region_kwargs(settings)
        )

    assert error.value.failure is RegionFailure.NO_STABLE_REGION
    assert error.value.as_dict()["reason"] == "NO_STABLE_REGION"


def test_jittered_grid_fails_the_ibi_cv_gate(settings: Settings) -> None:
    times = _beats(48)
    rng = np.random.default_rng(0)
    times = times + rng.uniform(-0.08, 0.08, size=times.size)
    times = np.sort(times)
    onset = np.ones(2000, dtype=np.float64)
    curve = _energy_curve(times, curve_hz=settings.energy.curve_hz)

    with pytest.raises(RegionDetectionError) as error:
        detect_stable_regions(
            times, onset_unit=onset, energy_curve=curve, **_region_kwargs(settings)
        )

    assert error.value.failure is RegionFailure.NO_STABLE_REGION


def test_steady_but_onset_sparse_grid_fails_the_onset_floor(settings: Settings) -> None:
    times = _beats(48)
    onset = _onset_at_beats(
        times,
        sample_rate=settings.analysis.sample_rate,
        hop_length=settings.analysis.hop_length,
        value=0.05,
    )
    curve = _energy_curve(times, curve_hz=settings.energy.curve_hz)

    with pytest.raises(RegionDetectionError) as error:
        detect_stable_regions(
            times, onset_unit=onset, energy_curve=curve, **_region_kwargs(settings)
        )

    assert error.value.failure is RegionFailure.NO_STABLE_REGION


def test_nms_keeps_at_most_max_regions_and_drops_overlaps(settings: Settings) -> None:
    times = _beats(64)
    onset = np.ones(4000, dtype=np.float64)
    curve = _energy_curve(times, curve_hz=settings.energy.curve_hz)

    regions = detect_stable_regions(
        times,
        onset_unit=onset,
        energy_curve=curve,
        **_region_kwargs(settings, max_regions_per_track=2, window_beats=16, step_beats=4),
    )

    assert len(regions) == 2
    assert not regions[0].overlaps(regions[1])


def test_click_track_regions_survive_the_real_onset_envelope(settings: Settings) -> None:
    samples, _truth = click_track(124.0, seconds=24.0, sample_rate=settings.analysis.sample_rate)
    energy = analyze_energy(
        samples,
        sample_rate=settings.analysis.sample_rate,
        hop_length=settings.analysis.hop_length,
        alpha=settings.energy.alpha,
        rms_floor_db=settings.energy.rms_floor_db,
        rms_ceiling_db=settings.energy.rms_ceiling_db,
        curve_hz=settings.energy.curve_hz,
        aggregation=settings.energy.aggregation,
        onset_low_percentile=settings.energy.normalization_low_percentile,
        onset_high_percentile=settings.energy.normalization_high_percentile,
    )
    times = _beats(48, bpm=124.0)

    regions = detect_stable_regions(
        times,
        onset_unit=energy.onset_unit,
        energy_curve=energy.curve,
        **_region_kwargs(settings),
    )

    assert len(regions) >= 1
