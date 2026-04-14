"""Integration tests: full eye diagram characterization pipeline."""

import json
from pathlib import Path

import pandas as pd

from src.pipeline import aggregate_type, process_experiment


class TestEyePipelineIntegration:
    """End-to-end test using the real example experiment."""

    def test_process_example_experiment(self, tmp_path: Path):
        repo_root = Path(".")
        example_dir = repo_root / "experiments" / "EXP_2025_02_01_eye_diagram_coax_40awg"

        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        exp_dir = test_repo / "experiments" / "EXP_2025_02_01_eye_diagram_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_dir.iterdir():
            if f.is_dir():
                raw_dir = exp_dir / f.name
                raw_dir.mkdir()
                for rf in f.iterdir():
                    (raw_dir / rf.name).write_bytes(rf.read_bytes())
            else:
                (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        result = process_experiment(exp_dir, test_repo)

        assert result.validation.is_valid, f"Validation errors: {result.validation.errors}"
        assert result.error is None
        assert "eye_metrics_csv" in result.outputs
        assert "eye_summary_json" in result.outputs

        df = pd.read_csv(result.outputs["eye_metrics_csv"])
        assert len(df) == 8  # 4 files * 2 phases
        assert "eye_height_ratio" in df.columns
        assert "eye_height_mv" in df.columns

        with open(result.outputs["eye_summary_json"]) as f:
            summary = json.load(f)
        assert summary["num_files"] == 4
        assert summary["cable_model"] == "coax_spi_sci_40awg"

    def test_aggregate_after_processing(self, tmp_path: Path):
        repo_root = Path(".")
        example_dir = repo_root / "experiments" / "EXP_2025_02_01_eye_diagram_coax_40awg"

        test_repo = tmp_path / "repo"
        test_repo.mkdir()

        for link_name in ["experiment_types", "models"]:
            (test_repo / link_name).symlink_to(
                (repo_root / link_name).resolve(), target_is_directory=True
            )

        exp_dir = test_repo / "experiments" / "EXP_2025_02_01_eye_diagram_coax_40awg"
        exp_dir.mkdir(parents=True)
        for f in example_dir.iterdir():
            if f.is_dir():
                raw_dir = exp_dir / f.name
                raw_dir.mkdir()
                for rf in f.iterdir():
                    (raw_dir / rf.name).write_bytes(rf.read_bytes())
            else:
                (exp_dir / f.name).write_bytes(f.read_bytes())

        (test_repo / "derived").mkdir()

        result = process_experiment(exp_dir, test_repo)
        assert result.error is None

        outputs = aggregate_type("eye_diagram_characterization", test_repo)

        assert "eye_diagram_comparison_table" in outputs
        assert "eye_diagram_comparison_plot" in outputs

        df = pd.read_csv(outputs["eye_diagram_comparison_table"])
        assert len(df) == 1
        assert df.iloc[0]["experiment_id"] == "EXP_2025_02_01_eye_diagram_coax_40awg"
