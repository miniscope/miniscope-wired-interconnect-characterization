"""Integration tests: full VNA characterization pipeline."""

import json
from pathlib import Path

import pandas as pd

from src.pipeline import aggregate_type, process_session


class TestVNAPipelineIntegration:
    """End-to-end test using the fixture measurement tree."""

    def test_process_session(self, test_repo: Path):
        session_dir = test_repo / "measurements" / "test_cable" / "1000mm" / "vna" / "20250301_01"

        result = process_session(session_dir, test_repo)

        assert result.validation.is_valid, f"Validation errors: {result.validation.errors}"
        assert result.error is None
        assert "vna_metrics_csv" in result.outputs
        assert "vna_traces_csv" in result.outputs
        assert "vna_summary_json" in result.outputs

        df = pd.read_csv(result.outputs["vna_metrics_csv"])
        assert len(df) == 2  # 2 .s2p files

        traces = pd.read_csv(result.outputs["vna_traces_csv"])
        assert len(traces) == 2 * 101  # 2 files * 101 points

        with open(result.outputs["vna_summary_json"]) as f:
            summary = json.load(f)
        assert summary["num_files"] == 2
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 1000.0

    def test_aggregate_after_processing(self, test_repo: Path):
        base = test_repo / "measurements" / "test_cable" / "1000mm" / "vna"
        for session_id in ["20250301_01", "20250302_01"]:
            result = process_session(base / session_id, test_repo)
            assert result.error is None

        outputs = aggregate_type("vna", test_repo)

        assert "vna_comparison_table" in outputs
        assert "vna_overlay_plot" in outputs

        df = pd.read_csv(outputs["vna_comparison_table"])
        assert len(df) == 2
        assert set(df["session_id"]) == {"20250301_01", "20250302_01"}
