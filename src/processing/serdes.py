from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import BaseProcessor, session_header
from src.processing.eye import extract_eye_opening, eye_figure, link_margin_metrics

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Every serdes session covers exactly these three lanes: the forward link at
# 3 and 6 Gbps plus the fixed low-rate reverse control channel.
EXPECTED_LANES = frozenset({"fwd_3g", "fwd_6g", "rev_187m"})


class ProcessSerdes(BaseProcessor):
    """
    Processes a GMSL2 SerDes characterization session.

    Reads session_manifest.csv and, for each lane, computes eye-opening metrics
    from the raw eye-monitor grid CSV and link-margin metrics from the raw
    TX-amplitude sweep CSV.

    Writes serdes_metrics.csv (one row per lane) + serdes_summary.json.
    """

    def __init__(self, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir

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
            lane_id = str(mrow["lane_id"]).strip()
            channel = str(mrow["channel"]).strip()
            rate_gbps = float(mrow["rate_gbps"])
            metrics: dict = {"lane_id": lane_id, "channel": channel, "rate_gbps": rate_gbps}

            eye_csv = str(mrow["eye_csv"]).strip()
            metrics["eye_csv"] = eye_csv
            metrics.update(self._eye_metrics(session_dir / eye_csv))

            eye_png = output_dir / f"{Path(eye_csv).stem}.png"
            self._render_eye_png(session_dir / eye_csv, channel, lane_id, eye_png)
            metrics["eye_png"] = eye_png.name

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

    def _eye_metrics(self, eye_csv_path: Path) -> dict:
        """Eye-opening metrics for one lane's raw EOM grid."""
        df = pd.read_csv(eye_csv_path)
        df.columns = df.columns.str.strip()
        return extract_eye_opening(
            df["phase"].to_numpy(),
            df["vth"].to_numpy(),
            df["polarity"].to_numpy(),
            df["errors"].to_numpy(),
            df["hits"].to_numpy(),
        )

    def _render_eye_png(
        self, eye_csv_path: Path, channel: str, lane_id: str, output_path: Path
    ) -> None:
        df = pd.read_csv(eye_csv_path)
        df.columns = df.columns.str.strip()
        fig = eye_figure(
            df["phase"].to_numpy(),
            df["vth"].to_numpy(),
            df["polarity"].to_numpy(),
            df["errors"].to_numpy(),
            df["hits"].to_numpy(),
            channel,
            lane_id,
        )
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)

    def _margin_metrics(self, csv_path: Path) -> dict:
        """Link-margin metrics for one lane's TX-amplitude sweep."""
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        metrics = link_margin_metrics(
            df["tx_amp_mv"].to_numpy(),
            df["errors"].to_numpy(),
        )
        metrics["num_margin_points"] = len(df)
        return metrics

    def _compute_summary(self, rows: list[dict], session: SessionRecord) -> dict:
        summary: dict = {
            **session_header(session),
            "num_lanes": len(rows),
            "combos": [
                {
                    k: row.get(k)
                    for k in [
                        "lane_id",
                        "channel",
                        "rate_gbps",
                        "eye_area_ratio",
                        "zero_error_fraction",
                        "eye_height_mv",
                        "eye_width_ui",
                        "link_margin_mv",
                        "error_onset_mv",
                    ]
                }
                for row in rows
            ],
        }

        # Convenience: worst-case values across lanes (the binding constraint
        # for "will this cable work"). link_margin_mv is the lowest error-free
        # TX amplitude, so LOWER is better and the worst lane has the HIGHEST
        # floor.
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
