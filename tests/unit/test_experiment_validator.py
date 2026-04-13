"""Tests for experiment validation."""

from pathlib import Path

import pytest

from src.core.experiment_validator import (
    ValidationResult,
    validate_experiment,
    validate_resistance_csv,
)
from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition


class TestValidationResult:
    def test_empty_is_valid(self):
        result = ValidationResult()
        assert result.is_valid

    def test_with_errors_not_valid(self):
        result = ValidationResult()
        result.add_error("something wrong")
        assert not result.is_valid

    def test_warnings_still_valid(self):
        result = ValidationResult()
        result.add_warning("heads up")
        assert result.is_valid

    def test_add_error(self):
        result = ValidationResult()
        result.add_error("err1")
        result.add_error("err2")
        assert len(result.errors) == 2

    def test_add_warning(self):
        result = ValidationResult()
        result.add_warning("warn1")
        assert len(result.warnings) == 1


class TestValidateResistanceCsv:
    def test_valid_csv(self, resistance_fixtures_dir: Path):
        csv_path = resistance_fixtures_dir / "valid_experiment" / "measurements.csv"
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert result.is_valid

    def test_missing_resistance_column(self, resistance_fixtures_dir: Path):
        csv_path = resistance_fixtures_dir / "bad_csv_columns" / "measurements.csv"
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert not result.is_valid
        assert any("resistance_ohm" in e for e in result.errors)

    def test_missing_length_column(self, resistance_fixtures_dir: Path):
        csv_path = resistance_fixtures_dir / "bad_csv_columns" / "measurements.csv"
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert any("cable_length_mm" in e for e in result.errors)

    def test_negative_and_nonnumeric_values(self, resistance_fixtures_dir: Path):
        csv_path = resistance_fixtures_dir / "bad_csv_values" / "measurements.csv"
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert not result.is_valid
        assert len(result.errors) >= 3

    def test_minimal_valid_csv(self, resistance_fixtures_dir: Path):
        csv_path = resistance_fixtures_dir / "valid_minimal" / "measurements.csv"
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert result.is_valid

    def test_nonexistent_csv(self, tmp_path: Path):
        result = ValidationResult()
        validate_resistance_csv(tmp_path / "nope.csv", result)
        assert not result.is_valid

    def test_empty_csv(self, tmp_path: Path):
        csv_path = tmp_path / "measurements.csv"
        csv_path.write_text("resistance_ohm,cable_length_mm\n")
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert result.is_valid
        assert any("no data rows" in w for w in result.warnings)


class TestValidateExperiment:
    @pytest.fixture
    def resistance_definition(self) -> Path:
        return Path("experiment_types/resistance_characterization/v1/definition.yaml")

    def test_valid_experiment(self, resistance_fixtures_dir: Path, fixture_models_dir: Path):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )
        result = validate_experiment(exp_dir, experiment, definition, fixture_models_dir)
        assert result.is_valid

    def test_missing_required_file(self, resistance_fixtures_dir: Path):
        exp_dir = resistance_fixtures_dir / "missing_csv"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )
        result = validate_experiment(exp_dir, experiment, definition)
        assert not result.is_valid
        assert any("measurements.csv" in e for e in result.errors)

    def test_model_ref_resolves(self, resistance_fixtures_dir: Path, fixture_models_dir: Path):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )
        result = validate_experiment(exp_dir, experiment, definition, fixture_models_dir)
        assert not any("Model reference" in w for w in result.warnings)

    def test_model_ref_missing_warns(self, resistance_fixtures_dir: Path, tmp_path: Path):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )
        empty_models = tmp_path / "models"
        empty_models.mkdir()
        (empty_models / "cable_models").mkdir()
        result = validate_experiment(exp_dir, experiment, definition, empty_models)
        assert any("Model reference" in w for w in result.warnings)
