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
    """Normalization references for the per-metric sub-scores.

    ``link_margin_full_scale_mv`` and ``attenuation_full_scale_db`` are the
    metric values that map to a sub-score of 0 (worst). ``eye_area_full_scale``
    is the opposite end: the eye-area ratio that maps to a sub-score of 1
    (best). An eye never fills its bounding box, so a wide-open, healthy eye
    occupies only a fraction of the EOM scan window -- this reference is well
    below 1.0, and feeding the raw ratio in unnormalized would cap the eye
    term far below its weight.
    """

    model_config = ConfigDict(extra="forbid")

    eye_area_full_scale: float = Field(gt=0, le=1.0)
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
    # Reporting reference for supply-window outputs (the USB 5 V rail).
    # A user-side choice, deliberately not a miniscope-model property.
    reference_supply_v: float = Field(gt=0)
    serdes_rates_gbps: list[int]
    vna_reference_frequencies_hz: list[float]


def load_analysis_config(path: Path) -> AnalysisConfig:
    """Load and validate config/analysis.yaml."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AnalysisConfig.model_validate(raw)
