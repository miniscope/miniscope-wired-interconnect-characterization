"""Typed access to config/analysis.yaml (quality-score weights, zones, etc.)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class QualityWeights(BaseModel):
    """Relative weight of each metric in the consolidated quality score."""

    model_config = ConfigDict(extra="forbid")

    eye_area: float = Field(ge=0)
    link_margin: float = Field(ge=0)
    attenuation: float = Field(ge=0)


class QualityReferences(BaseModel):
    """Normalization references: the metric value that maps to a score of 0."""

    model_config = ConfigDict(extra="forbid")

    link_margin_full_scale_mv: float = Field(gt=0)
    attenuation_full_scale_db: float = Field(gt=0)


class QualityScoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: QualityWeights
    references: QualityReferences


class ZonesConfig(BaseModel):
    """Score thresholds for the user-facing works/marginal/not-recommended zones."""

    model_config = ConfigDict(extra="forbid")

    works: float = Field(ge=0, le=1)
    marginal: float = Field(ge=0, le=1)


class AnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_score: QualityScoreConfig
    zones: ZonesConfig
    serdes_rates_gbps: list[int]
    vna_reference_frequencies_hz: list[float]


def load_analysis_config(path: Path) -> AnalysisConfig:
    """Load and validate config/analysis.yaml."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AnalysisConfig.model_validate(raw)
