from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.experiment_schemas import ExperimentRecord
from src.core.schemas import ExperimentDefinition
from src.processing.base import BaseProcessor

PHASE_NAMES = {0: "rising", 1: "falling"}


def _longest_zero_run(arr: np.ndarray) -> tuple[int, int]:
    """
    Find the longest contiguous run of zeros in a 1D array.

    Returns (start_index, length). If no zeros found, returns (0, 0).
    """
    if len(arr) == 0:
        return (0, 0)

    is_zero = arr == 0
    best_start = 0
    best_len = 0
    current_start = 0
    current_len = 0

    for i, z in enumerate(is_zero):
        if z:
            if current_len == 0:
                current_start = i
            current_len += 1
            if current_len > best_len:
                best_start = current_start
                best_len = current_len
        else:
            current_len = 0

    return (best_start, best_len)


def extract_eye_opening(
    eye_2d: np.ndarray,
) -> dict[str, float]:
    """
    Extract eye opening metrics from a 2D histogram (voltage x time).

    Uses center-scan: scan center time-column for eye height,
    scan center voltage-row for eye width.

    Returns dict with: eye_height_bins, eye_width_bins,
    eye_height_ratio, eye_width_ratio, eye_area_ratio.
    """
    v_bins, t_bins = eye_2d.shape

    center_col = eye_2d[:, t_bins // 2]
    _, height_bins = _longest_zero_run(center_col)

    center_row = eye_2d[v_bins // 2, :]
    _, width_bins = _longest_zero_run(center_row)

    height_ratio = height_bins / v_bins if v_bins > 0 else 0.0
    width_ratio = width_bins / t_bins if t_bins > 0 else 0.0

    return {
        "eye_height_bins": int(height_bins),
        "eye_width_bins": int(width_bins),
        "eye_height_ratio": round(float(height_ratio), 6),
        "eye_width_ratio": round(float(width_ratio), 6),
        "eye_area_ratio": round(float(height_ratio * width_ratio), 6),
    }


class ExtractEyeMetrics(BaseProcessor):
    """
    Reads manifest.csv and raw .npz files, extracts eye opening metrics
    per file per phase, and writes metrics CSV + summary JSON.
    """

    def __init__(self, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir

    @property
    def name(self) -> str:
        return "extract_eye_metrics"

    def process(
        self,
        experiment_dir: Path,
        experiment: ExperimentRecord,
        definition: ExperimentDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest = pd.read_csv(experiment_dir / "manifest.csv")
        manifest.columns = manifest.columns.str.strip()

        rows: list[dict] = []
        for _, mrow in manifest.iterrows():
            filename = str(mrow["filename"]).strip()
            npz_path = experiment_dir / "raw" / filename
            cable_length_mm = float(mrow["cable_length_mm"])
            data_rate_mbps = float(mrow["data_rate_mbps"])
            signal_type = str(
                mrow.get("signal_type", experiment.type_fields.get("signal_type", ""))
            )
            notes = str(mrow.get("notes", "")) if "notes" in mrow.index else ""

            data = np.load(npz_path)
            eye = data["eye"]

            has_voltage_range = "voltage_range" in data
            has_time_range = "time_range" in data
            voltage_range = data["voltage_range"] if has_voltage_range else None
            time_range = data["time_range"] if has_time_range else None

            for phase_idx in range(eye.shape[2]):
                eye_2d = eye[:, :, phase_idx]
                metrics = extract_eye_opening(eye_2d)

                row = {
                    "filename": filename,
                    "phase": PHASE_NAMES.get(phase_idx, str(phase_idx)),
                    "cable_length_mm": cable_length_mm,
                    "data_rate_mbps": data_rate_mbps,
                    "signal_type": signal_type,
                    **metrics,
                }

                if has_voltage_range and voltage_range is not None:
                    v_span = float(voltage_range[1] - voltage_range[0])
                    row["eye_height_mv"] = round(metrics["eye_height_ratio"] * v_span, 4)

                if has_time_range and time_range is not None:
                    t_span = float(time_range[1] - time_range[0])
                    row["eye_width_ps"] = round(metrics["eye_width_ratio"] * t_span, 4)

                if notes:
                    row["notes"] = notes

                rows.append(row)

        metrics_df = pd.DataFrame(rows)
        metrics_path = output_dir / "eye_metrics.csv"
        metrics_df.to_csv(metrics_path, index=False)

        summary = self._compute_summary(metrics_df, experiment)
        summary_path = output_dir / "eye_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "eye_metrics_csv": metrics_path,
            "eye_summary_json": summary_path,
        }

    def _compute_summary(self, df: pd.DataFrame, experiment: ExperimentRecord) -> dict:
        summary: dict = {
            "experiment_id": experiment.experiment_id,
            "num_files": df["filename"].nunique() if "filename" in df.columns else 0,
            "num_measurements": len(df),
        }

        for col in ["eye_height_ratio", "eye_width_ratio", "eye_area_ratio"]:
            if col in df.columns and not df[col].isna().all():
                series = df[col].dropna()
                summary[f"mean_{col}"] = round(float(series.mean()), 6)
                summary[f"min_{col}"] = round(float(series.min()), 6)
                summary[f"max_{col}"] = round(float(series.max()), 6)

        if "cable_length_mm" in df.columns and not df["cable_length_mm"].isna().all():
            lengths = df["cable_length_mm"].dropna().unique()
            summary["cable_length_mm_values"] = sorted(float(v) for v in lengths)

        type_fields = experiment.type_fields
        for key in [
            "cable_model",
            "oscilloscope",
            "signal_type",
            "data_rate_mbps",
            "signal_amplitude_mv",
        ]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
