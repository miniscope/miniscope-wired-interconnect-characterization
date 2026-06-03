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

        # Should have consolidated per-profile metrics
        assert "test_cable_consolidated_json" in summary["consolidated"]

        # Should have run cross-cutting analysis
        assert "quality_scores" in summary["cross"]
        assert "resistivity_summary" in summary["cross"]
        assert "supply_voltage_table" in summary["cross"]

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

    def test_stale_derived_outputs_pruned(self, test_repo: Path):
        """Outputs for sessions/profiles that no longer exist are removed."""
        ghost = test_repo / "derived" / "sessions" / "ghost_cable" / "500mm" / "resistance" / "x"
        ghost.mkdir(parents=True)
        (ghost / "resistance_summary.json").write_text("{}")
        ghost_profile = test_repo / "derived" / "profiles" / "ghost_cable"
        ghost_profile.mkdir(parents=True)
        (ghost_profile / "consolidated.json").write_text("{}")

        run_full_pipeline(test_repo)

        assert not (test_repo / "derived" / "sessions" / "ghost_cable").exists()
        assert not ghost_profile.exists()
        # Real outputs regenerated as usual
        assert (test_repo / "derived" / "profiles" / "test_cable" / "consolidated.json").exists()

    def test_clean_false_preserves_existing(self, test_repo: Path):
        """clean=False keeps unrelated derived files (incremental mode)."""
        keeper = test_repo / "derived" / "sessions" / "keep.txt"
        keeper.parent.mkdir(parents=True, exist_ok=True)
        keeper.write_text("keep me")

        run_full_pipeline(test_repo, clean=False)

        assert keeper.exists()

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

        profile_dir = test_repo / "derived" / "profiles" / "test_cable"
        assert (profile_dir / "consolidated.json").exists()
        assert (profile_dir / "resistance_by_length.csv").exists()
        assert (profile_dir / "serdes_by_length.csv").exists()
        assert (profile_dir / "vna_by_length.csv").exists()
