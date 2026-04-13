"""Tests for NormalizeResistance processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition
from src.processing.resistance import NormalizeResistance


class TestNormalizeResistance:
    @pytest.fixture
    def processor(self, fixture_models_dir: Path) -> NormalizeResistance:
        return NormalizeResistance(models_dir=fixture_models_dir)

    @pytest.fixture
    def definition(self):
        return load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )

    def test_name_property(self, processor: NormalizeResistance):
        assert processor.name == "normalize_resistance"

    def test_process_valid(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        output_dir = tmp_path / "output"

        outputs = processor.process(exp_dir, experiment, definition, output_dir)

        assert "normalized_resistance_csv" in outputs
        assert "resistance_summary_json" in outputs
        assert outputs["normalized_resistance_csv"].exists()
        assert outputs["resistance_summary_json"].exists()

    def test_output_normalized_csv_columns(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_resistance_csv"])
        assert "resistance_ohm" in df.columns
        assert "cable_length_mm" in df.columns
        assert "resistance_per_m" in df.columns
        assert len(df) == 4

    def test_resistance_per_m_computed(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_resistance_csv"])
        expected_per_m = df["resistance_ohm"] / (df["cable_length_mm"] / 1000.0)
        pd.testing.assert_series_equal(df["resistance_per_m"], expected_per_m, check_names=False)

    def test_summary_json_keys(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        with open(outputs["resistance_summary_json"]) as f:
            summary = json.load(f)

        assert summary["experiment_id"] == "test_resistance_valid"
        assert summary["num_measurements"] == 4
        assert "mean_resistance_ohm" in summary
        assert "std_resistance_ohm" in summary
        assert "min_resistance_ohm" in summary
        assert "max_resistance_ohm" in summary
        assert "median_resistance_ohm" in summary
        assert "mean_resistance_per_m" in summary
        assert summary["cable_length_mm"] == 500.0

    def test_summary_includes_metadata(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        with open(outputs["resistance_summary_json"]) as f:
            summary = json.load(f)

        assert summary["cable_model"] == "test_cable_for_resistance"
        assert summary["measurement_method"] == "four_wire"
        assert summary["measurement_instrument"] == "Keithley 2400"

    def test_output_dir_created(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        output_dir = tmp_path / "deep" / "nested" / "output"

        processor.process(exp_dir, experiment, definition, output_dir)
        assert output_dir.exists()

    def test_minimal_csv_no_notes(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_fixtures_dir: Path,
        tmp_path: Path,
    ):
        exp_dir = resistance_fixtures_dir / "valid_minimal"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_resistance_csv"])
        assert len(df) == 3
        assert "resistance_per_m" in df.columns
