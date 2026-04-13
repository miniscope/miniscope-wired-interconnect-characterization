from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.core.experiment_schemas import ExperimentRecord
from src.core.schemas import ExperimentDefinition
from src.processing.base import BaseProcessor


class NormalizeResistance(BaseProcessor):
    """
    Reads measurements.csv, normalizes columns, computes resistance per meter,
    and writes normalized CSV + summary JSON.
    """

    def __init__(self, models_dir: Path | None = None) -> None:
        self._models_dir = models_dir

    @property
    def name(self) -> str:
        return "normalize_resistance"

    def process(
        self,
        experiment_dir: Path,
        experiment: ExperimentRecord,
        definition: ExperimentDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        df = self._read_measurements(experiment_dir)
        df = self._compute_derived(df)

        normalized_path = output_dir / "normalized_resistance.csv"
        df.to_csv(normalized_path, index=False)

        summary = self._compute_summary(df, experiment)
        summary_path = output_dir / "resistance_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "normalized_resistance_csv": normalized_path,
            "resistance_summary_json": summary_path,
        }

    def _read_measurements(self, experiment_dir: Path) -> pd.DataFrame:
        """Read measurements.csv and validate column types."""
        csv_path = experiment_dir / "measurements.csv"
        df = pd.read_csv(csv_path)

        df.columns = df.columns.str.strip()
        df["resistance_ohm"] = pd.to_numeric(df["resistance_ohm"], errors="coerce")
        df["cable_length_mm"] = pd.to_numeric(df["cable_length_mm"], errors="coerce")

        df = df.dropna(subset=["resistance_ohm", "cable_length_mm"])
        return df

    def _compute_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute resistance_per_m from resistance and cable length."""
        df = df.copy()
        df["resistance_per_m"] = df["resistance_ohm"] / (df["cable_length_mm"] / 1000.0)
        return df

    def _compute_summary(self, df: pd.DataFrame, experiment: ExperimentRecord) -> dict:
        """Compute summary statistics and attach experiment metadata."""
        summary: dict = {
            "experiment_id": experiment.experiment_id,
            "num_measurements": len(df),
        }

        for col in ["resistance_ohm", "resistance_per_m"]:
            if col in df.columns and not df[col].isna().all():
                series = df[col].dropna()
                summary[f"mean_{col}"] = round(float(series.mean()), 6)
                summary[f"std_{col}"] = round(float(series.std()), 6)
                summary[f"min_{col}"] = round(float(series.min()), 6)
                summary[f"max_{col}"] = round(float(series.max()), 6)
                summary[f"median_{col}"] = round(float(series.median()), 6)

        if not df["cable_length_mm"].isna().all():
            lengths = df["cable_length_mm"].dropna().unique()
            if len(lengths) == 1:
                summary["cable_length_mm"] = float(lengths[0])
            else:
                summary["cable_length_mm_values"] = [float(v) for v in sorted(lengths)]

        type_fields = experiment.type_fields
        for key in ["cable_model", "measurement_method", "measurement_instrument", "temperature_c"]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
