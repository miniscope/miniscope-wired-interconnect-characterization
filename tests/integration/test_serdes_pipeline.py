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
        assert len(df) == 4  # 2 channels x 2 rates

        with open(result.outputs["serdes_summary_json"]) as f:
            summary = json.load(f)
        assert summary["profile_id"] == "test_cable"
        assert summary["num_combos"] == 4

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
        assert len(df) == 8  # 2 sessions x 4 combos
