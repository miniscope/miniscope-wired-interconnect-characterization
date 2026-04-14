"""Integration test: full pipeline end-to-end."""

import json
from pathlib import Path

from src.pipeline import run_full_pipeline


class TestFullPipeline:
    def test_run_full_pipeline(self, tmp_path: Path):
        """Run the complete pipeline on all example experiments."""
        repo_root = Path(".")

        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        # Copy all experiments
        src_experiments = repo_root / "experiments"
        dst_experiments = test_repo / "experiments"
        dst_experiments.mkdir()

        for exp_dir in src_experiments.iterdir():
            if not exp_dir.is_dir() or exp_dir.name.startswith("."):
                continue
            dst_exp = dst_experiments / exp_dir.name
            dst_exp.mkdir()
            for f in exp_dir.iterdir():
                if f.is_dir():
                    raw_dir = dst_exp / f.name
                    raw_dir.mkdir()
                    for rf in f.iterdir():
                        (raw_dir / rf.name).write_bytes(rf.read_bytes())
                else:
                    (dst_exp / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        summary = run_full_pipeline(test_repo)

        # Should have processed 3 experiments
        assert len(summary["processed"]) == 3
        for p in summary["processed"]:
            assert p["valid"], f"{p['experiment_id']} failed validation"
            assert p["error"] is None, f"{p['experiment_id']} had error: {p['error']}"

        # Should have aggregated 3 types
        assert len(summary["aggregated"]) == 3
        assert "resistance_characterization" in summary["aggregated"]
        assert "eye_diagram_characterization" in summary["aggregated"]
        assert "vna_characterization" in summary["aggregated"]

        # Should have generated wiki payload for coax_spi_sci_40awg
        assert "coax_spi_sci_40awg" in summary["wiki_payloads"]

        # Verify wiki payload file exists and is valid JSON
        payload_path = Path(summary["wiki_payloads"]["coax_spi_sci_40awg"])
        assert payload_path.exists()
        with open(payload_path) as f:
            payload = json.load(f)
        assert payload["model_id"] == "coax_spi_sci_40awg"
        # All 3 experiment types reference this cable model
        assert len(payload["characterization"]["resistance"]) >= 1
        assert len(payload["characterization"]["eye_diagram"]) >= 1
        assert len(payload["characterization"]["vna"]) >= 1
