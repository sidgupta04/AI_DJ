"""Guard the M2 sample-rate experiment: both rates must recover click-track BPM."""

from __future__ import annotations

import pytest
from fixtures.audio import click_track

from autodj.audio.beats import analyze_beats
from autodj.config.settings import Settings


@pytest.mark.parametrize("sample_rate", [22050, 44100])
@pytest.mark.parametrize("bpm", [120.0, 124.0, 128.0])
def test_configured_hop_recovers_bpm_at_both_sample_rates(
    settings: Settings, sample_rate: int, bpm: float
) -> None:
    analysis = settings.analysis
    samples, _truth = click_track(bpm, seconds=16.0, sample_rate=sample_rate)

    result = analyze_beats(
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

    assert result.native_bpm == pytest.approx(bpm, abs=1.0)
