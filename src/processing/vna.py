from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import BaseProcessor
from src.processing.touchstone import TouchstoneData, parse_s2p


def _interpolate_at_freq(
    frequencies_hz: np.ndarray, values_db: np.ndarray, target_hz: float
) -> float | None:
    """Interpolate a value at a target frequency. Returns None if out of range."""
    if target_hz < frequencies_hz[0] or target_hz > frequencies_hz[-1]:
        return None
    return float(np.interp(target_hz, frequencies_hz, values_db))


def estimate_characteristic_impedance(ts: TouchstoneData) -> float | None:
    """
    Estimate the cable's characteristic impedance from S-parameters.

    TODO (deferred decision): choose the extraction method (e.g. TDR-style
    transform of S11 vs analytic fit against the reference impedance).
    Until then this returns None and downstream consumers must handle it.
    """
    return None


class ProcessVNA(BaseProcessor):
    """
    Parses Touchstone .s2p files, extracts S-parameters, computes attenuation
    metrics, and writes metrics CSV + traces CSV + summary JSON.

    Cable length is structural: it comes from the session, not the manifest.
    """

    METRIC_FREQUENCIES_HZ = [1e6, 10e6, 100e6, 1e9]
    METRIC_FREQ_LABELS = ["1MHz", "10MHz", "100MHz", "1GHz"]

    def __init__(self, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir

    @property
    def name(self) -> str:
        return "process_vna"

    def process(
        self,
        session_dir: Path,
        session: SessionRecord,
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest = pd.read_csv(session_dir / "manifest.csv")
        manifest.columns = manifest.columns.str.strip()

        cable_length_mm = session.cable_length_mm
        metric_rows: list[dict] = []
        trace_rows: list[dict] = []

        for _, mrow in manifest.iterrows():
            filename = str(mrow["filename"]).strip()
            s2p_path = session_dir / "raw" / filename
            description = str(mrow.get("description", "")) if "description" in mrow.index else ""

            ts = parse_s2p(s2p_path)

            for freq, s21, s11 in zip(ts.frequencies_hz, ts.s21_db, ts.s11_db, strict=False):
                trace_rows.append(
                    {
                        "filename": filename,
                        "frequency_hz": float(freq),
                        "s21_db": round(float(s21), 4),
                        "s11_db": round(float(s11), 4),
                        "attenuation_db": round(-float(s21), 4),
                    }
                )

            metrics = self._compute_file_metrics(ts, cable_length_mm)
            metrics["filename"] = filename
            metrics["description"] = description
            metrics["num_points"] = ts.num_points
            metrics["frequency_start_hz"] = ts.frequency_start_hz
            metrics["frequency_stop_hz"] = ts.frequency_stop_hz
            metric_rows.append(metrics)

        metrics_df = pd.DataFrame(metric_rows)
        metrics_path = output_dir / "vna_metrics.csv"
        metrics_df.to_csv(metrics_path, index=False)

        traces_df = pd.DataFrame(trace_rows)
        traces_path = output_dir / "vna_traces.csv"
        traces_df.to_csv(traces_path, index=False)

        summary = self._compute_summary(metrics_df, session)
        summary_path = output_dir / "vna_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "vna_metrics_csv": metrics_path,
            "vna_traces_csv": traces_path,
            "vna_summary_json": summary_path,
        }

    def _compute_file_metrics(self, ts: TouchstoneData, cable_length_mm: float) -> dict:
        """Compute scalar metrics for one .s2p file."""
        metrics: dict = {}

        metrics["max_insertion_loss_db"] = round(float(np.min(ts.s21_db)), 4)
        metrics["min_return_loss_db"] = round(float(np.max(ts.s11_db)), 4)

        impedance = estimate_characteristic_impedance(ts)
        metrics["characteristic_impedance_ohm"] = (
            round(impedance, 2) if impedance is not None else None
        )

        cable_length_m = cable_length_mm / 1000.0

        for freq_hz, label in zip(
            self.METRIC_FREQUENCIES_HZ, self.METRIC_FREQ_LABELS, strict=False
        ):
            il = _interpolate_at_freq(ts.frequencies_hz, ts.s21_db, freq_hz)
            if il is not None:
                metrics[f"insertion_loss_{label}_db"] = round(il, 4)
                if cable_length_m > 0:
                    metrics[f"insertion_loss_{label}_db_per_m"] = round(il / cable_length_m, 4)

        return metrics

    def _compute_summary(self, df: pd.DataFrame, session: SessionRecord) -> dict:
        summary: dict = {
            "session_id": session.session_id,
            "profile_id": session.profile_id,
            "cable_length_mm": session.cable_length_mm,
            "measurement_type": session.measurement_type,
            "date": str(session.date),
            "operator": session.operator,
            "num_files": len(df),
        }

        for col in ["max_insertion_loss_db", "min_return_loss_db"]:
            if col in df.columns and not df[col].isna().all():
                series = df[col].dropna()
                summary[f"mean_{col}"] = round(float(series.mean()), 4)
                summary[f"worst_{col}"] = round(float(series.min()), 4)

        type_fields = session.type_fields
        for key in ["vna_instrument", "calibration_type", "port_impedance_ohm"]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
