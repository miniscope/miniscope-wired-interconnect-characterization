"""Integration tests: full resistance characterization pipeline."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import aggregate_type, process_experiment


class TestResistancePipelineIntegration:
    """End-to-end test using the real example experiment."""

    @pytest.fixture
    def repo_root(self) -> Path:
        return Path(".")

    @pytest.fixture
    def example_experiment_dir(self, repo_root: Path) -> Path:
        return repo_root / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"

    def test_process_example_experiment(
        self, example_experiment_dir: Path, repo_root: Path, tmp_path: Path
    ):
        """Process the real example experiment end-to-end."""
        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        exp_dir = test_repo / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_experiment_dir.iterdir():
            (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        result = process_experiment(exp_dir, test_repo)

        assert result.validation.is_valid, f"Validation errors: {result.validation.errors}"
        assert result.error is None
        assert "normalized_resistance_csv" in result.outputs
        assert "resistance_summary_json" in result.outputs

        df = pd.read_csv(result.outputs["normalized_resistance_csv"])
        assert len(df) == 10
        assert "resistance_per_m" in df.columns

        with open(result.outputs["resistance_summary_json"]) as f:
            summary = json.load(f)
        assert summary["num_measurements"] == 10
        assert summary["cable_model"] == "coax_spi_sci_40awg"
        assert summary["cable_length_mm"] == 1000.0
        assert 2.0 < summary["mean_resistance_ohm"] < 3.0

    def test_aggregate_after_processing(
        self, example_experiment_dir: Path, repo_root: Path, tmp_path: Path
    ):
        """Process then aggregate the example experiment."""
        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        exp_dir = test_repo / "experiments" / "EXP_2025_01_15_resistance_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_experiment_dir.iterdir():
            (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        result = process_experiment(exp_dir, test_repo)
        assert result.error is None

        outputs = aggregate_type("resistance_characterization", test_repo)

        assert "resistance_summary_table" in outputs
        assert "resistance_boxplot" in outputs

        df = pd.read_csv(outputs["resistance_summary_table"])
        assert len(df) == 1
        assert df.iloc[0]["experiment_id"] == "EXP_2025_01_15_resistance_coax_40awg"

        assert outputs["resistance_boxplot"].stat().st_size > 0
