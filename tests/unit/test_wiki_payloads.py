"""Tests for wiki payload generation."""

import json
from pathlib import Path

from src.wiki.payloads import generate_wiki_payloads


class TestGenerateWikiPayloads:
    def _setup_repo(self, tmp_path: Path) -> Path:
        """Create a minimal repo structure with a processed experiment."""
        repo_root = Path(".")
        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        example_dir = repo_root / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"
        exp_dir = test_repo / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_dir.iterdir():
            if f.is_file():
                (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived" / "wiki_payloads").mkdir(parents=True)

        # Process the experiment first
        from src.pipeline import process_experiment

        (test_repo / "derived" / "manifests").mkdir(parents=True, exist_ok=True)
        process_experiment(exp_dir, test_repo)

        return test_repo

    def test_generates_payload_for_referenced_model(self, tmp_path: Path):
        test_repo = self._setup_repo(tmp_path)
        outputs = generate_wiki_payloads(test_repo)

        assert "coax_spi_sci_40awg" in outputs
        assert outputs["coax_spi_sci_40awg"].exists()

    def test_payload_contains_model_metadata(self, tmp_path: Path):
        test_repo = self._setup_repo(tmp_path)
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["coax_spi_sci_40awg"]) as f:
            payload = json.load(f)

        assert payload["model_id"] == "coax_spi_sci_40awg"
        assert payload["model_metadata"] is not None
        assert payload["model_metadata"]["model_id"] == "coax_spi_sci_40awg"

    def test_payload_contains_characterization_data(self, tmp_path: Path):
        test_repo = self._setup_repo(tmp_path)
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["coax_spi_sci_40awg"]) as f:
            payload = json.load(f)

        assert len(payload["characterization"]["resistance"]) >= 1
        exp_entry = payload["characterization"]["resistance"][0]
        assert exp_entry["experiment_id"] == "EXP_2025_01_15_resistance_coax_40awg"
        assert exp_entry["summary"] is not None

    def test_payload_has_generated_at(self, tmp_path: Path):
        test_repo = self._setup_repo(tmp_path)
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["coax_spi_sci_40awg"]) as f:
            payload = json.load(f)

        assert "generated_at" in payload

    def test_no_experiments_no_payloads(self, tmp_path: Path):
        test_repo = tmp_path / "empty_repo"
        (test_repo / "experiments").mkdir(parents=True)
        (test_repo / "models" / "cable_models").mkdir(parents=True)
        (test_repo / "derived" / "wiki_payloads").mkdir(parents=True)

        outputs = generate_wiki_payloads(test_repo)
        assert outputs == {}
