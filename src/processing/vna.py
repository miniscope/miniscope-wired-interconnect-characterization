from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import BaseProcessor, copy_type_fields, session_header
from src.processing.touchstone import TouchstoneData, parse_s2p


def _interpolate_at_freq(
    frequencies_hz: np.ndarray, values_db: np.ndarray, target_hz: float
) -> float | None:
    """Interpolate a value at a target frequency. Returns None if out of range."""
    if target_hz < frequencies_hz[0] or target_hz > frequencies_hz[-1]:
        return None
    return float(np.interp(target_hz, frequencies_hz, values_db))


@dataclass
class AbcdMatrix:
    """The ABCD (transmission/cascade) matrix of a 2-port, per frequency.

    Each of a, b, c, d is a complex array over frequency: a and d are
    dimensionless, b has units of ohms, c of siemens. The matrix relates the
    input port (V1, I1) to the output (V2, I2) as
    [V1 I1]^T = [[a, b], [c, d]] [V2, -I2]^T, which makes cascaded networks
    multiply. For a reciprocal 2-port det = a*d - b*c = 1. Built from
    S-parameters via `sparams_to_abcd`; the cable's characteristic impedance
    follows as sqrt(b/c) -- see `characteristic_impedance`.
    """

    a: np.ndarray
    b: np.ndarray
    c: np.ndarray
    d: np.ndarray


def sparams_to_abcd(
    s11: np.ndarray,
    s21: np.ndarray,
    s12: np.ndarray,
    s22: np.ndarray,
    z_ref: float = 50.0,
) -> AbcdMatrix:
    """Convert 2-port S-parameters (referenced to real ``z_ref``) to ABCD.

    Standard reciprocal-network conversion (same real reference impedance at
    both ports). The conversion divides by S21, so entries blow up at deep
    transmission nulls (|S21| -> 0); callers guard with np.isfinite. Inputs are
    coerced to complex arrays, so the cable's complex S-parameters (magnitude
    and phase) feed straight in.
    """
    s11 = np.asarray(s11, dtype=complex)
    s21 = np.asarray(s21, dtype=complex)
    s12 = np.asarray(s12, dtype=complex)
    s22 = np.asarray(s22, dtype=complex)

    with np.errstate(divide="ignore", invalid="ignore"):
        denom = 2.0 * s21
        a = ((1 + s11) * (1 - s22) + s12 * s21) / denom
        b = z_ref * ((1 + s11) * (1 + s22) - s12 * s21) / denom
        c = ((1 - s11) * (1 - s22) - s12 * s21) / (denom * z_ref)
        d = ((1 - s11) * (1 + s22) + s12 * s21) / denom

    return AbcdMatrix(a=a, b=b, c=c, d=d)


def characteristic_impedance(abcd: AbcdMatrix) -> np.ndarray:
    """Characteristic impedance Z0(f) = sqrt(B/C) from an ABCD matrix, in ohms.

    Exact for a uniform reciprocal line and a robust estimate for a real cable.
    Complex in general; callers typically take the real part.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.sqrt(abcd.b / abcd.c)


def summarize_characteristic_impedance(z0_real: np.ndarray) -> float | None:
    """Single robust characteristic impedance (ohms) from a Re(Z0(f)) trace.

    Median of Re(Z0) over the middle 80% of the band, dropping the lowest and
    highest 10% of points (where connector and fixture effects distort the
    estimate) and any non-finite/non-positive samples (the spikes at deep S21
    nulls). Returns None if no usable points remain. Shared by the offline
    metric (`estimate_characteristic_impedance`) and the capture-page readout
    so both report the same number.
    """
    real = np.asarray(z0_real, dtype=float)
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


def characteristic_impedance_profile(ts: TouchstoneData) -> np.ndarray | None:
    """
    Per-frequency characteristic impedance Z0(f) of the cable, in ohms.

    Method: treat the cable as a 2-port, convert its complex S-parameters
    (normalized to the measurement reference impedance) to the ABCD matrix via
    `sparams_to_abcd`, then take Z0 = sqrt(B/C) (`characteristic_impedance`).
    This needs phase, which is why the Touchstone parser retains complex
    S-parameters. Returns the complex Z0(f) (callers typically take the real
    part), or None if complex data is unavailable.

    NOTE: connector/fixture discontinuities dominate Z0 at the band edges, so
    the scalar in `estimate_characteristic_impedance` reports a mid-band
    value rather than a single point.
    """
    if ts.s21.size == 0:
        return None

    abcd = sparams_to_abcd(ts.s11, ts.s21, ts.s12, ts.s22, z_ref=ts.ref_impedance)
    return characteristic_impedance(abcd)


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
    return summarize_characteristic_impedance(np.real(z0))


class ProcessVNA(BaseProcessor):
    """
    Parses Touchstone .s2p files, extracts S-parameters, computes attenuation
    metrics, and writes metrics CSV + traces CSV + summary JSON.

    Cable length is structural: it comes from the session, not the manifest.
    """

    # Reference frequencies include the Nyquist fundamentals of the link
    # rates we project/report quality at: 750 MHz (FPD-Link III ~1.5 Gbps),
    # 1.5 GHz (GMSL2 3 Gbps), 3 GHz (GMSL2 6 Gbps). Frequencies outside a
    # sweep's span are skipped.
    METRIC_FREQUENCIES_HZ = [1e6, 10e6, 100e6, 500e6, 750e6, 1e9, 1.5e9, 3e9]
    METRIC_FREQ_LABELS = ["1MHz", "10MHz", "100MHz", "500MHz", "750MHz", "1GHz", "1500MHz", "3GHz"]

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

    def _compute_file_metrics(self, ts: TouchstoneData, cable_length_mm: float | None) -> dict:
        """Compute scalar metrics for one .s2p file."""
        metrics: dict = {}

        metrics["max_insertion_loss_db"] = round(float(np.min(ts.s21_db)), 4)
        metrics["min_return_loss_db"] = round(float(np.max(ts.s11_db)), 4)

        impedance = estimate_characteristic_impedance(ts)
        metrics["characteristic_impedance_ohm"] = (
            round(impedance, 2) if impedance is not None else None
        )

        # Per-metre normalization only applies to cables; commutators have
        # no length, their absolute insertion loss IS the result.
        cable_length_m = cable_length_mm / 1000.0 if cable_length_mm is not None else 0.0

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
        summary: dict = {**session_header(session), "num_files": len(df)}

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

        # Attenuation (positive dB) at each reference frequency the sweep
        # covered, keyed by frequency in Hz. Downstream, quality projection
        # interpolates this map at a link rate's Nyquist frequency.
        attenuation_by_hz: dict[str, float] = {}
        for freq_hz, label in zip(
            self.METRIC_FREQUENCIES_HZ, self.METRIC_FREQ_LABELS, strict=False
        ):
            col = f"insertion_loss_{label}_db"
            if col in df.columns and not df[col].isna().all():
                attenuation_by_hz[str(int(freq_hz))] = round(-float(df[col].dropna().mean()), 4)
        if attenuation_by_hz:
            summary["attenuation_db_by_hz"] = attenuation_by_hz

        copy_type_fields(
            summary, session, ["vna_instrument", "calibration_type", "port_impedance_ohm"]
        )
        return summary
