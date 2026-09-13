"""Central configuration.

Every experimental parameter lives in ``default.yaml`` with a documented reason. Code reads
settings; it never hard-codes thresholds or weights.

Precedence: constructor arguments > environment variables > ``.env`` > ``default.yaml``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default.yaml")

WEIGHT_SUM_TOLERANCE = 1e-6

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
SearchRange = tuple[Fraction, Fraction]


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_weight_sum(weights: dict[str, float]) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        names = ", ".join(sorted(weights))
        raise ValueError(f"weights ({names}) must sum to 1.0, got {total}")


class IngestionSettings(ConfigSection):
    extensions: tuple[str, ...]
    validation_seconds: float = Field(gt=0.0)
    silence_scan_seconds: float = Field(gt=0.0)
    min_duration_seconds: float = Field(gt=0.0)
    subprocess_timeout_seconds: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _extensions_must_be_normalized(self) -> Self:
        for extension in self.extensions:
            if not extension.startswith(".") or extension != extension.lower():
                raise ValueError(f"extension {extension!r} must be lowercase and start with '.'")
        return self

    @model_validator(mode="after")
    def _silence_scan_must_widen_the_window(self) -> Self:
        if self.silence_scan_seconds < self.validation_seconds:
            raise ValueError(
                "silence_scan_seconds must be at least validation_seconds, otherwise the silence "
                "fallback would inspect less audio than the check that triggered it"
            )
        return self

    def matches(self, suffix: str) -> bool:
        return suffix.lower() in self.extensions


class AnalysisSettings(ConfigSection):
    version: int = Field(ge=1)
    sample_rate: int = Field(ge=8000)
    hop_length: int = Field(ge=1)
    refine_hop_length: int = Field(ge=1)
    start_bpm: float = Field(gt=0.0)
    min_bpm: float = Field(gt=0.0)
    max_bpm: float = Field(gt=0.0)
    min_beats: int = Field(ge=2)
    max_ibi_cv: float = Field(gt=0.0)
    min_onset_contrast: Fraction
    min_confidence: Fraction
    refine_search_radius_frames: int = Field(ge=1)

    @property
    def frame_hz(self) -> float:
        """Frame rate of the tempo/beat onset envelope."""
        return self.sample_rate / self.hop_length

    @property
    def refine_frame_hz(self) -> float:
        """Frame rate of the higher-resolution envelope used for beat refinement."""
        return self.sample_rate / self.refine_hop_length

    @model_validator(mode="after")
    def _analysis_ranges_must_be_ordered(self) -> Self:
        if self.refine_hop_length > self.hop_length:
            raise ValueError("refine_hop_length must not be coarser than hop_length")
        if self.min_bpm >= self.max_bpm:
            raise ValueError("min_bpm must be below max_bpm")
        if not (self.min_bpm <= self.start_bpm <= self.max_bpm):
            raise ValueError("start_bpm must lie within [min_bpm, max_bpm]")
        return self


class EnergySettings(ConfigSection):
    alpha: Fraction
    rms_floor_db: float = Field(lt=0.0)
    rms_ceiling_db: float
    curve_hz: float = Field(gt=0.0)
    aggregation: Literal["mean", "median", "p90"]
    normalization_low_percentile: float = Field(ge=0.0, lt=100.0)
    normalization_high_percentile: float = Field(gt=0.0, le=100.0)

    @model_validator(mode="after")
    def _ranges_must_be_ordered(self) -> Self:
        if self.rms_floor_db >= self.rms_ceiling_db:
            raise ValueError("rms_floor_db must be below rms_ceiling_db")
        if self.normalization_low_percentile >= self.normalization_high_percentile:
            raise ValueError("normalization percentiles must be ordered low < high")
        return self


class StableRegionSettings(ConfigSection):
    window_beats: int = Field(ge=4)
    step_beats: int = Field(ge=1)
    ibi_cv_max: float = Field(gt=0.0)
    ibi_tolerance: float = Field(gt=0.0, lt=1.0)
    in_tolerance_fraction_min: Fraction
    onset_strength_floor: Fraction
    max_regions_per_track: int = Field(ge=1)
    weight_tempo_consistency: Fraction
    weight_onset_strength: Fraction
    weight_in_tolerance: Fraction

    @model_validator(mode="after")
    def _weights_must_sum_to_one(self) -> Self:
        _validate_weight_sum(
            {
                "weight_tempo_consistency": self.weight_tempo_consistency,
                "weight_onset_strength": self.weight_onset_strength,
                "weight_in_tolerance": self.weight_in_tolerance,
            }
        )
        if self.step_beats > self.window_beats:
            raise ValueError("step_beats must not exceed window_beats")
        return self


class RetrievalSettings(ConfigSection):
    max_bpm_deviation_pct: float = Field(gt=0.0, le=50.0)
    relaxed_bpm_deviation_pct: float = Field(gt=0.0, le=50.0)
    energy_filter_enabled: bool
    max_energy_delta: Fraction
    require_stable_region: bool
    allow_repeats: bool

    @model_validator(mode="after")
    def _relaxed_must_not_tighten(self) -> Self:
        if self.relaxed_bpm_deviation_pct < self.max_bpm_deviation_pct:
            raise ValueError("relaxed_bpm_deviation_pct must not be stricter than the strict value")
        return self


class RankingSettings(ConfigSection):
    weight_tempo: Fraction
    weight_energy: Fraction
    weight_quality: Fraction

    @model_validator(mode="after")
    def _weights_must_sum_to_one(self) -> Self:
        _validate_weight_sum(
            {
                "weight_tempo": self.weight_tempo,
                "weight_energy": self.weight_energy,
                "weight_quality": self.weight_quality,
            }
        )
        return self


class TransitionSettings(ConfigSection):
    crossfade_beats: int = Field(ge=4)
    margin_beats: int = Field(ge=0)
    outgoing_search_fraction: SearchRange
    incoming_search_fraction: SearchRange
    weight_stability: Fraction
    weight_energy: Fraction
    weight_stretch: Fraction
    weight_position: Fraction
    align_on_downbeat: bool

    @model_validator(mode="after")
    def _weights_and_ranges(self) -> Self:
        _validate_weight_sum(
            {
                "weight_stability": self.weight_stability,
                "weight_energy": self.weight_energy,
                "weight_stretch": self.weight_stretch,
                "weight_position": self.weight_position,
            }
        )
        for name in ("outgoing_search_fraction", "incoming_search_fraction"):
            low, high = getattr(self, name)
            if low >= high:
                raise ValueError(f"{name} must be an ordered (low, high) pair")
        return self


class TempoSettings(ConfigSection):
    min_stretch_ratio: float = Field(gt=0.0, le=1.0)
    max_stretch_ratio: float = Field(ge=1.0)
    stretch_backend: Literal["pedalboard", "rubberband_cli", "phase_vocoder"]

    @property
    def max_stretch_deviation(self) -> float:
        """Largest allowed distance from a 1.0 (unstretched) ratio."""
        return max(self.max_stretch_ratio - 1.0, 1.0 - self.min_stretch_ratio)


class RenderSettings(ConfigSection):
    sample_rate: int = Field(ge=8000)
    channels: Literal[1, 2]
    output_bit_depth: Literal[16, 24, 32]
    peak_ceiling_dbfs: float = Field(le=0.0)


class SessionSettings(ConfigSection):
    default_length: int = Field(ge=2)
    selection_strategy: Literal["random", "nearest_bpm", "greedy", "beam"]


class EvaluationSettings(ConfigSection):
    excerpt_seconds: float = Field(gt=0.0)
    pair_count: int = Field(ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTODJ_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        yaml_file=DEFAULT_CONFIG_PATH,
    )

    database_url: str
    audio_library_dir: Path
    render_cache_dir: Path
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    log_format: Literal["console", "json"]

    ingestion: IngestionSettings
    analysis: AnalysisSettings
    energy: EnergySettings
    stable_regions: StableRegionSettings
    retrieval: RetrievalSettings
    ranking: RankingSettings
    transition: TransitionSettings
    tempo: TempoSettings
    render: RenderSettings
    session: SessionSettings
    evaluation: EvaluationSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )

    def snapshot(self) -> dict[str, Any]:
        """JSON-serializable copy for the ``config_snapshot`` stored with every session."""
        return self.model_dump(mode="json")


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Load settings from ``default.yaml``, then ``env_file``, then the environment.

    Pass ``env_file=None`` to ignore a developer's ``.env``, which tests rely on for
    determinism. The ignore is needed because pydantic-settings synthesizes ``__init__`` from
    the model fields, so its dunder arguments are invisible to type checkers.
    """
    return Settings(_env_file=env_file)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
