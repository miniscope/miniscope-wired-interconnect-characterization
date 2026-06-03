"""
Consolidated 0-1 quality score per (profile, length, data rate).

This is the single number a non-technical user reads off the main wiki
plot: "will this cable at this length work for my Miniscope?" It combines
the worst-case eye opening, the link-margin floor, and (when available)
VNA attenuation into one score, then maps the score onto
works / marginal / not_recommended zones.

============================ DEFERRED DECISION ============================
TODO (Daniel): the formula below is a PLACEHOLDER weighted sum so the
plumbing can run end to end. Finalize the formula, the weights, and the
zone thresholds in config/analysis.yaml once real measurements exist.
All tunable values live in config/analysis.yaml -- nothing here is
hard-coded on purpose.
===========================================================================
"""

from __future__ import annotations

from dataclasses import dataclass

from src.analysis.config import AnalysisConfig


@dataclass
class QualityInputs:
    """
    Worst-case metrics for one (profile, length, rate), taken across
    channels and sessions. Any field may be None when that measurement
    hasn't been made; missing metrics are dropped and the remaining
    weights renormalized.
    """

    eye_area_ratio: float | None = None  # 0-1, already normalized
    link_margin_mv: float | None = None  # lowest error-free TX amplitude; LOWER is better
    attenuation_db: float | None = None  # positive dB; lower is better


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(inputs: QualityInputs, config: AnalysisConfig) -> float | None:
    """
    Compute the consolidated quality score in [0, 1].

    Per-metric sub-scores (each 0-1, 1 = best):
    - eye_area_ratio is already a 0-1 fraction of the unit interval
    - link margin: 1 at 0 mV floor, 0 at link_margin_full_scale_mv
    - attenuation: 1 at 0 dB, 0 at attenuation_full_scale_db

    Returns None when no metric is available at all.
    """
    weights = config.quality_score.weights
    refs = config.quality_score.references

    components: list[tuple[float, float]] = []  # (weight, sub_score)

    if inputs.eye_area_ratio is not None:
        components.append((weights.eye_area, _clamp01(inputs.eye_area_ratio)))

    if inputs.link_margin_mv is not None:
        sub = _clamp01(1.0 - inputs.link_margin_mv / refs.link_margin_full_scale_mv)
        components.append((weights.link_margin, sub))

    if inputs.attenuation_db is not None:
        sub = _clamp01(1.0 - inputs.attenuation_db / refs.attenuation_full_scale_db)
        components.append((weights.attenuation, sub))

    total_weight = sum(w for w, _ in components)
    if total_weight == 0:
        return None

    return round(sum(w * s for w, s in components) / total_weight, 6)


def zone(score_value: float, config: AnalysisConfig) -> str:
    """Map a score onto the user-facing recommendation zones."""
    if score_value >= config.zones.works:
        return "works"
    if score_value >= config.zones.marginal:
        return "marginal"
    return "not_recommended"
