from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from autodj.config.settings import RankingSettings, Settings, TransitionSettings, load_settings


def test_documented_defaults_are_loaded(settings: Settings) -> None:
    assert settings.analysis.sample_rate == 22050
    assert settings.analysis.hop_length == 512
    assert settings.render.sample_rate == 44100
    assert settings.render.channels == 2
    assert settings.transition.crossfade_beats == 32
    assert settings.stable_regions.window_beats == 32
    assert settings.retrieval.max_bpm_deviation_pct == pytest.approx(5.0)
    assert settings.tempo.min_stretch_ratio == pytest.approx(0.95)
    assert settings.tempo.max_stretch_ratio == pytest.approx(1.05)


def test_cost_weights_sum_to_one(settings: Settings) -> None:
    ranking = settings.ranking
    assert ranking.weight_tempo + ranking.weight_energy + ranking.weight_quality == pytest.approx(
        1.0
    )
    transition = settings.transition
    assert (
        transition.weight_stability
        + transition.weight_energy
        + transition.weight_stretch
        + transition.weight_position
    ) == pytest.approx(1.0)


def test_ranking_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="must sum to 1.0"):
        RankingSettings(weight_tempo=0.6, weight_energy=0.6, weight_quality=0.05)


def test_search_fractions_must_be_ordered(settings: Settings) -> None:
    inverted = {**settings.transition.model_dump(), "incoming_search_fraction": (0.35, 0.0)}

    with pytest.raises(ValidationError, match="ordered"):
        TransitionSettings(**inverted)


def test_environment_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTODJ_ANALYSIS__SAMPLE_RATE", "44100")
    monkeypatch.setenv("AUTODJ_LOG_FORMAT", "json")

    overridden = load_settings(env_file=None)

    assert overridden.analysis.sample_rate == 44100
    assert overridden.log_format == "json"
    assert overridden.analysis.hop_length == 512


def test_derived_frame_rates(settings: Settings) -> None:
    assert settings.analysis.frame_hz == pytest.approx(22050 / 512)
    assert settings.analysis.refine_frame_hz > settings.analysis.frame_hz
    assert settings.tempo.max_stretch_deviation == pytest.approx(0.05)


def test_snapshot_is_json_serializable(settings: Settings) -> None:
    snapshot = settings.snapshot()

    assert json.loads(json.dumps(snapshot))["analysis"]["version"] == settings.analysis.version


def test_unknown_configuration_keys_are_rejected(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        RankingSettings(**{**settings.ranking.model_dump(), "weight_vibe": 0.1})
