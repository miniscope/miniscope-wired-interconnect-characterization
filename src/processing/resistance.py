from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import BaseProcessor


class NormalizeResistance(BaseProcessor):
    """
    Reads resistance.csv, computes round-trip resistance per meter, and
    writes normalized CSV + summary JSON.

    The resistance protocol measures round-trip loop resistance (one cable
    end shorted, LCR meter at the other), so the per-meter value is the
    combined center-conductor + shield-return resistance per meter of cable.
    Cable length is structural: it comes from the session, not the CSV.
    """

    def __init__(self, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir

    @property
    def name(self) -> str:
        return "normalize_resistance"

    def process(
        self,
        session_dir: Path,
        session: SessionRecord,
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        df = self._read_measurements(session_dir)
        df = self._compute_derived(df, session.cable_length_mm)

        normalized_path = output_dir / "normalized_resistance.csv"
        df.to_csv(normalized_path, index=False)

        summary = self._compute_summary(df, session)
        summary_path = output_dir / "resistance_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "normalized_resistance_csv": normalized_path,
            "resistance_summary_json": summary_path,
        }

    def _read_measurements(self, session_dir: Path) -> pd.DataFrame:
        """Read resistance.csv and validate column types."""
        csv_path = session_dir / "resistance.csv"
        df = pd.read_csv(csv_path)

        df.columns = df.columns.str.strip()
        df["resistance_ohm"] = pd.to_numeric(df["resistance_ohm"], errors="coerce")

        df = df.dropna(subset=["resistance_ohm"])
        return df

    def _compute_derived(self, df: pd.DataFrame, cable_length_mm: float) -> pd.DataFrame:
        """Compute round-trip resistance per meter from the session's cable length."""
        df = df.copy()
        cable_length_m = cable_length_mm / 1000.0
        df["roundtrip_resistance_ohm_per_m"] = df["resistance_ohm"] / cable_length_m
        return df

    def _compute_summary(self, df: pd.DataFrame, session: SessionRecord) -> dict:
        """Compute summary statistics and attach session metadata."""
        summary: dict = {
            "session_id": session.session_id,
            "profile_id": session.profile_id,
            "cable_length_mm": session.cable_length_mm,
            "measurement_type": session.measurement_type,
            "date": str(session.date),
            "operator": session.operator,
            "num_measurements": len(df),
        }

        for col in ["resistance_ohm", "roundtrip_resistance_ohm_per_m"]:
            if col in df.columns and not df[col].isna().all():
                series = df[col].dropna()
                summary[f"mean_{col}"] = round(float(series.mean()), 6)
                summary[f"std_{col}"] = round(float(series.std()), 6)
                summary[f"min_{col}"] = round(float(series.min()), 6)
                summary[f"max_{col}"] = round(float(series.max()), 6)
                summary[f"median_{col}"] = round(float(series.median()), 6)

        type_fields = session.type_fields
        for key in ["measurement_method", "measurement_instrument", "temperature_c"]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
