"""
Cross-cutting analysis: results that span profiles and measurement types.

Consumes per-profile consolidated metrics (derived/profiles/) plus the
miniscope power models, and produces the repo's headline outputs in
derived/cross/:

- resistivity_summary.csv          one row per profile (fit across lengths)
- supply_voltage.csv (+ PNG/scope) allowable supply-V window per miniscope x profile x length
- max_length_summary.csv           voltage-limited max length at the default supply
- quality_scores.csv (+ PNG/rate)  consolidated 0-1 score with works/marginal zones

These are exactly the tables/plots the wiki pages are rendered from.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.analysis.config import AnalysisConfig, load_analysis_config
from src.analysis.quality_score import QualityInputs, score, zone
from src.analysis.resistivity import fit_resistivity
from src.analysis.supply_voltage import max_length_row, supply_voltage_rows
from src.core.loading import load_model
from src.core.model_schemas import MiniscopeModel

logger = logging.getLogger(__name__)

ZONE_COLORS = {
    "works": "#2e7d32",
    "marginal": "#f9a825",
    "not_recommended": "#c62828",
}


def _load_consolidated_profiles(repo_root: Path) -> dict[str, dict]:
    """Load every derived/profiles/<id>/consolidated.json."""
    profiles: dict[str, dict] = {}
    profiles_dir = repo_root / "derived" / "profiles"
    if not profiles_dir.exists():
        return profiles
    for json_path in sorted(profiles_dir.glob("*/consolidated.json")):
        try:
            with open(json_path) as f:
                profiles[json_path.parent.name] = json.load(f)
        except Exception as e:
            logger.warning("Failed to load %s: %s", json_path, e)
    return profiles


def _load_miniscopes(repo_root: Path) -> list[MiniscopeModel]:
    miniscopes: list[MiniscopeModel] = []
    models_dir = repo_root / "models" / "miniscope_models"
    if not models_dir.exists():
        return miniscopes
    for path in sorted(models_dir.glob("*.yaml")):
        try:
            miniscopes.append(load_model(path, model_type="miniscope_models"))
        except Exception as e:
            logger.warning("Failed to load miniscope model %s: %s", path, e)
    return miniscopes


def _resistivity_table(consolidated: dict[str, dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for profile_id, data in consolidated.items():
        by_length = data.get("resistance_by_length", [])
        fit = fit_resistivity(
            [r["cable_length_mm"] for r in by_length],
            [r["mean_roundtrip_resistance_ohm_per_m"] for r in by_length],
        )
        if fit is None:
            continue
        rows.append({"profile_id": profile_id, **fit.to_dict()})
    return pd.DataFrame(rows)


def _supply_voltage_table(
    consolidated: dict[str, dict],
    resistivity_df: pd.DataFrame,
    miniscopes: list[MiniscopeModel],
) -> pd.DataFrame:
    rows: list[dict] = []
    if resistivity_df.empty:
        return pd.DataFrame(rows)

    resistivity_by_profile = resistivity_df.set_index("profile_id")[
        "roundtrip_resistivity_ohm_per_m"
    ].to_dict()

    for profile_id, data in consolidated.items():
        rho = resistivity_by_profile.get(profile_id)
        if rho is None:
            continue
        # Report at every length the profile has ANY measurement for
        lengths: set[float] = set()
        for key in ["resistance_by_length", "serdes_by_length", "vna_by_length"]:
            lengths.update(r["cable_length_mm"] for r in data.get(key, []))

        for miniscope in miniscopes:
            rows.extend(supply_voltage_rows(miniscope, profile_id, rho, sorted(lengths)))

    return pd.DataFrame(rows)


def _max_length_table(
    consolidated: dict[str, dict],
    resistivity_df: pd.DataFrame,
    miniscopes: list[MiniscopeModel],
) -> pd.DataFrame:
    """Voltage-limited max usable length at the default supply, per miniscope x profile."""
    rows: list[dict] = []
    if resistivity_df.empty:
        return pd.DataFrame(rows)

    resistivity_by_profile = resistivity_df.set_index("profile_id")[
        "roundtrip_resistivity_ohm_per_m"
    ].to_dict()

    for profile_id in consolidated:
        rho = resistivity_by_profile.get(profile_id)
        if rho is None:
            continue
        for miniscope in miniscopes:
            row = max_length_row(miniscope, profile_id, rho)
            if row is not None:
                rows.append(row)

    return pd.DataFrame(rows)


def _quality_table(consolidated: dict[str, dict], config: AnalysisConfig) -> pd.DataFrame:
    """
    One row per (profile, length, rate): worst-case inputs across channels,
    consolidated score, and zone.
    """
    rows: list[dict] = []
    for profile_id, data in consolidated.items():
        serdes_rows = data.get("serdes_by_length", [])
        vna_by_length = {r["cable_length_mm"]: r for r in data.get("vna_by_length", [])}

        # Group serdes rows by (length, rate), take worst case across channels
        by_length_rate: dict[tuple[float, int], list[dict]] = {}
        for r in serdes_rows:
            key = (r["cable_length_mm"], int(r["rate_gbps"]))
            by_length_rate.setdefault(key, []).append(r)

        for (length_mm, rate), combos in sorted(by_length_rate.items()):
            eye_areas = [
                c["mean_eye_area_ratio"] for c in combos if c.get("mean_eye_area_ratio") is not None
            ]
            margins = [
                c["mean_link_margin_mv"] for c in combos if c.get("mean_link_margin_mv") is not None
            ]

            vna_row = vna_by_length.get(length_mm)
            attenuation_db = None
            if vna_row and vna_row.get("mean_max_insertion_loss_db") is not None:
                # Insertion loss is negative dB; attenuation is its magnitude
                attenuation_db = abs(vna_row["mean_max_insertion_loss_db"])

            inputs = QualityInputs(
                eye_area_ratio=min(eye_areas) if eye_areas else None,
                link_margin_mv=max(margins) if margins else None,
                attenuation_db=attenuation_db,
            )
            score_value = score(inputs, config)
            if score_value is None:
                continue

            rows.append(
                {
                    "profile_id": profile_id,
                    "cable_length_mm": length_mm,
                    "rate_gbps": rate,
                    "worst_eye_area_ratio": inputs.eye_area_ratio,
                    "worst_link_margin_mv": inputs.link_margin_mv,
                    "attenuation_db": inputs.attenuation_db,
                    "quality_score": score_value,
                    "zone": zone(score_value, config),
                }
            )

    return pd.DataFrame(rows)


def _plot_quality_vs_length(
    quality_df: pd.DataFrame,
    rate: int,
    config: AnalysisConfig,
    output_path: Path,
) -> bool:
    rate_df = quality_df[quality_df["rate_gbps"] == rate]
    if rate_df.empty:
        return False

    fig, ax = plt.subplots(figsize=(8, 5))

    # Shaded recommendation zones behind the curves
    ax.axhspan(config.zones.works, 1.0, color=ZONE_COLORS["works"], alpha=0.10)
    ax.axhspan(config.zones.marginal, config.zones.works, color=ZONE_COLORS["marginal"], alpha=0.10)
    ax.axhspan(0.0, config.zones.marginal, color=ZONE_COLORS["not_recommended"], alpha=0.10)
    ax.axhline(config.zones.works, color=ZONE_COLORS["works"], lw=0.8, ls="--")
    ax.axhline(config.zones.marginal, color=ZONE_COLORS["marginal"], lw=0.8, ls="--")

    for profile_id, group in rate_df.groupby("profile_id"):
        group = group.sort_values("cable_length_mm")
        ax.plot(
            group["cable_length_mm"],
            group["quality_score"],
            marker="o",
            label=profile_id,
        )

    ax.set_xlabel("Cable length (mm)")
    ax.set_ylabel("Quality score (0-1)")
    ax.set_ylim(0, 1.05)
    ax.set_title(f"Cable quality vs length at {rate} Gbps")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return True


def _plot_supply_voltage(
    supply_df: pd.DataFrame,
    miniscope_id: str,
    output_path: Path,
) -> bool:
    """
    Allowable supply-voltage window vs cable length for one miniscope.

    Per cable: the floor (V_supply_min, solid) is the brownout limit and the
    ceiling (V_supply_max, dashed) the regulator's over-voltage limit; the
    band between them is the usable window. The default-supply line (e.g.
    5 V USB) is marked so the voltage-limited max length is read directly off
    where the floor crosses it.
    """
    scope_df = supply_df[supply_df["miniscope_model"] == miniscope_id]
    if scope_df.empty:
        return False

    fig, ax = plt.subplots(figsize=(8, 5))
    has_ceiling = False
    for profile_id, group in scope_df.groupby("profile_id"):
        group = group.sort_values("cable_length_mm")
        line = ax.plot(
            group["cable_length_mm"],
            group["v_supply_min"],
            marker="o",
            label=f"{profile_id} (min supply)",
        )[0]
        ceiling = group["v_supply_max"]
        if ceiling.notna().any():
            has_ceiling = True
            ax.plot(
                group["cable_length_mm"],
                ceiling,
                marker="o",
                ls="--",
                color=line.get_color(),
                alpha=0.6,
                label=f"{profile_id} (max supply)",
            )
            ax.fill_between(
                group["cable_length_mm"],
                group["v_supply_min"],
                ceiling,
                color=line.get_color(),
                alpha=0.10,
            )

    default_v = float(scope_df["default_supply_v"].iloc[0])
    ax.axhline(
        default_v, color="#455a64", lw=1.0, ls=":", label=f"default supply ({default_v:g} V)"
    )

    ax.set_xlabel("Cable length (mm)")
    ax.set_ylabel("Supply voltage (V)")
    band = " window" if has_ceiling else " floor"
    ax.set_title(f"Allowable supply-voltage{band} vs cable length ({miniscope_id})")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return True


def run_cross_analysis(repo_root: Path) -> dict[str, Path]:
    """
    Run all cross-cutting analysis. Requires processing + consolidation to
    have run first (reads derived/profiles/).
    """
    config = load_analysis_config(repo_root / "config" / "analysis.yaml")
    consolidated = _load_consolidated_profiles(repo_root)
    if not consolidated:
        return {}

    output_dir = repo_root / "derived" / "cross"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    # Resistivity per profile
    resistivity_df = _resistivity_table(consolidated)
    if not resistivity_df.empty:
        path = output_dir / "resistivity_summary.csv"
        resistivity_df.to_csv(path, index=False)
        outputs["resistivity_summary"] = path

    # Supply voltage per miniscope x profile x length
    miniscopes = _load_miniscopes(repo_root)
    supply_df = _supply_voltage_table(consolidated, resistivity_df, miniscopes)
    if not supply_df.empty:
        path = output_dir / "supply_voltage.csv"
        supply_df.to_csv(path, index=False)
        outputs["supply_voltage_table"] = path

        for miniscope_id in supply_df["miniscope_model"].unique():
            plot_path = output_dir / f"supply_voltage_{miniscope_id}.png"
            if _plot_supply_voltage(supply_df, miniscope_id, plot_path):
                outputs[f"supply_voltage_plot_{miniscope_id}"] = plot_path

    # Voltage-limited max usable length at the default supply
    max_length_df = _max_length_table(consolidated, resistivity_df, miniscopes)
    if not max_length_df.empty:
        path = output_dir / "max_length_summary.csv"
        max_length_df.to_csv(path, index=False)
        outputs["max_length_summary"] = path

    # Quality scores per profile x length x rate
    quality_df = _quality_table(consolidated, config)
    if not quality_df.empty:
        path = output_dir / "quality_scores.csv"
        quality_df.to_csv(path, index=False)
        outputs["quality_scores"] = path

        for rate in config.serdes_rates_gbps:
            plot_path = output_dir / f"quality_vs_length_{rate}g.png"
            if _plot_quality_vs_length(quality_df, rate, config, plot_path):
                outputs[f"quality_vs_length_plot_{rate}g"] = plot_path

    return outputs
