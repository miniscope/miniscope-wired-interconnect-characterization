from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.instruments.types import DEFAULT_LANES, MarginPoint, MarginSweep, SerdesLane
from src.processing.base import BaseProcessor, session_header
from src.processing.eye import extract_eye_opening, eye_figure, link_margin_metrics

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Every serdes session covers exactly these three lanes: the forward link at
# 3 and 6 Gbps plus the fixed low-rate reverse control channel.
EXPECTED_LANES = frozenset({"fwd_3g", "fwd_6g", "rev_187m"})
_LANE_BY_ID = {lane.lane_id: lane for lane in DEFAULT_LANES}

# Error-count ceiling for a lost-lock / unreachable margin step, used when
# averaging repeated sweeps so a dropped run doesn't dominate the mean. Matches
# the clamp the margin plot uses so averaged curves stay on the same scale.
_ERROR_CEILING = 256


def _read_iterations(mrow) -> int:
    """Margin-iteration count from a manifest row; 1 for legacy rows without it."""
    raw = mrow.get("margin_iterations")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 1
    try:
        return max(1, int(raw))
    except (ValueError, TypeError):
        return 1


def read_margin_sweep(csv_path: Path, lane: SerdesLane) -> MarginSweep:
    """Read one raw link-margin sweep CSV back into a MarginSweep."""
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    points = [
        MarginPoint(
            tx_amplitude_mv=float(row["tx_amp_mv"]),
            code=int(row["code"]),
            rep=int(row["rep"]),
            locked=bool(int(row["locked"])),
            errors=int(row["errors"]),
            status=str(row["status"]).strip(),
        )
        for _, row in df.iterrows()
    ]
    return MarginSweep(lane=lane, points=points)


def average_margin_sweeps(sweeps: list[MarginSweep]) -> MarginSweep:
    """Average several link-margin sweeps of one lane into one representative sweep.

    Every sweep walks the same deterministic TX-amplitude grid (shared
    start/step/stop), but a sweep that errors stops at its first failing step
    (``margin_continue_on_error`` off), so runs can be different lengths. We
    average the error count at each amplitude over ALL runs: a run that stopped
    *above* a given amplitude already failed at an easier step and would only be
    worse at the harder, lower amplitude, so it counts as a failure (errors at
    the ``_ERROR_CEILING``) there. Lost-lock steps (errors == -1) use the same
    ceiling. The averaged status is "ok" only where the mean rounds to zero --
    a deliberately conservative consensus, so any meaningful error in any run
    flips that step to "errors".

    A single populated run is returned as-is.
    """
    if not sweeps:
        raise ValueError("average_margin_sweeps requires at least one sweep")
    populated = [s for s in sweeps if s.points]
    if len(populated) <= 1:
        # Nothing to average: hand back the single populated sweep, or (if every
        # run came back empty) the first original sweep to preserve its lane.
        return populated[0] if populated else sweeps[0]

    lane = populated[0].lane
    by_amp = [{p.tx_amplitude_mv: p for p in s.points} for s in populated]
    reached_floor = [min(d) for d in by_amp]  # lowest amplitude each run measured
    amps = sorted({a for d in by_amp for a in d}, reverse=True)  # union, high -> low

    points: list[MarginPoint] = []
    for amp in amps:
        errs: list[float] = []
        sample: MarginPoint | None = None
        for d, floor in zip(by_amp, reached_floor, strict=True):
            point = d.get(amp)
            if point is not None:
                sample = sample or point
                errs.append(float(_ERROR_CEILING if point.errors < 0 else point.errors))
            elif amp < floor:
                # Run stopped above this amplitude -> treat the harder step as failed.
                errs.append(float(_ERROR_CEILING))
        avg_errors = round(sum(errs) / len(errs)) if errs else 0
        status = "ok" if avg_errors == 0 else "errors"
        points.append(
            MarginPoint(
                tx_amplitude_mv=amp,
                code=sample.code if sample else 0,
                rep=sample.rep if sample else 0,
                locked=avg_errors < _ERROR_CEILING,
                errors=avg_errors,
                status=status,
            )
        )
    return MarginSweep(lane=lane, points=points)


