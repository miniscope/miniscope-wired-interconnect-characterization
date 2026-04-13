from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.aggregation.base import BaseAggregator
from src.core.loading import load_experiment
from src.core.schemas import ExperimentDefinition

logger = logging.getLogger(__name__)


def _get_experiment_id(exp_dir: Path) -> str | None:
    """Read experiment_id from experiment.yaml, or fall back to dir name."""
    yaml_path = exp_dir / "experiment.yaml"
    if yaml_path.exists():
        try:
            return load_experiment(yaml_path).experiment_id
        except Exception:
            pass
    return exp_dir.name


class ResistanceSummary(BaseAggregator):
    """
    Aggregates processed resistance data across experiments.
    Produces a summary table CSV and a boxplot PNG.
    """

    def __init__(self, derived_dir: Path | None = None) -> None:
        self._derived_dir = derived_dir

    @property
    def name(self) -> str:
        return "resistance_summary"

    def aggregate(
        self,
        experiment_dirs: list[Path],
        definition: ExperimentDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        summaries = self._load_experiment_summaries(experiment_dirs)
        outputs: dict[str, Path] = {}

        if summaries:
            table_df = self._build_summary_table(summaries)
            table_path = output_dir / "resistance_summary.csv"
            table_df.to_csv(table_path, index=False)
            outputs["resistance_summary_table"] = table_path

            boxplot_path = output_dir / "resistance_boxplot.png"
            self._generate_boxplot(experiment_dirs, boxplot_path)
            outputs["resistance_boxplot"] = boxplot_path

        return outputs

    def _normalized_dir(self, exp_dir: Path, exp_id: str) -> Path:
        """Resolve the normalized output directory for an experiment."""
        if self._derived_dir is not None:
            return self._derived_dir / "normalized" / exp_id
        return exp_dir.parent.parent / "derived" / "normalized" / exp_id

    def _load_experiment_summaries(self, experiment_dirs: list[Path]) -> list[dict]:
        """Load resistance_summary.json from each experiment's normalized output."""
        summaries: list[dict] = []
        for exp_dir in experiment_dirs:
            exp_id = _get_experiment_id(exp_dir)
            summary_path = self._normalized_dir(exp_dir, exp_id) / "resistance_summary.json"

            if not summary_path.exists():
                logger.warning("No processed summary for %s, skipping", exp_id)
                continue

            with open(summary_path) as f:
                summaries.append(json.load(f))

        return summaries

    def _build_summary_table(self, summaries: list[dict]) -> pd.DataFrame:
        """Build a DataFrame with one row per experiment."""
        columns = [
            "experiment_id",
            "cable_model",
            "measurement_method",
            "measurement_instrument",
            "temperature_c",
            "cable_length_mm",
            "num_measurements",
            "mean_resistance_ohm",
            "std_resistance_ohm",
            "min_resistance_ohm",
            "max_resistance_ohm",
            "median_resistance_ohm",
            "mean_resistance_per_m",
            "std_resistance_per_m",
        ]
        rows: list[dict] = []
        for s in summaries:
            row = {col: s.get(col) for col in columns}
            rows.append(row)

        return pd.DataFrame(rows, columns=columns)

    def _generate_boxplot(self, experiment_dirs: list[Path], output_path: Path) -> None:
        """Generate a boxplot of resistance_ohm distributions across experiments."""
        data: list[list[float]] = []
        labels: list[str] = []

        for exp_dir in experiment_dirs:
            exp_id = _get_experiment_id(exp_dir)
            csv_path = self._normalized_dir(exp_dir, exp_id) / "normalized_resistance.csv"

            if not csv_path.exists():
                continue

            df = pd.read_csv(csv_path)
            if "resistance_ohm" in df.columns:
                values = df["resistance_ohm"].dropna().tolist()
                if values:
                    data.append(values)
                    labels.append(exp_id)

        if not data:
            return

        fig, ax = plt.subplots(figsize=(max(6, len(data) * 1.5), 5))
        ax.boxplot(data, tick_labels=labels)
        ax.set_ylabel("Resistance (ohm)")
        ax.set_title("Resistance Distribution by Experiment")
        if len(labels) > 3:
            plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
