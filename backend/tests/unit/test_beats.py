"""Beat tracking on in-memory synthetic audio. No files, no database."""

from __future__ import annotations

import numpy as np
import pytest
from fixtures.audio import click_track

from autodj.audio.beats import (
    AnalysisFailure,
    BeatTrackingError,
    _GridCandidate,
    _preferred_octave,
    analyze_beats,
    refine_beat_times,
)
from autodj.config.settings import Settings


def _kwargs(settings: Settings, **overrides: object) -> dict[str, object]:
    analysis = settings.analysis
    values: dict[str, object] = {
        "sample_rate": analysis.sample_rate,
        "hop_length": analysis.hop_length,
        "refine_hop_length": analysis.refine_hop_length,
        "start_bpm": analysis.start_bpm,
        "min_bpm": analysis.min_bpm,
        "max_bpm": analysis.max_bpm,
        "min_beats": analysis.min_beats,
        "max_ibi_cv": analysis.max_ibi_cv,
        "min_onset_contrast": analysis.min_onset_contrast,
        "min_confidence": analysis.min_confidence,
        "refine_search_radius_frames": analysis.refine_search_radius_frames,
    }
    values.update(overrides)
    return values


def _mean_abs_error_ms(detected: np.ndarray, truth: np.ndarray) -> float:
    errors = [abs(time - truth[int(np.argmin(np.abs(truth - time)))]) for time in detected]
    return 1000.0 * float(np.mean(errors))


@pytest.mark.parametrize("bpm", [100.0, 120.0, 124.0, 128.0, 140.0])
def test_click_track_recovers_known_bpm(settings: Settings, bpm: float) -> None:
    samples, _truth = click_track(bpm, seconds=16.0, sample_rate=settings.analysis.sample_rate)

    result = analyze_beats(samples, **_kwargs(settings))  # type: ignore[arg-type]

    assert result.native_bpm == pytest.approx(bpm, abs=1.0)
    assert result.beat_times.size >= settings.analysis.min_beats
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence > 0.5
    assert result.onset_contrast > 0.8
    assert np.all(np.diff(result.beat_times) > 0)


def _octave(bpm: float, *, mean_onbeat: float, contrast: float) -> _GridCandidate:
    interval = 60.0 / bpm
    return _GridCandidate(
        times=np.array([0.0, interval, 2 * interval], dtype=np.float64),
        bpm=bpm,
        octave_factor=1.0,
        onset_contrast=contrast,
        mean_onbeat=mean_onbeat,
        ibi_cv=0.01,
    )


def test_start_bpm_breaks_only_exact_octave_score_ties() -> None:
    """87 vs 174: equal evidence prefers 87 (closer to 124); a better lock at 174 wins."""
    house_87 = _octave(87.0, mean_onbeat=1.0, contrast=1.0)
    house_174 = _octave(174.0, mean_onbeat=1.0, contrast=1.0)
    assert house_87.score == house_174.score

    tied = _preferred_octave((house_87, house_174), start_bpm=124.0)
    assert tied.bpm == pytest.approx(87.0)

    stronger_174 = _octave(174.0, mean_onbeat=1.01, contrast=1.0)
    assert stronger_174.score > house_87.score
    assert _preferred_octave((house_87, stronger_174), start_bpm=124.0).bpm == pytest.approx(174.0)


def test_a_100_bpm_grid_is_not_pulled_toward_the_124_prior(settings: Settings) -> None:
    samples, _truth = click_track(100.0, seconds=16.0, sample_rate=settings.analysis.sample_rate)

    result = analyze_beats(samples, **_kwargs(settings))  # type: ignore[arg-type]

    assert result.native_bpm == pytest.approx(100.0, abs=1.0)
    assert result.tempo_octave_factor == pytest.approx(1.0)


def test_a_124_click_track_is_not_reported_as_half_or_double_time(settings: Settings) -> None:
    samples, _truth = click_track(124.0, seconds=16.0, sample_rate=settings.analysis.sample_rate)

    result = analyze_beats(samples, **_kwargs(settings))  # type: ignore[arg-type]

    assert 120.0 < result.native_bpm < 128.0
    assert result.tempo_octave_factor == pytest.approx(1.0)


