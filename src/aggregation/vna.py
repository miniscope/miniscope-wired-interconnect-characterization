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
    yaml_path = exp_dir / "experiment.yaml"
    if yaml_path.exists():
        try:
            return load_experiment(yaml_path).experiment_id
        except Exception:
            pass
    return exp_dir.name


class VNASummary(BaseAggregator):
    """
    Aggregates processed VNA data across experiments.
    Produces a comparison table CSV and an overlay plot PNG.
    """

    def __init__(self, derived_dir: Path | None = None) -> None:
        self._derived_dir = derived_dir

    @property
    def name(self) -> str:
        return "vna_summary"

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
            table_path = output_dir / "vna_comparison.csv"
            table_df.to_csv(table_path, index=False)
            outputs["vna_comparison_table"] = table_path

            plot_path = output_dir / "vna_comparison.png"
            self._generate_overlay_plot(experiment_dirs, plot_path)
            outputs["vna_overlay_plot"] = plot_path

        return outputs

    def _normalized_dir(self, exp_dir: Path, exp_id: str) -> Path:
        if self._derived_dir is not None:
            return self._derived_dir / "normalized" / exp_id
        return exp_dir.parent.parent / "derived" / "normalized" / exp_id

    def _load_experiment_summaries(self, experiment_dirs: list[Path]) -> list[dict]:
        summaries: list[dict] = []
        for exp_dir in experiment_dirs:
            exp_id = _get_experiment_id(exp_dir)
            summary_path = self._normalized_dir(exp_dir, exp_id) / "vna_summary.json"

            if not summary_path.exists():
                logger.warning("No processed VNA summary for %s, skipping", exp_id)
                continue

            with open(summary_path) as f:
                summaries.append(json.load(f))

        return summaries

    def _build_comparison_table(self, summaries: list[dict]) -> pd.DataFrame:
        columns = [
            "experiment_id",
            "cable_model",
            "vna_instrument",
            "calibration_type",
            "num_files",
            "mean_max_insertion_loss_db",
            "worst_max_insertion_loss_db",
            "mean_min_return_loss_db",
        ]
        rows: list[dict] = []
        for s in summaries:
            row = {col: s.get(col) for col in columns}
            rows.append(row)

        return pd.DataFrame(rows, columns=columns)

    def _generate_overlay_plot(self, experiment_dirs: list[Path], output_path: Path) -> None:
        """Overlay plot of insertion loss (S21) vs frequency across experiments."""
        fig, ax = plt.subplots(figsize=(10, 6))
        has_data = False

        for exp_dir in experiment_dirs:
            exp_id = _get_experiment_id(exp_dir)
            traces_path = self._normalized_dir(exp_dir, exp_id) / "vna_traces.csv"

            if not traces_path.exists():
                continue

            df = pd.read_csv(traces_path)
            if "frequency_hz" not in df.columns or "s21_db" not in df.columns:
                continue

            for filename, group in df.groupby("filename"):
                group = group.sort_values("frequency_hz")
                label = f"{exp_id}/{filename}"
                ax.plot(
                    group["frequency_hz"] / 1e6,
                    group["s21_db"],
                    label=label,
                    alpha=0.8,
                )
                has_data = True

        if not has_data:
            plt.close(fig)
            return

        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("S21 (dB)")
        ax.set_title("Insertion Loss Comparison")
        ax.legend(fontsize=7, loc="lower left")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
