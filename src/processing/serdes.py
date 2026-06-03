from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import BaseProcessor
from src.processing.eye import (
    extract_eye_opening,
    eye_opening_physical,
    link_margin_metrics,
)

# Every serdes session must cover exactly these channel x rate combos.
SERDES_CHANNELS = ("forward", "back")
SERDES_RATES_GBPS = (3, 6)
EXPECTED_COMBOS = {(c, r) for c in SERDES_CHANNELS for r in SERDES_RATES_GBPS}


class ProcessSerdes(BaseProcessor):
    """
    Processes a GMSL2 SerDes characterization session.

    Reads session_manifest.csv, and for each {forward,back} x {3,6 Gbps}
    combo computes eye-opening metrics from the eye-diagram NPZ and
    link-margin metrics from the TX-amplitude sweep CSV.

    Writes serdes_metrics.csv (one row per combo) + serdes_summary.json.
    """

    def __init__(self, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir

    @property
    def name(self) -> str:
        return "process_serdes"

    def process(
        self,
        session_dir: Path,
        session: SessionRecord,
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest = pd.read_csv(session_dir / "session_manifest.csv")
        manifest.columns = manifest.columns.str.strip()

        rows: list[dict] = []
        for _, mrow in manifest.iterrows():
            channel = str(mrow["channel"]).strip()
            rate_gbps = int(mrow["rate_gbps"])

            metrics: dict = {"channel": channel, "rate_gbps": rate_gbps}

            eye_npz = str(mrow["eye_npz"]).strip()
            metrics["eye_npz"] = eye_npz
            metrics.update(self._eye_metrics(session_dir / eye_npz))

            margin_csv = str(mrow["margin_csv"]).strip()
            metrics["margin_csv"] = margin_csv
            metrics.update(self._margin_metrics(session_dir / margin_csv))

            rows.append(metrics)

        metrics_df = pd.DataFrame(rows)
        metrics_path = output_dir / "serdes_metrics.csv"
        metrics_df.to_csv(metrics_path, index=False)

        summary = self._compute_summary(rows, session)
        summary_path = output_dir / "serdes_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "serdes_metrics_csv": metrics_path,
            "serdes_summary_json": summary_path,
        }

    def _eye_metrics(self, npz_path: Path) -> dict:
        """Eye-opening metrics (bins, ratios, and physical units) for one combo."""
        data = np.load(npz_path)
        eye = data["error_counts"]

        metrics = extract_eye_opening(eye)
        metrics.update(
            eye_opening_physical(metrics, data["voltage_range_mv"], data["time_range_ps"])
        )
        return metrics

    def _margin_metrics(self, csv_path: Path) -> dict:
        """Link-margin metrics for one combo's TX-amplitude sweep."""
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()

        metrics = link_margin_metrics(
            df["tx_amplitude_mv"].to_numpy(),
            df["error_count"].to_numpy(),
        )
        metrics["num_margin_points"] = len(df)
        return metrics

    def _compute_summary(self, rows: list[dict], session: SessionRecord) -> dict:
        summary: dict = {
            "session_id": session.session_id,
            "profile_id": session.profile_id,
            "cable_length_mm": session.cable_length_mm,
            "measurement_type": session.measurement_type,
            "date": str(session.date),
            "operator": session.operator,
            "num_combos": len(rows),
            "combos": [
                {
                    k: row.get(k)
                    for k in [
                        "channel",
                        "rate_gbps",
                        "eye_height_ratio",
                        "eye_width_ratio",
                        "eye_area_ratio",
                        "eye_height_mv",
                        "eye_width_ps",
                        "link_margin_mv",
                        "error_onset_mv",
                    ]
                }
                for row in rows
            ],
        }

        # Convenience: worst-case values across combos (the binding constraint
        # for "will this cable work"). Note link_margin_mv is the lowest
        # error-free TX amplitude, so LOWER is better and the worst combo is
        # the one with the HIGHEST floor.
        areas = [r["eye_area_ratio"] for r in rows if r.get("eye_area_ratio") is not None]
        margins = [r["link_margin_mv"] for r in rows if r.get("link_margin_mv") is not None]
        if areas:
            summary["worst_eye_area_ratio"] = min(areas)
        if margins:
            summary["worst_link_margin_mv"] = max(margins)

        type_fields = session.type_fields
        for key in ["serdes_device", "temperature_c"]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
