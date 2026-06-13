"""Integration tests: full SerDes characterization pipeline."""

import json
from pathlib import Path

import pandas as pd

from src.pipeline import aggregate_type, process_session
from tests.conftest import build_test_repo


class TestSerdesPipelineIntegration:
    """End-to-end test using the fixture measurement tree."""

    def test_process_session(self, test_repo: Path):
        session_dir = test_repo / "measurements" / "test_cable" / "500mm" / "serdes" / "20250401_01"

        result = process_session(session_dir, test_repo)

        assert result.validation.is_valid, f"Validation errors: {result.validation.errors}"
        assert result.error is None
        assert "serdes_metrics_csv" in result.outputs
        assert "serdes_summary_json" in result.outputs

        df = pd.read_csv(result.outputs["serdes_metrics_csv"])
        assert len(df) == 3  # fwd_3g, fwd_6g, rev_187m

        with open(result.outputs["serdes_summary_json"]) as f:
            summary = json.load(f)
        assert summary["profile_id"] == "test_cable"
        assert summary["num_lanes"] == 3

    def test_invalid_serdes_sessions_fail(self, tmp_path: Path):
        repo = build_test_repo(tmp_path, bad_measurements=True)
        base = repo / "measurements" / "test_cable" / "500mm" / "serdes"

        for session_id in ["20250403_01", "20250404_01", "20250405_01"]:
            result = process_session(base / session_id, repo)
            assert not result.validation.is_valid, f"{session_id} should fail validation"
            assert result.outputs == {}

    def test_aggregate_after_processing(self, test_repo: Path):
        for length, session_id in [("500mm", "20250401_01"), ("1000mm", "20250402_01")]:
            session_dir = test_repo / "measurements" / "test_cable" / length / "serdes" / session_id
            result = process_session(session_dir, test_repo)
            assert result.error is None

        outputs = aggregate_type("serdes", test_repo)

        assert "serdes_metrics_table" in outputs
        assert "serdes_eye_vs_length_plot" in outputs
        assert "serdes_margin_vs_length_plot" in outputs

        df = pd.read_csv(outputs["serdes_metrics_table"])
        assert len(df) == 6  # 2 sessions x 3 lanes

    def test_multi_run_margin_round_trip(self, tmp_path: Path):
        """Repeated margin sweeps persist raw per run and re-derive the average."""
        from datetime import date

        from src.core.session_writer import SessionMeta, write_serdes_session
        from src.instruments.serdes.driver import SerdesConfig
        from src.instruments.serdes.simulator import SimulatedSerdesDriver

        repo = build_test_repo(tmp_path)
        driver = SimulatedSerdesDriver(cable_length_mm=500.0, seed=11)
        driver.connect()
        result = driver.run_full_sequence(config=SerdesConfig(eye_bins=16, margin_iterations=2))

        meta = SessionMeta(
            operator="tester",
            date=date(2025, 4, 9),
            notes="multi-run",
            type_fields={"serdes_device": "Test GMSL2 eval kit"},
        )
        # write_serdes_session validates with the exact CI rules before returning.
        ref = write_serdes_session(repo, "test_cable", 500.0, result, meta)

        # Raw per-run files persisted; run 1 keeps the plain margin_<lane>.csv name.
        assert (ref.path / "margin_fwd_6g.csv").exists()
        assert (ref.path / "margin_fwd_6g_run2.csv").exists()
        manifest = pd.read_csv(ref.path / "session_manifest.csv")
        assert (manifest["margin_iterations"] == 2).all()

        # Processing re-derives the average from the raw runs and reports the count.
        processed = process_session(ref.path, repo)
        assert processed.validation.is_valid, processed.validation.errors
        metrics = pd.read_csv(processed.outputs["serdes_metrics_csv"])
        assert (metrics["num_margin_runs"] == 2).all()
