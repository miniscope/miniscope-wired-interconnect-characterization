"""
Per-profile consolidation: combine repeated sessions into one set of
metrics per (cable length, measurement type).

Repeated measures are first-class in this repo: any (profile, length, type)
can have many sessions. Processing (src/processing/) turns each session
into a summary JSON; this module pools those summaries so that downstream
consumers (cross-cutting analysis, wiki pages) see one row per condition
with across-session variability (mean, std, n).

Outputs per profile, under derived/profiles/<profile_id>/:
- resistance_by_length.csv  (one row per length)
- serdes_by_length.csv      (one row per length x channel x rate)
- vna_by_length.csv         (one row per length)
- consolidated.json         (everything above, nested, for downstream code)
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.core.loading import load_session
from src.core.session_schemas import SessionRecord, length_dir_name

logger = logging.getLogger(__name__)


def _mean_std_n(values: list[float]) -> dict:
    """Across-session pooled statistics. std is None with fewer than 2 values."""
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "std": None, "n_sessions": 0}
    return {
        "mean": round(statistics.fmean(values), 6),
        "std": round(statistics.stdev(values), 6) if len(values) > 1 else None,
        "n_sessions": len(values),
    }


def _load_summary(repo_root: Path, session: SessionRecord) -> dict | None:
    """Load the processed summary JSON for a session, if processing has run."""
    summary_names = {
        "resistance": "resistance_summary.json",
        "serdes": "serdes_summary.json",
        "vna": "vna_summary.json",
    }
    name = summary_names.get(session.measurement_type)
    if name is None:
        return None

    summary_path = (
        repo_root
        / "derived"
        / "sessions"
        / session.profile_id
        / length_dir_name(session.cable_length_mm)
        / session.measurement_type
        / session.session_id
        / name
    )
    if not summary_path.exists():
        logger.warning("No processed summary for %s, skipping", summary_path.parent)
        return None
    with open(summary_path) as f:
        return json.load(f)


def _group_sessions_by_type(
    repo_root: Path, profile_id: str
) -> dict[str, list[tuple[SessionRecord, dict]]]:
    """Collect (session, summary) pairs for a profile, grouped by measurement type."""
    groups: dict[str, list[tuple[SessionRecord, dict]]] = defaultdict(list)
    profile_dir = repo_root / "measurements" / profile_id
    if not profile_dir.exists():
        return groups

    for yaml_path in sorted(profile_dir.glob("*/*/*/session.yaml")):
        try:
            session = load_session(yaml_path)
        except Exception as e:
            logger.warning("Skipping unloadable session %s: %s", yaml_path, e)
            continue
        summary = _load_summary(repo_root, session)
        if summary is None:
            continue
        groups[session.measurement_type].append((session, summary))

    return groups


def _consolidate_resistance(entries: list[tuple[SessionRecord, dict]]) -> list[dict]:
    """One row per length: pooled round-trip resistance stats across sessions."""
    by_length: dict[float, list[dict]] = defaultdict(list)
    for session, summary in entries:
        by_length[session.cable_length_mm].append(summary)

    rows: list[dict] = []
    for length_mm in sorted(by_length):
        summaries = by_length[length_mm]
        per_m = _mean_std_n([s.get("mean_roundtrip_resistance_ohm_per_m") for s in summaries])
        rows.append(
            {
                "cable_length_mm": length_mm,
                "n_sessions": per_m["n_sessions"],
                "total_measurements": sum(s.get("num_measurements", 0) for s in summaries),
                "mean_roundtrip_resistance_ohm_per_m": per_m["mean"],
                "std_roundtrip_resistance_ohm_per_m": per_m["std"],
            }
        )
    return rows


def _consolidate_serdes(entries: list[tuple[SessionRecord, dict]]) -> list[dict]:
    """One row per (length, channel, rate): pooled eye + margin stats."""
    by_combo: dict[tuple[float, str, int], list[dict]] = defaultdict(list)
    for session, summary in entries:
        for combo in summary.get("combos", []):
            key = (session.cable_length_mm, combo["channel"], int(combo["rate_gbps"]))
            by_combo[key].append(combo)

    rows: list[dict] = []
    for length_mm, channel, rate in sorted(by_combo):
        combos = by_combo[(length_mm, channel, rate)]
        row: dict = {
            "cable_length_mm": length_mm,
            "channel": channel,
            "rate_gbps": rate,
            "n_sessions": len(combos),
        }
        for metric in [
            "eye_area_ratio",
            "eye_height_mv",
            "eye_width_ps",
            "link_margin_mv",
        ]:
            stats = _mean_std_n([c.get(metric) for c in combos])
            row[f"mean_{metric}"] = stats["mean"]
            row[f"std_{metric}"] = stats["std"]
        rows.append(row)
    return rows


def _consolidate_vna(entries: list[tuple[SessionRecord, dict]]) -> list[dict]:
    """One row per length: pooled insertion-loss stats across sessions."""
    by_length: dict[float, list[dict]] = defaultdict(list)
    for session, summary in entries:
        by_length[session.cable_length_mm].append(summary)

    rows: list[dict] = []
    for length_mm in sorted(by_length):
        summaries = by_length[length_mm]
        il = _mean_std_n([s.get("mean_max_insertion_loss_db") for s in summaries])
        worst = [
            s.get("worst_max_insertion_loss_db")
            for s in summaries
            if s.get("worst_max_insertion_loss_db") is not None
        ]

        # Pool attenuation-at-reference-frequency maps across sessions: mean
        # per frequency over the sessions that covered it. Quality projection
        # interpolates this at a link rate's Nyquist frequency.
        attenuation_by_hz: dict[str, float] = {}
        freq_keys = sorted(
            {k for s in summaries for k in s.get("attenuation_db_by_hz", {})}, key=float
        )
        for key in freq_keys:
            values = [
                s["attenuation_db_by_hz"][key]
                for s in summaries
                if key in s.get("attenuation_db_by_hz", {})
            ]
            attenuation_by_hz[key] = round(statistics.fmean(values), 4)

        rows.append(
            {
                "cable_length_mm": length_mm,
                "n_sessions": il["n_sessions"],
                "mean_max_insertion_loss_db": il["mean"],
                "std_max_insertion_loss_db": il["std"],
                "worst_max_insertion_loss_db": min(worst) if worst else None,
                "attenuation_db_by_hz": attenuation_by_hz,
            }
        )
    return rows


def consolidate_profile(repo_root: Path, profile_id: str) -> dict[str, Path]:
    """
    Consolidate all processed sessions for one profile.

    Returns mapping of output logical name -> file path. Returns an empty
    mapping when the profile has no processed sessions yet.
    """
    groups = _group_sessions_by_type(repo_root, profile_id)
    if not groups:
        return {}

    output_dir = repo_root / "derived" / "profiles" / profile_id
    output_dir.mkdir(parents=True, exist_ok=True)

    consolidated: dict = {"profile_id": profile_id}
    outputs: dict[str, Path] = {}

    consolidators = {
        "resistance": ("resistance_by_length", _consolidate_resistance),
        "serdes": ("serdes_by_length", _consolidate_serdes),
        "vna": ("vna_by_length", _consolidate_vna),
    }

    for type_name, (output_name, consolidator) in consolidators.items():
        entries = groups.get(type_name, [])
        rows = consolidator(entries) if entries else []
        consolidated[output_name] = rows
        if rows:
            csv_path = output_dir / f"{output_name}.csv"
            df = pd.DataFrame(rows)
            # Nested (dict-valued) fields live in consolidated.json only
            nested = [c for c in df.columns if df[c].map(lambda v: isinstance(v, dict)).any()]
            df.drop(columns=nested).to_csv(csv_path, index=False)
            outputs[f"{profile_id}_{output_name}"] = csv_path

    json_path = output_dir / "consolidated.json"
    with open(json_path, "w") as f:
        json.dump(consolidated, f, indent=2)
    outputs[f"{profile_id}_consolidated_json"] = json_path

    return outputs


def consolidate_profiles(repo_root: Path) -> dict[str, Path]:
    """Consolidate every profile that has measurements."""
    measurements_dir = repo_root / "measurements"
    outputs: dict[str, Path] = {}
    if not measurements_dir.exists():
        return outputs

    for profile_dir in sorted(measurements_dir.iterdir()):
        if not profile_dir.is_dir() or profile_dir.name.startswith("."):
            continue
        outputs.update(consolidate_profile(repo_root, profile_dir.name))

    return outputs
