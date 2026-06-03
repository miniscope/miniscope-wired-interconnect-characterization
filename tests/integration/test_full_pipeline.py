"""Integration test: full pipeline end-to-end."""

import json
from pathlib import Path

from src.pipeline import run_full_pipeline


class TestFullPipeline:
    def test_run_full_pipeline(self, test_repo: Path):
        """Run the complete pipeline on the fixture measurement tree."""
        summary = run_full_pipeline(test_repo)

        # Should have processed 6 sessions (2 resistance + 2 serdes + 2 vna)
        assert len(summary["processed"]) == 6
        for p in summary["processed"]:
            assert p["valid"], f"{p['session_ref']} failed validation"
            assert p["error"] is None, f"{p['session_ref']} had error: {p['error']}"

        # Should have aggregated all three measurement types
        for type_name in ["resistance", "serdes", "vna"]:
            assert type_name in summary["aggregated"]
            assert "error" not in summary["aggregated"][type_name]

        # Should have generated a wiki payload per profile
        assert "test_cable" in summary["wiki_payloads"]

        payload_path = Path(summary["wiki_payloads"]["test_cable"])
        assert payload_path.exists()
        with open(payload_path) as f:
            payload = json.load(f)
        assert payload["profile_id"] == "test_cable"
        assert len(payload["characterization"]["resistance"]) == 2
        assert len(payload["characterization"]["serdes"]) == 2
        assert len(payload["characterization"]["vna"]) == 2
        for entries in payload["characterization"].values():
            for entry in entries:
                assert entry["summary"] is not None

    def test_derived_tree_layout(self, test_repo: Path):
        """Derived outputs mirror the measurements/ tree under derived/sessions/."""
        run_full_pipeline(test_repo)

        derived_sessions = test_repo / "derived" / "sessions" / "test_cable"
        assert (
            derived_sessions / "500mm" / "resistance" / "20250115_01" / "resistance_summary.json"
        ).exists()
        assert (
            derived_sessions / "500mm" / "serdes" / "20250401_01" / "serdes_summary.json"
        ).exists()
        assert (derived_sessions / "1000mm" / "vna" / "20250301_01" / "vna_summary.json").exists()

        aggregated = test_repo / "derived" / "aggregated"
        assert (aggregated / "resistance" / "resistance_summary.csv").exists()
        assert (aggregated / "serdes" / "serdes_metrics.csv").exists()
        assert (aggregated / "vna" / "vna_comparison.csv").exists()
