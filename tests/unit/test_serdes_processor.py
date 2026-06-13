"""Tests for ProcessSerdes processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.serdes import ProcessSerdes


@pytest.fixture
def serdes_session_dir(measurements_fixtures_dir: Path) -> Path:
    return measurements_fixtures_dir / "test_cable" / "500mm" / "serdes" / "20250401_01"


class TestProcessSerdes:
    @pytest.fixture
    def processor(self) -> ProcessSerdes:
        return ProcessSerdes()

    @pytest.fixture
    def definition(self):
        return load_definition(Path("measurement_types/serdes/v1/definition.yaml"))

    def test_process_valid(self, processor, definition, serdes_session_dir: Path, tmp_path: Path):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        assert "serdes_metrics_csv" in outputs
        assert "serdes_summary_json" in outputs
        assert outputs["serdes_metrics_csv"].exists()
        assert outputs["serdes_summary_json"].exists()

    def test_metrics_csv_has_all_lanes(
        self, processor, definition, serdes_session_dir: Path, tmp_path: Path
    ):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["serdes_metrics_csv"])
        assert len(df) == 3
        assert set(df["lane_id"]) == {"fwd_3g", "fwd_6g", "rev_187m"}

    def test_metrics_columns(self, processor, definition, serdes_session_dir: Path, tmp_path: Path):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["serdes_metrics_csv"])
        for col in [
            "lane_id",
            "channel",
            "rate_gbps",
            "eye_area_ratio",
            "zero_error_fraction",
            "eye_height_mv",
            "eye_width_ui",
            "link_margin_mv",
            "error_onset_mv",
            "num_margin_points",
        ]:
            assert col in df.columns

        # Synthetic fixtures have an open eye and a clear error onset
        assert (df["eye_area_ratio"] > 0).all()
        assert df["link_margin_mv"].notna().all()

    def test_higher_rate_has_smaller_eye(
        self, processor, definition, serdes_session_dir: Path, tmp_path: Path
    ):
        """Fixture generator makes 6 Gbps eyes smaller than 3 Gbps eyes."""
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["serdes_metrics_csv"]).set_index("lane_id")
        assert df.loc["fwd_6g", "eye_area_ratio"] < df.loc["fwd_3g", "eye_area_ratio"]

    def test_summary_json(self, processor, definition, serdes_session_dir: Path, tmp_path: Path):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        with open(outputs["serdes_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250401_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 500.0
        assert summary["num_lanes"] == 3
        assert len(summary["combos"]) == 3
        assert "worst_eye_area_ratio" in summary
        assert "worst_link_margin_mv" in summary
        assert summary["serdes_device"] == "Test GMSL2 eval kit"


class TestAverageMarginSweeps:
    def _sweep(self, lane, points):
        from src.instruments.types import MarginPoint, MarginSweep

        return MarginSweep(
            lane, [MarginPoint(a, int(a // 10), 0, e == 0, e, s) for a, e, s in points]
        )

    def test_single_run_returned_unchanged(self):
        from src.instruments.types import FORWARD_3G
        from src.processing.serdes import average_margin_sweeps

        sweep = self._sweep(FORWARD_3G, [(400.0, 0, "ok"), (390.0, 5, "errors")])
        assert average_margin_sweeps([sweep]) is sweep

    def test_averages_errors_and_penalizes_early_stop(self):
        """Different-length runs: a run that stopped above an amplitude counts as
        failed (error ceiling) at that harder, lower step."""
        from src.instruments.types import FORWARD_3G
        from src.processing.serdes import _ERROR_CEILING, average_margin_sweeps

        run_a = self._sweep(  # stopped at 390 (errored)
            FORWARD_3G, [(410.0, 0, "ok"), (400.0, 0, "ok"), (390.0, 4, "errors")]
        )
        run_b = self._sweep(  # reached 380 before erroring
            FORWARD_3G,
            [(410.0, 0, "ok"), (400.0, 0, "ok"), (390.0, 0, "ok"), (380.0, 10, "errors")],
        )

        avg = average_margin_sweeps([run_a, run_b])
        by_amp = {p.tx_amplitude_mv: p for p in avg.points}

        assert sorted(by_amp, reverse=True) == [410.0, 400.0, 390.0, 380.0]
        assert by_amp[410.0].errors == 0 and by_amp[410.0].status == "ok"
        assert by_amp[390.0].errors == 2 and by_amp[390.0].status == "errors"  # mean(4, 0)
        # 380 mV: run A stopped above it -> failure ceiling; mean(256, 10) -> 133.
        assert by_amp[380.0].errors == round((_ERROR_CEILING + 10) / 2)
        assert by_amp[380.0].status == "errors"

    def test_lost_lock_clamped_to_ceiling(self):
        from src.instruments.types import REVERSE_187M
        from src.processing.serdes import _ERROR_CEILING, average_margin_sweeps

        run_a = self._sweep(REVERSE_187M, [(250.0, 0, "ok"), (240.0, -1, "lost_lock")])
        run_b = self._sweep(REVERSE_187M, [(250.0, 0, "ok"), (240.0, 0, "ok")])

        avg = average_margin_sweeps([run_a, run_b])
        by_amp = {p.tx_amplitude_mv: p for p in avg.points}
        assert by_amp[240.0].errors == round(_ERROR_CEILING / 2)  # mean(256, 0)

    def test_empty_raises(self):
        from src.processing.serdes import average_margin_sweeps

        with pytest.raises(ValueError):
            average_margin_sweeps([])


class TestMarginReadAndMetrics:
    def _write_margin(self, path: Path, rows):
        import csv

        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["tx_amp_mv", "code", "rep", "locked", "errors", "status"])
            for a, e, s in rows:
                w.writerow([a, int(a // 10), 0, int(e == 0), e, s])

    def test_read_margin_sweep_roundtrip(self, tmp_path: Path):
        from src.instruments.types import FORWARD_6G
        from src.processing.serdes import read_margin_sweep

        p = tmp_path / "margin_fwd_6g.csv"
        self._write_margin(p, [(400.0, 0, "ok"), (390.0, 5, "errors")])
        sweep = read_margin_sweep(p, FORWARD_6G)

        assert sweep.lane is FORWARD_6G
        assert [pt.tx_amplitude_mv for pt in sweep.points] == [400.0, 390.0]
        assert sweep.points[1].status == "errors" and sweep.points[1].errors == 5

    def test_margin_metrics_averages_multiple_runs(self, tmp_path: Path):
        run1 = tmp_path / "margin_fwd_6g.csv"
        run2 = tmp_path / "margin_fwd_6g_run2.csv"
        self._write_margin(run1, [(400.0, 0, "ok"), (390.0, 0, "ok"), (380.0, 8, "errors")])
        self._write_margin(run2, [(400.0, 0, "ok"), (390.0, 6, "errors")])

        metrics = ProcessSerdes()._margin_metrics([run1, run2], "fwd_6g")
        assert metrics["num_margin_runs"] == 2
        assert metrics["num_margin_points"] >= 3
        assert "link_margin_mv" in metrics

    def test_margin_metrics_single_run(self, tmp_path: Path):
        run1 = tmp_path / "margin_rev_187m.csv"
        self._write_margin(run1, [(250.0, 0, "ok"), (240.0, 4, "errors")])

        metrics = ProcessSerdes()._margin_metrics([run1], "rev_187m")
        assert metrics["num_margin_runs"] == 1
