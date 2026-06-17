from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.aggregation.base import BaseAggregator, SessionContext
from src.core.schemas import MeasurementDefinition


class MassSummary(BaseAggregator):
    """
    Aggregates processed mass data across sessions.
    Produces a summary table CSV and a boxplot PNG of net cable mass.
    """

    def __init__(self, derived_dir: Path | None = None) -> None:
        self._derived_dir = derived_dir

    def aggregate(
        self,
        sessions: list[SessionContext],
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        summaries = self.load_summaries(sessions, "mass")
        outputs: dict[str, Path] = {}

        if summaries:
            table_df = self._build_summary_table(summaries)
            table_path = output_dir / "mass_summary.csv"
            table_df.to_csv(table_path, index=False)
            outputs["mass_summary_table"] = table_path

            boxplot_path = output_dir / "mass_boxplot.png"
            self._generate_boxplot(sessions, boxplot_path)
            outputs["mass_boxplot"] = boxplot_path

        return outputs

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
            "num_measurements",
            "mean_cable_mass_g",
            "std_cable_mass_g",
            "min_cable_mass_g",
            "max_cable_mass_g",
            "median_cable_mass_g",
            "mean_cable_mass_g_per_cm",
            "std_cable_mass_g_per_cm",
        ]
        rows: list[dict] = []
        for s in summaries:
            row = {col: s.get(col) for col in columns}
            rows.append(row)

        return pd.DataFrame(rows, columns=columns)

    def _generate_boxplot(self, sessions: list[SessionContext], output_path: Path) -> None:
        """Generate a boxplot of net cable mass distributions across sessions."""
        data: list[list[float]] = []
        labels: list[str] = []

        for ctx in sessions:
            csv_path = ctx.derived_dir / "normalized_mass.csv"

            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path)
            if "cable_mass_g" in df.columns:
                values = df["cable_mass_g"].dropna().tolist()
                if values:
                    data.append(values)
                    labels.append(ctx.label)

        if not data:
            return

        fig, ax = plt.subplots(figsize=(max(6, len(data) * 1.5), 5))
        ax.boxplot(data, tick_labels=labels)
        ax.set_ylabel("Net cable mass (g)")
        ax.set_title("Cable Mass Distribution by Session")
        if len(labels) > 3:
            plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
