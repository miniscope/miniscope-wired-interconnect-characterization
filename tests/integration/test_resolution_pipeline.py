"""Integration tests: resolution manifests generated during pipeline processing."""

import json
from pathlib import Path

from src.pipeline import process_experiment


class TestResolutionPipelineIntegration:
    def test_manifest_written_on_process(self, tmp_path: Path):
        """Processing an experiment should write a resolution manifest."""
        repo_root = Path(".")
        example_dir = repo_root / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"

        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        exp_dir = test_repo / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_dir.iterdir():
            if f.is_file():
                (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        result = process_experiment(exp_dir, test_repo)
        assert result.error is None

        manifest_path = (
            test_repo
            / "derived"
            / "manifests"
            / "EXP_2025_01_15_resistance_coax_40awg"
            / "resolution_manifest.json"
        )
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["experiment_id"] == "EXP_2025_01_15_resistance_coax_40awg"
        assert "models" in manifest
        assert "cable_model" in manifest["models"]

        cable = manifest["models"]["cable_model"]
        assert cable["resolved"] is True
        assert cable["source"] == "repo"
        assert cable["model_id"] == "coax_spi_sci_40awg"

    def test_manifest_records_unresolved_optional(self, tmp_path: Path):
        """Optional model refs not provided should appear as unresolved."""
        repo_root = Path(".")
        example_dir = repo_root / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"

        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        exp_dir = test_repo / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_dir.iterdir():
            if f.is_file():
                (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        result = process_experiment(exp_dir, test_repo)
        assert result.error is None

        manifest_path = (
            test_repo
            / "derived"
            / "manifests"
            / "EXP_2025_01_15_resistance_coax_40awg"
            / "resolution_manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        # connector_model is optional and not provided in the example
        connector = manifest["models"]["connector_model"]
        assert connector["resolved"] is False
        assert "not provided" in connector["reason"]
