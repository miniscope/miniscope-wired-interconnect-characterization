"""Tests for ResistanceSummary aggregator."""

from pathlib import Path

import pandas as pd
import pytest

from src.aggregation.resistance import ResistanceSummary
from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition
from src.processing.resistance import NormalizeResistance


class TestResistanceSummary:
    @pytest.fixture
    def definition(self):
        return load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )

    @pytest.fixture
    def processed_experiment(
        self, resistance_fixtures_dir: Path, fixture_models_dir: Path, tmp_path: Path
    ) -> tuple[Path, Path]:
        """Process a fixture experiment and return (exp_dir, derived_dir)."""
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )

        derived_dir = tmp_path / "derived"
        output_dir = derived_dir / "normalized" / experiment.experiment_id

        processor = NormalizeResistance(models_dir=fixture_models_dir)
        processor.process(exp_dir, experiment, definition, output_dir)

        return exp_dir, derived_dir

    def test_name_property(self):
        aggregator = ResistanceSummary()
        assert aggregator.name == "resistance_summary"

    def test_aggregate_single(self, processed_experiment, definition, tmp_path: Path):
        exp_dir, derived_dir = processed_experiment
        aggregator = ResistanceSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([exp_dir], definition, output_dir)

        assert "resistance_summary_table" in outputs
        assert "resistance_boxplot" in outputs
        assert outputs["resistance_summary_table"].exists()
        assert outputs["resistance_boxplot"].exists()

    def test_summary_table_columns(self, processed_experiment, definition, tmp_path: Path):
        exp_dir, derived_dir = processed_experiment
        aggregator = ResistanceSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([exp_dir], definition, output_dir)
        df = pd.read_csv(outputs["resistance_summary_table"])

        assert len(df) == 1
        assert "experiment_id" in df.columns
        assert "mean_resistance_ohm" in df.columns
        assert "mean_resistance_per_m" in df.columns
        assert df.iloc[0]["experiment_id"] == "test_resistance_valid"

    def test_boxplot_is_png(self, processed_experiment, definition, tmp_path: Path):
        exp_dir, derived_dir = processed_experiment
        aggregator = ResistanceSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([exp_dir], definition, output_dir)
        boxplot_path = outputs["resistance_boxplot"]
        assert boxplot_path.suffix == ".png"
        assert boxplot_path.stat().st_size > 0

    def test_skips_unprocessed(self, definition, tmp_path: Path):
        """An experiment dir with no processed output should be skipped."""
        fake_dir = tmp_path / "experiments" / "fake_experiment"
        fake_dir.mkdir(parents=True)

        aggregator = ResistanceSummary(derived_dir=tmp_path / "derived")
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([fake_dir], definition, output_dir)
        assert outputs == {}

    def test_aggregate_multiple(
        self,
        resistance_fixtures_dir: Path,
        fixture_models_dir: Path,
        definition,
        tmp_path: Path,
    ):
        """Process two fixtures and aggregate them together."""
        derived_dir = tmp_path / "derived"
        exp_dirs: list[Path] = []

        for fixture_name in ["valid_experiment", "valid_minimal"]:
            exp_dir = resistance_fixtures_dir / fixture_name
            experiment = load_experiment(exp_dir / "experiment.yaml")
            output_dir = derived_dir / "normalized" / experiment.experiment_id

            processor = NormalizeResistance(models_dir=fixture_models_dir)
            processor.process(exp_dir, experiment, definition, output_dir)
            exp_dirs.append(exp_dir)

        aggregator = ResistanceSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"
        outputs = aggregator.aggregate(exp_dirs, definition, output_dir)

        df = pd.read_csv(outputs["resistance_summary_table"])
        assert len(df) == 2
