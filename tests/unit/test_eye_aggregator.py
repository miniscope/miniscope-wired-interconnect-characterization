"""Tests for EyeDiagramSummary aggregator."""

from pathlib import Path

import pandas as pd
import pytest

from src.aggregation.eye_diagram import EyeDiagramSummary
from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition
from src.processing.eye_diagram import ExtractEyeMetrics


class TestEyeDiagramSummary:
    @pytest.fixture
    def definition(self):
        return load_definition(
            Path("experiment_types/eye_diagram_characterization/v1/definition.yaml")
        )

    @pytest.fixture
    def processed_experiment(
        self, eye_fixtures_dir: Path, fixture_models_dir: Path, tmp_path: Path
    ) -> tuple[Path, Path]:
        """Process a fixture experiment and return (exp_dir, derived_dir)."""
        exp_dir = eye_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/eye_diagram_characterization/v1/definition.yaml")
        )

        derived_dir = tmp_path / "derived"
        output_dir = derived_dir / "normalized" / experiment.experiment_id

        processor = ExtractEyeMetrics(models_dir=fixture_models_dir)
        processor.process(exp_dir, experiment, definition, output_dir)

        return exp_dir, derived_dir

    def test_name_property(self):
        aggregator = EyeDiagramSummary()
        assert aggregator.name == "eye_diagram_summary"

    def test_aggregate_single(self, processed_experiment, definition, tmp_path: Path):
        exp_dir, derived_dir = processed_experiment
        aggregator = EyeDiagramSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([exp_dir], definition, output_dir)

        assert "eye_diagram_comparison_table" in outputs
        assert "eye_diagram_comparison_plot" in outputs
        assert outputs["eye_diagram_comparison_table"].exists()
        assert outputs["eye_diagram_comparison_plot"].exists()

    def test_comparison_table_columns(self, processed_experiment, definition, tmp_path: Path):
        exp_dir, derived_dir = processed_experiment
        aggregator = EyeDiagramSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([exp_dir], definition, output_dir)
        df = pd.read_csv(outputs["eye_diagram_comparison_table"])

        assert len(df) == 1
        assert "experiment_id" in df.columns
        assert "mean_eye_height_ratio" in df.columns
        assert "mean_eye_area_ratio" in df.columns
        assert df.iloc[0]["experiment_id"] == "test_eye_valid"

    def test_plot_is_png(self, processed_experiment, definition, tmp_path: Path):
        exp_dir, derived_dir = processed_experiment
        aggregator = EyeDiagramSummary(derived_dir=derived_dir)
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([exp_dir], definition, output_dir)
        plot_path = outputs["eye_diagram_comparison_plot"]
        assert plot_path.suffix == ".png"
        assert plot_path.stat().st_size > 0

    def test_skips_unprocessed(self, definition, tmp_path: Path):
        fake_dir = tmp_path / "experiments" / "fake"
        fake_dir.mkdir(parents=True)
        aggregator = EyeDiagramSummary(derived_dir=tmp_path / "derived")
        outputs = aggregator.aggregate([fake_dir], definition, tmp_path / "aggregated")
        assert outputs == {}