def test_a_true_half_time_pulse_is_rejected_as_out_of_range(settings: Settings) -> None:
    """A 62 BPM pulse scores best at 62, which is below min_bpm. Do not invent 124."""
    samples, _truth = click_track(62.0, seconds=16.0, sample_rate=settings.analysis.sample_rate)

    with pytest.raises(BeatTrackingError) as error:
        analyze_beats(samples, **_kwargs(settings))  # type: ignore[arg-type]

    assert error.value.failure is AnalysisFailure.TEMPO_OUT_OF_RANGE
    assert error.value.as_dict()["detail"]


def test_white_noise_fails_with_a_structured_reason(settings: Settings) -> None:
    generator = np.random.default_rng(0)
    noise = (0.3 * generator.standard_normal(16 * settings.analysis.sample_rate)).astype(np.float32)

    with pytest.raises(BeatTrackingError) as error:
        analyze_beats(noise, **_kwargs(settings))  # type: ignore[arg-type]

    assert error.value.failure in {
        AnalysisFailure.WEAK_ONSET_ALIGNMENT,
        AnalysisFailure.LOW_CONFIDENCE,
        AnalysisFailure.IRREGULAR_BEAT_GRID,
        AnalysisFailure.TEMPO_OUT_OF_RANGE,
        AnalysisFailure.TOO_FEW_BEATS,
    }


def test_too_few_beats_is_rejected(settings: Settings) -> None:
    samples, _truth = click_track(124.0, seconds=16.0, sample_rate=settings.analysis.sample_rate)

    with pytest.raises(BeatTrackingError) as error:
        analyze_beats(samples, **_kwargs(settings, min_beats=10_000))  # type: ignore[arg-type]

    assert error.value.failure is AnalysisFailure.TOO_FEW_BEATS


def test_refinement_moves_a_coarse_guess_onto_the_interpolated_peak(settings: Settings) -> None:
    hop = settings.analysis.refine_hop_length
    sample_rate = settings.analysis.sample_rate
    envelope = np.zeros(64, dtype=np.float64)
    envelope[19] = 0.7
    envelope[20] = 1.0
    envelope[21] = 0.6
    coarse = np.array([22 * hop / sample_rate], dtype=np.float64)

    refined = refine_beat_times(
        coarse,
        envelope,
        sample_rate=sample_rate,
        hop_length=hop,
        search_radius=4,
    )

    denom = 0.7 - 2.0 * 1.0 + 0.6
    expected_frame = 20 + 0.5 * (0.7 - 0.6) / denom
    expected_time = expected_frame * hop / sample_rate
    assert refined.size == 1
    assert refined[0] == pytest.approx(expected_time, abs=1e-9)
    assert abs(refined[0] - expected_time) < abs(coarse[0] - expected_time)


def test_refinement_reduces_click_timing_error(settings: Settings) -> None:
    sample_rate = settings.analysis.sample_rate
    hop = settings.analysis.hop_length
    samples, truth = click_track(124.0, seconds=16.0, sample_rate=sample_rate)
    result = analyze_beats(samples, **_kwargs(settings))  # type: ignore[arg-type]

    # The coarse grid is the refined times snapped back to the analysis hop.
    coarse = np.rint(result.beat_times * sample_rate / hop) * hop / sample_rate
    assert _mean_abs_error_ms(result.beat_times, truth) < _mean_abs_error_ms(coarse, truth)


def test_confidence_is_regularity_times_onset_contrast(settings: Settings) -> None:
    samples, _truth = click_track(124.0, seconds=16.0, sample_rate=settings.analysis.sample_rate)

    result = analyze_beats(samples, **_kwargs(settings))  # type: ignore[arg-type]

    regularity = max(0.0, 1.0 - result.ibi_cv / settings.analysis.max_ibi_cv)
    assert result.confidence == pytest.approx(regularity * max(0.0, result.onset_contrast))
    assert result.confidence == pytest.approx(result.onset_contrast, abs=0.15)
