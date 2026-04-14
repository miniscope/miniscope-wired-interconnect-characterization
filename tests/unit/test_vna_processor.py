"""Tests for ProcessVNA processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition
from src.processing.vna import ProcessVNA


class TestProcessVNA:
    @pytest.fixture
    def processor(self, fixture_models_dir: Path) -> ProcessVNA:
        return ProcessVNA(models_dir=fixture_models_dir)

    @pytest.fixture
    def definition(self):
        return load_definition(Path("experiment_types/vna_characterization/v1/definition.yaml"))

    def test_name_property(self, processor: ProcessVNA):
        assert processor.name == "process_vna"

    def test_process_valid(self, processor, definition, vna_fixtures_dir: Path, tmp_path: Path):
        exp_dir = vna_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        output_dir = tmp_path / "output"

        outputs = processor.process(exp_dir, experiment, definition, output_dir)

        assert "vna_metrics_csv" in outputs
        assert "vna_traces_csv" in outputs
        assert "vna_summary_json" in outputs
        assert outputs["vna_metrics_csv"].exists()
        assert outputs["vna_traces_csv"].exists()
        assert outputs["vna_summary_json"].exists()

    def test_metrics_csv_columns(
        self, processor, definition, vna_fixtures_dir: Path, tmp_path: Path
    ):
        exp_dir = vna_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        assert "filename" in df.columns
        assert "cable_length_mm" in df.columns
        assert "max_insertion_loss_db" in df.columns
        assert "num_points" in df.columns
        assert len(df) == 2  # 2 .s2p files

    def test_traces_csv_has_all_points(
        self, processor, definition, vna_fixtures_dir: Path, tmp_path: Path
    ):
        exp_dir = vna_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_traces_csv"])
        assert "frequency_hz" in df.columns
        assert "s21_db" in df.columns
        assert "s11_db" in df.columns
        # 2 files * 101 points each = 202
        assert len(df) == 202

    def test_insertion_loss_at_frequencies(
        self, processor, definition, vna_fixtures_dir: Path, tmp_path: Path
    ):
        exp_dir = vna_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        # Should have interpolated insertion loss at key frequencies
        has_il_cols = [
            c for c in df.columns if c.startswith("insertion_loss_") and c.endswith("_db")
        ]
        assert len(has_il_cols) > 0

    def test_summary_json(self, processor, definition, vna_fixtures_dir: Path, tmp_path: Path):
        exp_dir = vna_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        with open(outputs["vna_summary_json"]) as f:
            summary = json.load(f)

        assert summary["experiment_id"] == "test_vna_valid"
        assert summary["num_files"] == 2
        assert "mean_max_insertion_loss_db" in summary
        assert summary["vna_instrument"] == "Test VNA"

    def test_minimal_experiment(
        self, processor, definition, vna_fixtures_dir: Path, tmp_path: Path
    ):
        exp_dir = vna_fixtures_dir / "valid_minimal"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        assert len(df) == 1
