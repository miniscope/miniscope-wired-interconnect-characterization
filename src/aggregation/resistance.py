from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.aggregation.base import BaseAggregator, SessionContext
from src.core.schemas import MeasurementDefinition

logger = logging.getLogger(__name__)


class ResistanceSummary(BaseAggregator):
    """
    Aggregates processed resistance data across sessions.
    Produces a summary table CSV and a boxplot PNG.
    """

    def __init__(self, derived_dir: Path | None = None) -> None:
        self._derived_dir = derived_dir

    @property
    def name(self) -> str:
        return "resistance_summary"

    def aggregate(
        self,
        sessions: list[SessionContext],
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        summaries = self._load_session_summaries(sessions)
        outputs: dict[str, Path] = {}

        if summaries:
            table_df = self._build_summary_table(summaries)
            table_path = output_dir / "resistance_summary.csv"
            table_df.to_csv(table_path, index=False)
            outputs["resistance_summary_table"] = table_path

            boxplot_path = output_dir / "resistance_boxplot.png"
            self._generate_boxplot(sessions, boxplot_path)
            outputs["resistance_boxplot"] = boxplot_path

        return outputs

    def _load_session_summaries(self, sessions: list[SessionContext]) -> list[dict]:
        """Load resistance_summary.json from each session's derived output."""
        summaries: list[dict] = []
        for ctx in sessions:
            summary_path = ctx.derived_dir / "resistance_summary.json"

            if not summary_path.exists():
                logger.warning("No processed summary for %s, skipping", ctx.label)
                continue

            with open(summary_path) as f:
                summaries.append(json.load(f))

        return summaries

    def _build_summary_table(self, summaries: list[dict]) -> pd.DataFrame:
        """Build a DataFrame with one row per session."""
        columns = [
            "profile_id",
            "condition",
            "cable_length_mm",
            "session_id",
            "date",
            "operator",
            "measurement_method",
            "measurement_instrument",
            "temperature_c",
            "num_measurements",
            "mean_resistance_ohm",
            "std_resistance_ohm",
            "min_resistance_ohm",
            "max_resistance_ohm",
            "median_resistance_ohm",
            "mean_roundtrip_resistance_ohm_per_m",
            "std_roundtrip_resistance_ohm_per_m",
        ]
        rows: list[dict] = []
        for s in summaries:
            row = {col: s.get(col) for col in columns}
            rows.append(row)

        return pd.DataFrame(rows, columns=columns)

    def _generate_boxplot(self, sessions: list[SessionContext], output_path: Path) -> None:
        """Generate a boxplot of resistance_ohm distributions across sessions."""
        data: list[list[float]] = []
        labels: list[str] = []

        for ctx in sessions:
            csv_path = ctx.derived_dir / "normalized_resistance.csv"

            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path)
            if "resistance_ohm" in df.columns:
                values = df["resistance_ohm"].dropna().tolist()
                if values:
                    data.append(values)
                    labels.append(ctx.label)

        if not data:
            return

        fig, ax = plt.subplots(figsize=(max(6, len(data) * 1.5), 5))
        ax.boxplot(data, tick_labels=labels)
        ax.set_ylabel("Round-trip resistance (ohm)")
        ax.set_title("Resistance Distribution by Session")
        if len(labels) > 3:
            plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
