from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import BaseProcessor, copy_type_fields, session_header


class NormalizeWeight(BaseProcessor):
    """
    Reads weight.csv, derives the net cable mass and mass per centimetre, and
    writes normalized CSV + summary JSON.

    The weight protocol weighs the whole cable assembly and the non-cable
    fixture (PCBs + SMA connectors) separately, so the net cable mass is
    ``assembly_weight_g - fixture_weight_g``. Cable length is structural: it
    comes from the session, not the CSV, and yields the mass per centimetre.
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

        df = self._read_measurements(session_dir)
        df = self._compute_derived(df, session.cable_length_mm)

        normalized_path = output_dir / "normalized_weight.csv"
        df.to_csv(normalized_path, index=False)

        summary = self._compute_summary(df, session)
        summary_path = output_dir / "weight_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "normalized_weight_csv": normalized_path,
            "weight_summary_json": summary_path,
        }

    def _read_measurements(self, session_dir: Path) -> pd.DataFrame:
        """Read weight.csv and coerce the mass columns to numbers."""
        csv_path = session_dir / "weight.csv"
        df = pd.read_csv(csv_path)

        df.columns = df.columns.str.strip()
        for col in ["assembly_weight_g", "fixture_weight_g"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["assembly_weight_g", "fixture_weight_g"])
        return df

    def _compute_derived(self, df: pd.DataFrame, cable_length_mm: float | None) -> pd.DataFrame:
        """
        Derive net cable mass (assembly minus fixture) and, when the session
        has a length, mass per centimetre. Non-cable DUTs (commutators) have
        no length, so only the net mass applies.
        """
        df = df.copy()
        df["cable_weight_g"] = df["assembly_weight_g"] - df["fixture_weight_g"]
        if cable_length_mm is not None:
            cable_length_cm = cable_length_mm / 10.0
            df["cable_weight_g_per_cm"] = df["cable_weight_g"] / cable_length_cm
        return df

    def _compute_summary(self, df: pd.DataFrame, session: SessionRecord) -> dict:
        """Compute summary statistics and attach session metadata."""
        summary: dict = {**session_header(session), "num_measurements": len(df)}

        for col in [
            "assembly_weight_g",
            "fixture_weight_g",
            "cable_weight_g",
            "cable_weight_g_per_cm",
        ]:
            if col in df.columns and not df[col].isna().all():
                series = df[col].dropna()
                summary[f"mean_{col}"] = round(float(series.mean()), 6)
                summary[f"std_{col}"] = round(float(series.std()), 6)
                summary[f"min_{col}"] = round(float(series.min()), 6)
                summary[f"max_{col}"] = round(float(series.max()), 6)
                summary[f"median_{col}"] = round(float(series.median()), 6)

        copy_type_fields(summary, session, ["measurement_method", "measurement_instrument"])
        return summary
