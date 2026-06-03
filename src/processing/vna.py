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


def characteristic_impedance_profile(ts: TouchstoneData) -> np.ndarray | None:
    """
    Per-frequency characteristic impedance Z0(f) of the cable, in ohms.

    Method: treat the cable as a 2-port and convert its complex
    S-parameters (normalized to the measurement reference impedance) to the
    ABCD matrix, then use the transmission-line identity Z0 = sqrt(B/C).
    This is exact for a uniform reciprocal line and a robust estimate for a
    real cable; it needs phase, which is why the Touchstone parser retains
    complex S-parameters. Returns the complex Z0(f); callers typically take
    the real part. Returns None if complex data is unavailable.

    NOTE: connector/fixture discontinuities dominate Z0 at the band edges, so
    the scalar in `estimate_characteristic_impedance` reports a mid-band
    value rather than a single point.
    """
    if ts.s21.size == 0:
        return None

    z_ref = ts.ref_impedance
    s11, s21, s12, s22 = ts.s11, ts.s21, ts.s12, ts.s22

    # S -> ABCD (B and C are all we need for Z0 = sqrt(B/C)).
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = 2.0 * s21
        b = z_ref * ((1 + s11) * (1 + s22) - s12 * s21) / denom
        c = ((1 - s11) * (1 - s22) - s12 * s21) / (denom * z_ref)
        z0 = np.sqrt(b / c)

    return z0


def estimate_characteristic_impedance(ts: TouchstoneData) -> float | None:
    """
    Single characteristic-impedance value for the cable, in ohms.

    Takes the median of Re(Z0(f)) over the middle 80% of the swept band
    (dropping the lowest/highest 10% of points, where connector and fixture
    effects distort the estimate). Returns None if no usable points exist.
    """
    z0 = characteristic_impedance_profile(ts)
    if z0 is None:
        return None

    real = np.real(z0)
    finite = np.isfinite(real) & (real > 0)
    if not finite.any():
        return None

    n = real.size
    lo, hi = int(0.1 * n), max(int(0.1 * n) + 1, int(0.9 * n))
    band = np.zeros(n, dtype=bool)
    band[lo:hi] = True
    usable = real[finite & band]
    if usable.size == 0:
        usable = real[finite]

    return float(np.median(usable))


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

            z0_profile = characteristic_impedance_profile(ts)
            for i, (freq, s21, s11) in enumerate(
                zip(ts.frequencies_hz, ts.s21_db, ts.s11_db, strict=False)
            ):
                z0 = float(np.real(z0_profile[i])) if z0_profile is not None else None
                trace_rows.append(
                    {
                        "filename": filename,
                        "frequency_hz": float(freq),
                        "s21_db": round(float(s21), 4),
                        "s11_db": round(float(s11), 4),
                        "attenuation_db": round(-float(s21), 4),
                        "impedance_ohm": round(z0, 4)
                        if z0 is not None and np.isfinite(z0)
                        else None,
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

        if (
            "characteristic_impedance_ohm" in df.columns
            and not df["characteristic_impedance_ohm"].isna().all()
        ):
            series = df["characteristic_impedance_ohm"].dropna()
            summary["mean_characteristic_impedance_ohm"] = round(float(series.mean()), 2)

        type_fields = session.type_fields
        for key in ["vna_instrument", "calibration_type", "port_impedance_ohm"]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