class ProcessSerdes(BaseProcessor):
    """
    Processes a GMSL2 SerDes characterization session.

    Reads session_manifest.csv and, for each lane, computes eye-opening metrics
    from the raw eye-monitor grid CSV and link-margin metrics from the raw
    TX-amplitude sweep CSV.

    Writes serdes_metrics.csv (one row per lane) + serdes_summary.json.
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

        manifest = pd.read_csv(session_dir / "session_manifest.csv")
        manifest.columns = manifest.columns.str.strip()

        rows: list[dict] = []
        for _, mrow in manifest.iterrows():
            lane_id = str(mrow["lane_id"]).strip()
            channel = str(mrow["channel"]).strip()
            rate_gbps = float(mrow["rate_gbps"])
            metrics: dict = {"lane_id": lane_id, "channel": channel, "rate_gbps": rate_gbps}

            eye_csv = str(mrow["eye_csv"]).strip()
            metrics["eye_csv"] = eye_csv
            metrics.update(self._eye_metrics(session_dir / eye_csv))

            eye_png = output_dir / f"{Path(eye_csv).stem}.png"
            self._render_eye_png(session_dir / eye_csv, channel, lane_id, eye_png)
            metrics["eye_png"] = eye_png.name

            margin_csv = str(mrow["margin_csv"]).strip()
            metrics["margin_csv"] = margin_csv
            iterations = _read_iterations(mrow)
            # Run 1 is margin_<lane>.csv; repeats append as margin_<lane>_run<i>.csv.
            run_paths = [session_dir / margin_csv] + [
                session_dir / f"margin_{lane_id}_run{i}.csv" for i in range(2, iterations + 1)
            ]
            metrics.update(self._margin_metrics(run_paths, lane_id))

            rows.append(metrics)

        metrics_df = pd.DataFrame(rows)
        metrics_path = output_dir / "serdes_metrics.csv"
        metrics_df.to_csv(metrics_path, index=False)

        summary = self._compute_summary(rows, session)
        summary_path = output_dir / "serdes_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        return {
            "serdes_metrics_csv": metrics_path,
            "serdes_summary_json": summary_path,
        }

    def _eye_metrics(self, eye_csv_path: Path) -> dict:
        """Eye-opening metrics for one lane's raw EOM grid."""
        df = pd.read_csv(eye_csv_path)
        df.columns = df.columns.str.strip()
        return extract_eye_opening(
            df["phase"].to_numpy(),
            df["vth"].to_numpy(),
            df["polarity"].to_numpy(),
            df["errors"].to_numpy(),
            df["hits"].to_numpy(),
        )

    def _render_eye_png(
        self, eye_csv_path: Path, channel: str, lane_id: str, output_path: Path
    ) -> None:
        df = pd.read_csv(eye_csv_path)
        df.columns = df.columns.str.strip()
        fig = eye_figure(
            df["phase"].to_numpy(),
            df["vth"].to_numpy(),
            df["polarity"].to_numpy(),
            df["errors"].to_numpy(),
            df["hits"].to_numpy(),
            channel,
            lane_id,
        )
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)

    def _margin_metrics(self, run_paths: list[Path], lane_id: str) -> dict:
        """Link-margin metrics for one lane, averaging repeated raw sweeps.

        A single-run session passes one path through ``average_margin_sweeps``
        unchanged; repeated runs are averaged here (the derivation), so the raw
        per-run CSVs stay the source of truth and ``derived/`` is regenerable.
        """
        lane = _LANE_BY_ID[lane_id]
        sweeps = [read_margin_sweep(p, lane) for p in run_paths]
        averaged = average_margin_sweeps(sweeps)
        metrics = link_margin_metrics(
            np.array([p.tx_amplitude_mv for p in averaged.points], dtype=float),
            np.array([p.errors for p in averaged.points], dtype=int),
        )
        metrics["num_margin_points"] = len(averaged.points)
        metrics["num_margin_runs"] = len(sweeps)
        return metrics

    def _compute_summary(self, rows: list[dict], session: SessionRecord) -> dict:
        summary: dict = {
            **session_header(session),
            "num_lanes": len(rows),
            "combos": [
                {
                    k: row.get(k)
                    for k in [
                        "lane_id",
                        "channel",
                        "rate_gbps",
                        "eye_area_ratio",
                        "zero_error_fraction",
                        "eye_height_mv",
                        "eye_width_ui",
                        "link_margin_mv",
                        "error_onset_mv",
                    ]
                }
                for row in rows
            ],
        }

        # Convenience: worst-case values across lanes (the binding constraint
        # for "will this cable work"). link_margin_mv is the lowest error-free
        # TX amplitude, so LOWER is better and the worst lane has the HIGHEST
        # floor.
        areas = [r["eye_area_ratio"] for r in rows if r.get("eye_area_ratio") is not None]
        margins = [r["link_margin_mv"] for r in rows if r.get("link_margin_mv") is not None]
        if areas:
            summary["worst_eye_area_ratio"] = min(areas)
        if margins:
            summary["worst_link_margin_mv"] = max(margins)

        type_fields = session.type_fields
        for key in ["serdes_device", "temperature_c"]:
            if key in type_fields:
                summary[key] = type_fields[key]

        return summary
