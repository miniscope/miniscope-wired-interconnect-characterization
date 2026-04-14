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


class EyeDiagramSummary(BaseAggregator):
    """
    Aggregates processed eye diagram data across experiments.
    Produces a comparison table CSV and a scatter plot PNG.
    """

    def __init__(self, derived_dir: Path | None = None) -> None:
        self._derived_dir = derived_dir

    @property
    def name(self) -> str:
        return "eye_diagram_summary"

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
            table_df = self._build_comparison_table(summaries)
            table_path = output_dir / "eye_diagram_comparison.csv"
            table_df.to_csv(table_path, index=False)
            outputs["eye_diagram_comparison_table"] = table_path

            plot_path = output_dir / "eye_diagram_comparison.png"
            self._generate_plot(experiment_dirs, plot_path)
            outputs["eye_diagram_comparison_plot"] = plot_path

        return outputs

    def _normalized_dir(self, exp_dir: Path, exp_id: str) -> Path:
        if self._derived_dir is not None:
            return self._derived_dir / "normalized" / exp_id
        return exp_dir.parent.parent / "derived" / "normalized" / exp_id

    def _load_experiment_summaries(self, experiment_dirs: list[Path]) -> list[dict]:
        summaries: list[dict] = []
        for exp_dir in experiment_dirs:
            exp_id = _get_experiment_id(exp_dir)
            summary_path = self._normalized_dir(exp_dir, exp_id) / "eye_summary.json"

            if not summary_path.exists():
                logger.warning("No processed eye summary for %s, skipping", exp_id)
                continue

            with open(summary_path) as f:
                summaries.append(json.load(f))

        return summaries

    def _build_comparison_table(self, summaries: list[dict]) -> pd.DataFrame:
        columns = [
            "experiment_id",
            "cable_model",
            "oscilloscope",
            "signal_type",
            "data_rate_mbps",
            "num_files",
            "num_measurements",
            "mean_eye_height_ratio",
            "min_eye_height_ratio",
            "max_eye_height_ratio",
            "mean_eye_width_ratio",
            "mean_eye_area_ratio",
        ]
        rows: list[dict] = []
        for s in summaries:
            row = {col: s.get(col) for col in columns}
            rows.append(row)

        return pd.DataFrame(rows, columns=columns)

    def _generate_plot(self, experiment_dirs: list[Path], output_path: Path) -> None:
        """Scatter plot of mean eye_area_ratio vs cable_length for each experiment."""
        exp_ids: list[str] = []
        area_ratios: list[float] = []

        for exp_dir in experiment_dirs:
            exp_id = _get_experiment_id(exp_dir)
            metrics_path = self._normalized_dir(exp_dir, exp_id) / "eye_metrics.csv"

            if not metrics_path.exists():
                continue

            df = pd.read_csv(metrics_path)
            if "eye_area_ratio" in df.columns:
                mean_area = df["eye_area_ratio"].dropna().mean()
                if pd.notna(mean_area):
                    exp_ids.append(exp_id)
                    area_ratios.append(float(mean_area))

        if not exp_ids:
            return

        fig, ax = plt.subplots(figsize=(max(6, len(exp_ids) * 1.5), 5))
        ax.bar(range(len(exp_ids)), area_ratios, tick_label=exp_ids)
        ax.set_ylabel("Mean Eye Area Ratio")
        ax.set_title("Eye Opening Comparison by Experiment")
        if len(exp_ids) > 3:
            plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
