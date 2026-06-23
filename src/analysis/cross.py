"""
Cross-cutting analysis: results that span profiles and measurement types.

Consumes per-profile consolidated metrics (derived/profiles/) plus the
miniscope power models, and produces the repo's headline outputs in
derived/cross/:

- resistivity_summary.csv          one row per profile (fit across lengths)
- supply_voltage.csv (+ PNG/scope) allowable supply-V window per miniscope x profile x length
- max_length_summary.csv           voltage-limited max length at the reference supply
- quality_scores.csv (+ PNG/rate)  consolidated 0-1 score with works/marginal zones
- miniscope_quality.csv (+ PNG/scope) quality at each miniscope's own rate,
  tagged measured (eye/link data) or projected_from_vna (no eye hardware)
- commutator_impact.csv             standalone added R / attenuation per miniscope
- commutator_length_impact.csv      cable-length budget each commutator costs

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
from src.analysis.projection import attenuation_at_hz, nyquist_hz
from src.analysis.quality_score import QualityInputs, score, zone
from src.analysis.resistivity import fit_resistivity
from src.analysis.supply_voltage import max_length_row, supply_voltage_rows
from src.core.loading import load_model, load_profile
from src.core.model_schemas import MiniscopeModel

logger = logging.getLogger(__name__)

ZONE_COLORS = {
    "works": "#2e7d32",
    "marginal": "#f9a825",
    "not_recommended": "#c62828",
}


def _shade_quality_zones(ax, config: AnalysisConfig) -> None:
    """Shade the works/marginal/not-recommended quality bands behind a 0-1 plot."""
    ax.axhspan(config.zones.works, 1.0, color=ZONE_COLORS["works"], alpha=0.10)
    ax.axhspan(config.zones.marginal, config.zones.works, color=ZONE_COLORS["marginal"], alpha=0.10)
    ax.axhspan(0.0, config.zones.marginal, color=ZONE_COLORS["not_recommended"], alpha=0.10)
    ax.axhline(config.zones.works, color=ZONE_COLORS["works"], lw=0.8, ls="--")
    ax.axhline(config.zones.marginal, color=ZONE_COLORS["marginal"], lw=0.8, ls="--")


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


def _load_profile_kinds(repo_root: Path) -> dict[str, str]:
    """profile_id -> 'cable' | 'commutator' from profiles/*.yaml."""
    kinds: dict[str, str] = {}
    profiles_dir = repo_root / "profiles"
    if not profiles_dir.exists():
        return kinds
    for path in sorted(profiles_dir.glob("*.yaml")):
        try:
            profile = load_profile(path)
        except Exception as e:
            logger.warning("Failed to load profile %s: %s", path, e)
            continue
        kinds[profile.profile_id] = profile.profile_type
    return kinds


def _resistivity_table(consolidated: dict[str, dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for profile_id, data in consolidated.items():
        by_length = data.get("resistance_by_length", [])
        by_length = [r for r in by_length if r.get("cable_length_mm") is not None]
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
    reference_supply_v: float,
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
            lengths.update(
                r["cable_length_mm"]
                for r in data.get(key, [])
                if r.get("cable_length_mm") is not None
            )

        for miniscope in miniscopes:
            rows.extend(
                supply_voltage_rows(miniscope, profile_id, rho, sorted(lengths), reference_supply_v)
            )

    return pd.DataFrame(rows)


def _max_length_table(
    consolidated: dict[str, dict],
    resistivity_df: pd.DataFrame,
    miniscopes: list[MiniscopeModel],
    reference_supply_v: float,
) -> pd.DataFrame:
    """Voltage-limited max usable length at the reference supply, per miniscope x profile."""
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
            row = max_length_row(miniscope, profile_id, rho, reference_supply_v)
            if row is not None:
                rows.append(row)

    return pd.DataFrame(rows)


def _commutator_measured(data: dict) -> tuple[float | None, dict]:
    """
    Pull a commutator's measured standalone numbers from its consolidated
    rows: (added series resistance in ohm, attenuation_db_by_hz map).
    """
    added_resistance = None
    for row in data.get("resistance_by_length", []):
        if row.get("mean_roundtrip_resistance_ohm") is not None:
            added_resistance = row["mean_roundtrip_resistance_ohm"]
            break

    attenuation_by_hz: dict = {}
    for row in data.get("vna_by_length", []):
        if row.get("attenuation_db_by_hz"):
            attenuation_by_hz = row["attenuation_db_by_hz"]
            break

    return added_resistance, attenuation_by_hz


def _commutator_impact_table(
    commutators: dict[str, dict],
    miniscopes: list[MiniscopeModel],
) -> pd.DataFrame:
    """
    STANDALONE commutator impact per miniscope (ADR 0001: no cable x
    commutator matrix). The commutator sits in series in the link, so:

    - power: its measured series resistance raises the supply floor by
      I_max * R_comm (and eats the same amount of cable budget);
    - signal: its insertion loss at the miniscope's Nyquist frequency adds
      directly to the cable's attenuation.
    """
    rows: list[dict] = []
    for commutator_id, data in sorted(commutators.items()):
        added_r, attenuation_by_hz = _commutator_measured(data)
        for miniscope in miniscopes:
            added_attenuation = None
            if miniscope.serdes_rate_gbps is not None and attenuation_by_hz:
                added_attenuation = attenuation_at_hz(
                    attenuation_by_hz, nyquist_hz(miniscope.serdes_rate_gbps)
                )
            delta_v = None
            if added_r is not None and miniscope.max_current_ma is not None:
                delta_v = (miniscope.max_current_ma / 1000.0) * added_r
            if added_r is None and added_attenuation is None:
                continue
            rows.append(
                {
                    "commutator_id": commutator_id,
                    "miniscope_model": miniscope.model_id,
                    "added_resistance_ohm": added_r,
                    "supply_floor_increase_v": (round(delta_v, 4) if delta_v is not None else None),
                    "rate_gbps": miniscope.serdes_rate_gbps,
                    "added_attenuation_db": (
                        round(added_attenuation, 4) if added_attenuation is not None else None
                    ),
                }
            )
    return pd.DataFrame(rows)


def _commutator_length_impact_table(
    commutators: dict[str, dict],
    resistivity_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    How much voltage-limited cable budget a commutator costs, per cable:
    its series resistance is equivalent to R_comm / rho metres of that
    cable, so the max usable length shortens by about that much.
    """
    rows: list[dict] = []
    if resistivity_df.empty:
        return pd.DataFrame(rows)

    for commutator_id, data in sorted(commutators.items()):
        added_r, _ = _commutator_measured(data)
        if added_r is None:
            continue
        for _, cable in resistivity_df.iterrows():
            rho = cable["roundtrip_resistivity_ohm_per_m"]
            if rho is None or rho <= 0:
                continue
            rows.append(
                {
                    "commutator_id": commutator_id,
                    "profile_id": cable["profile_id"],
                    "added_resistance_ohm": added_r,
                    "max_length_reduction_mm": round(added_r / rho * 1000.0, 1),
                }
            )
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

        # Score only the characterized forward link rates (config.serdes_rates_gbps,
        # e.g. 3 & 6 Gbps). The 187.5 Mbps reverse control channel is excluded on
        # purpose: it is low-rate and robust, never the link bottleneck, and its
        # link-margin algorithm runs stricter -- so it would drag the score down
        # without reflecting real usability. It is still measured and shown in the
        # per-cable SerDes detail table, just not in the headline quality number.
        scored_rates = {float(rate) for rate in config.serdes_rates_gbps}

        # Group serdes rows by (length, rate), take worst case across channels
        by_length_rate: dict[tuple[float, float], list[dict]] = {}
        for r in serdes_rows:
            rate = float(r["rate_gbps"])
            if rate not in scored_rates:
                continue
            key = (r["cable_length_mm"], rate)
            by_length_rate.setdefault(key, []).append(r)

        for (length_mm, rate), combos in sorted(by_length_rate.items()):
            eye_areas = [
                c["mean_eye_area_ratio"] for c in combos if c.get("mean_eye_area_ratio") is not None
            ]
            margins = [
                c["mean_link_margin_mv"] for c in combos if c.get("mean_link_margin_mv") is not None
            ]

            # Attenuation at the link's own Nyquist fundamental (rate/2) -- the
            # same quantity the projected path uses -- NOT the worst-case
            # broadband insertion loss, which penalizes a cable for loss far
            # above its link frequency (a short coax can show ~10 dB at 3 GHz
            # while losing <1 dB at its actual rate). None (Nyquist outside the
            # swept span) drops the term and renormalizes the remaining weights.
            vna_row = vna_by_length.get(length_mm)
            attenuation_db = None
            if vna_row:
                attenuation_db = attenuation_at_hz(
                    vna_row.get("attenuation_db_by_hz", {}), nyquist_hz(rate)
                )

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


def _miniscope_quality_table(
    consolidated: dict[str, dict],
    quality_df: pd.DataFrame,
    miniscopes: list[MiniscopeModel],
    config: AnalysisConfig,
) -> pd.DataFrame:
    """
    Quality-vs-length per miniscope, at THAT miniscope's link rate (ADR 0001
    steps 2-3). Two co-equal sources, always tagged:

    - "measured": the miniscope's rate has eye/link data (GMSL2 rates) --
      rows come straight from the per-rate quality table.
    - "projected_from_vna": no eye hardware at that rate (FPD-Link III) --
      the score is computed from the cable's VNA attenuation interpolated at
      the link's Nyquist fundamental (rate/2), and only within the measured
      sweep span (never extrapolated).
    """
    rows: list[dict] = []
    measured_rates: set[float] = (
        set(quality_df["rate_gbps"].astype(float)) if not quality_df.empty else set()
    )

    for miniscope in miniscopes:
        rate = miniscope.serdes_rate_gbps
        if rate is None:
            continue

        if rate in measured_rates:
            for _, qrow in quality_df[quality_df["rate_gbps"].astype(float) == rate].iterrows():
                rows.append(
                    {
                        "miniscope_model": miniscope.model_id,
                        "profile_id": qrow["profile_id"],
                        "cable_length_mm": qrow["cable_length_mm"],
                        "rate_gbps": rate,
                        "quality_score": qrow["quality_score"],
                        "zone": qrow["zone"],
                        "source": "measured",
                        "attenuation_db": qrow.get("attenuation_db"),
                    }
                )
            continue

        # No eye data at this rate: project from VNA attenuation at Nyquist
        target_hz = nyquist_hz(rate)
        for profile_id, data in consolidated.items():
            for vna_row in data.get("vna_by_length", []):
                attenuation = attenuation_at_hz(vna_row.get("attenuation_db_by_hz", {}), target_hz)
                if attenuation is None:
                    continue
                score_value = score(QualityInputs(attenuation_db=attenuation), config)
                if score_value is None:
                    continue
                rows.append(
                    {
                        "miniscope_model": miniscope.model_id,
                        "profile_id": profile_id,
                        "cable_length_mm": vna_row["cable_length_mm"],
                        "rate_gbps": rate,
                        "quality_score": score_value,
                        "zone": zone(score_value, config),
                        "source": "projected_from_vna",
                        "attenuation_db": round(attenuation, 4),
                    }
                )

    return pd.DataFrame(rows)


def _plot_miniscope_quality(
    miniscope_quality_df: pd.DataFrame,
    miniscope_id: str,
    config: AnalysisConfig,
    output_path: Path,
) -> bool:
    """Quality vs length for one miniscope at its rate, tagged measured/projected."""
    scope_df = miniscope_quality_df[miniscope_quality_df["miniscope_model"] == miniscope_id]
    if scope_df.empty:
        return False

    fig, ax = plt.subplots(figsize=(8, 5))
    _shade_quality_zones(ax, config)

    projected = bool((scope_df["source"] == "projected_from_vna").any())
    for profile_id, group in scope_df.groupby("profile_id"):
        group = group.sort_values("cable_length_mm")
        ax.plot(
            group["cable_length_mm"],
            group["quality_score"],
            marker="o",
            ls="--" if projected else "-",
            label=profile_id,
        )

    rate = float(scope_df["rate_gbps"].iloc[0])
    tag = "PROJECTED from VNA attenuation" if projected else "measured"
    ax.set_xlabel("Cable length (mm)")
    ax.set_ylabel("Quality score (0-1)")
    ax.set_ylim(0, 1.05)
    ax.set_title(f"{miniscope_id}: cable quality vs length at {rate:g} Gbps ({tag})")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return True


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
    _shade_quality_zones(ax, config)

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
    band between them is the usable window. The reference-supply line (the
    USB 5 V rail, from config/analysis.yaml) is marked so the voltage-limited
    max length is read directly off where the floor crosses it.
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

    reference_v = float(scope_df["reference_supply_v"].iloc[0])
    ax.axhline(
        reference_v,
        color="#455a64",
        lw=1.0,
        ls=":",
        label=f"reference supply ({reference_v:g} V USB)",
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
    all_consolidated = _load_consolidated_profiles(repo_root)
    if not all_consolidated:
        return {}

    # Split DUT kinds: the cable analyses (resistivity, supply window,
    # quality vs length) only apply to cables; commutators get their own
    # standalone-impact outputs below.
    kinds = _load_profile_kinds(repo_root)
    consolidated = {
        pid: d for pid, d in all_consolidated.items() if kinds.get(pid, "cable") == "cable"
    }
    commutators = {pid: d for pid, d in all_consolidated.items() if kinds.get(pid) == "commutator"}

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
    supply_df = _supply_voltage_table(
        consolidated, resistivity_df, miniscopes, config.reference_supply_v
    )
    if not supply_df.empty:
        path = output_dir / "supply_voltage.csv"
        supply_df.to_csv(path, index=False)
        outputs["supply_voltage_table"] = path

        for miniscope_id in supply_df["miniscope_model"].unique():
            plot_path = output_dir / f"supply_voltage_{miniscope_id}.png"
            if _plot_supply_voltage(supply_df, miniscope_id, plot_path):
                outputs[f"supply_voltage_plot_{miniscope_id}"] = plot_path

    # Voltage-limited max usable length at the reference supply
    max_length_df = _max_length_table(
        consolidated, resistivity_df, miniscopes, config.reference_supply_v
    )
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

    # Quality per miniscope, at the miniscope's own rate (measured or
    # projected from VNA). Co-equal with the supply-voltage outputs above.
    miniscope_quality_df = _miniscope_quality_table(consolidated, quality_df, miniscopes, config)
    if not miniscope_quality_df.empty:
        path = output_dir / "miniscope_quality.csv"
        miniscope_quality_df.to_csv(path, index=False)
        outputs["miniscope_quality"] = path

        for miniscope_id in miniscope_quality_df["miniscope_model"].unique():
            plot_path = output_dir / f"miniscope_quality_{miniscope_id}.png"
            if _plot_miniscope_quality(miniscope_quality_df, miniscope_id, config, plot_path):
                outputs[f"miniscope_quality_plot_{miniscope_id}"] = plot_path

    # Commutator standalone impact (no cable x commutator matrix)
    if commutators:
        impact_df = _commutator_impact_table(commutators, miniscopes)
        if not impact_df.empty:
            path = output_dir / "commutator_impact.csv"
            impact_df.to_csv(path, index=False)
            outputs["commutator_impact"] = path

        length_impact_df = _commutator_length_impact_table(commutators, resistivity_df)
        if not length_impact_df.empty:
            path = output_dir / "commutator_length_impact.csv"
            length_impact_df.to_csv(path, index=False)
            outputs["commutator_length_impact"] = path

    return outputs
