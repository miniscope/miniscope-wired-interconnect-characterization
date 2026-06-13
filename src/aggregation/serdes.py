from __future__ import annotations

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.aggregation.base import BaseAggregator, SessionContext
from src.core.schemas import MeasurementDefinition
from src.instruments.types import rate_label


class SerdesSummary(BaseAggregator):
    """
    Aggregates processed SerDes data across sessions.

    Produces a per-combo metrics table CSV plus eye-opening-vs-length and
    link-margin-vs-length plots, faceted by data rate with one line per
    (profile, channel).
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

        table_df = self._build_combo_table(sessions)
        outputs: dict[str, Path] = {}

        if not table_df.empty:
            table_path = output_dir / "serdes_metrics.csv"
            table_df.to_csv(table_path, index=False)
            outputs["serdes_metrics_table"] = table_path

            eye_plot_path = output_dir / "serdes_eye_vs_length.png"
            self._plot_metric_vs_length(
                table_df,
                "eye_area_ratio",
                "Eye area ratio",
                eye_plot_path,
            )
            if eye_plot_path.exists():
                outputs["serdes_eye_vs_length_plot"] = eye_plot_path

            margin_plot_path = output_dir / "serdes_margin_vs_length.png"
            self._plot_metric_vs_length(
                table_df,
                "link_margin_mv",
                "Link margin floor (mV, lower is better)",
                margin_plot_path,
            )
            if margin_plot_path.exists():
                outputs["serdes_margin_vs_length_plot"] = margin_plot_path

        return outputs

    def _build_combo_table(self, sessions: list[SessionContext]) -> pd.DataFrame:
        """One row per (session, channel, rate) from each serdes_summary.json."""
        rows: list[dict] = []
        for summary in self.load_summaries(sessions, "serdes"):
            for combo in summary.get("combos", []):
                rows.append(
                    {
                        "profile_id": summary.get("profile_id"),
                        "condition": summary.get("condition"),
                        "cable_length_mm": summary.get("cable_length_mm"),
                        "session_id": summary.get("session_id"),
                        "date": summary.get("date"),
                        "operator": summary.get("operator"),
                        **combo,
                    }
                )

        return pd.DataFrame(rows)

    def _plot_metric_vs_length(
        self,
        df: pd.DataFrame,
        metric: str,
        ylabel: str,
        output_path: Path,
    ) -> None:
        """Plot a combo metric vs cable length, one subplot per rate."""
        if metric not in df.columns or df[metric].isna().all():
            return

        # Vs-length plots only make sense for length conditions; commutator
        # (no-length) sessions surface on their own page instead.
        df = df[df["cable_length_mm"].notna()]
        if df.empty:
            return

        rates = sorted(df["rate_gbps"].dropna().unique())
        if not rates:
            return

        fig, axes = plt.subplots(1, len(rates), figsize=(6 * len(rates), 5), squeeze=False)

        has_data = False
        for ax, rate in zip(axes[0], rates, strict=False):
            rate_df = df[df["rate_gbps"] == rate]
            for (profile_id, channel), group in rate_df.groupby(["profile_id", "channel"]):
                group = group.sort_values("cable_length_mm")
                values = group[metric].dropna()
                if values.empty:
                    continue
                ax.plot(
                    group["cable_length_mm"],
                    group[metric],
                    marker="o",
                    label=f"{profile_id} ({channel})",
                )
                has_data = True

            ax.set_title(rate_label(rate))
            ax.set_xlabel("Cable length (mm)")
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)

        if not has_data:
            plt.close(fig)
            return

        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
