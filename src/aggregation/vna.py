from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.aggregation.base import BaseAggregator, SessionContext
from src.core.schemas import MeasurementDefinition


class VNASummary(BaseAggregator):
    """
    Aggregates processed VNA data across sessions.
    Produces a comparison table CSV and an overlay plot PNG.
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

        summaries = self.load_summaries(sessions, "vna")
        outputs: dict[str, Path] = {}

        if summaries:
            table_df = self._build_comparison_table(summaries)
            table_path = output_dir / "vna_comparison.csv"
            table_df.to_csv(table_path, index=False)
            outputs["vna_comparison_table"] = table_path

            # Attenuation vs frequency (the user-facing loss curve). Kept at
            # the historical filename/key so the wiki renderer and the type
            # definition continue to find it.
            atten_path = output_dir / "vna_comparison.png"
            if self._generate_overlay_plot(
                sessions,
                atten_path,
                column="attenuation_db",
                ylabel="Attenuation (dB)",
                title="Cable attenuation vs frequency",
            ):
                outputs["vna_overlay_plot"] = atten_path

            # Characteristic impedance vs frequency.
            imp_path = output_dir / "vna_impedance.png"
            if self._generate_overlay_plot(
                sessions,
                imp_path,
                column="impedance_ohm",
                ylabel="Characteristic impedance (ohm)",
                title="Characteristic impedance vs frequency",
            ):
                outputs["vna_impedance_plot"] = imp_path

        return outputs

    def _build_comparison_table(self, summaries: list[dict]) -> pd.DataFrame:
        columns = [
            "profile_id",
            "condition",
            "cable_length_mm",
            "session_id",
            "date",
            "operator",
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

    def _generate_overlay_plot(
        self,
        sessions: list[SessionContext],
        output_path: Path,
        column: str,
        ylabel: str,
        title: str,
    ) -> bool:
        """
        Overlay one trace column vs frequency across sessions.

        Returns True if a plot was written, False if no session had usable
        data for the requested column (so callers can skip the output).
        """
        fig, ax = plt.subplots(figsize=(10, 6))
        has_data = False

        for ctx in sessions:
            traces_path = ctx.derived_dir / "vna_traces.csv"

            if not traces_path.exists():
                continue

            df = pd.read_csv(traces_path)
            if "frequency_hz" not in df.columns or column not in df.columns:
                continue

            for filename, group in df.groupby("filename"):
                group = group.sort_values("frequency_hz").dropna(subset=[column])
                if group.empty:
                    continue
                label = f"{ctx.label}/{filename}"
                ax.plot(
                    group["frequency_hz"] / 1e6,
                    group[column],
                    label=label,
                    alpha=0.8,
                )
                has_data = True

        if not has_data:
            plt.close(fig)
            return False

        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(fontsize=7, loc="best")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        return True
