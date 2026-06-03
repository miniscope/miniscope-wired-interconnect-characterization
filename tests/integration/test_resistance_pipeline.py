"""Integration tests: full resistance characterization pipeline."""

import json
from pathlib import Path

import pandas as pd

from src.pipeline import aggregate_type, process_session


class TestResistancePipelineIntegration:
    """End-to-end test using the fixture measurement tree."""

    def test_process_session(self, test_repo: Path):
        session_dir = (
            test_repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250115_01"
        )

        result = process_session(session_dir, test_repo)

        assert result.validation.is_valid, f"Validation errors: {result.validation.errors}"
        assert result.error is None
        assert "normalized_resistance_csv" in result.outputs
        assert "resistance_summary_json" in result.outputs

        df = pd.read_csv(result.outputs["normalized_resistance_csv"])
        assert len(df) == 4
        assert "roundtrip_resistance_ohm_per_m" in df.columns

        with open(result.outputs["resistance_summary_json"]) as f:
            summary = json.load(f)
        assert summary["num_measurements"] == 4
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 500.0
        # ~1.2 ohm over 0.5 m -> ~2.4 ohm/m round trip
        assert 2.0 < summary["mean_roundtrip_resistance_ohm_per_m"] < 3.0

    def test_aggregate_after_processing(self, test_repo: Path):
        """Process both resistance sessions then aggregate them."""
        base = test_repo / "measurements" / "test_cable" / "500mm" / "resistance"
        for session_id in ["20250115_01", "20250116_01"]:
            result = process_session(base / session_id, test_repo)
            assert result.error is None

        outputs = aggregate_type("resistance", test_repo)

        assert "resistance_summary_table" in outputs
        assert "resistance_boxplot" in outputs

        df = pd.read_csv(outputs["resistance_summary_table"])
        assert len(df) == 2
        assert set(df["session_id"]) == {"20250115_01", "20250116_01"}
        assert (df["profile_id"] == "test_cable").all()

        assert outputs["resistance_boxplot"].stat().st_size > 0
