"""Tests for the pipeline runner."""

from pathlib import Path

import pytest

from src.pipeline import PipelineResult, _resolve_class, process_experiment
from src.processing.resistance import NormalizeResistance


class TestResolveClass:
    def test_valid_path(self):
        cls = _resolve_class("src.processing.resistance.NormalizeResistance")
        assert cls is NormalizeResistance

    def test_invalid_module(self):
        with pytest.raises(ModuleNotFoundError):
            _resolve_class("src.processing.nonexistent.Foo")

    def test_invalid_class(self):
        with pytest.raises(AttributeError):
            _resolve_class("src.processing.resistance.NonexistentClass")


class TestProcessExperiment:
    def test_valid_experiment(self, tmp_path: Path, resistance_fixtures_dir: Path):
        """Set up a minimal repo structure and process a fixture experiment."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        (repo_root / "experiment_types").symlink_to(
            Path("experiment_types").resolve(), target_is_directory=True
        )

        models_dir = repo_root / "models" / "cable_models"
        models_dir.mkdir(parents=True)
        fixture_cable = (
            resistance_fixtures_dir.parent.parent
            / "models"
            / "cable_models"
            / "test_cable_for_resistance.yaml"
        )
        (models_dir / "test_cable_for_resistance.yaml").write_bytes(fixture_cable.read_bytes())

        exp_dir = repo_root / "experiments" / "test_resistance_valid"
        exp_dir.mkdir(parents=True)
        src_exp = resistance_fixtures_dir / "valid_experiment"
        (exp_dir / "experiment.yaml").write_bytes((src_exp / "experiment.yaml").read_bytes())
        (exp_dir / "measurements.csv").write_bytes((src_exp / "measurements.csv").read_bytes())

        result = process_experiment(exp_dir, repo_root)

        assert isinstance(result, PipelineResult)
        assert result.validation.is_valid
        assert result.error is None
        assert "normalized_resistance_csv" in result.outputs
        assert "resistance_summary_json" in result.outputs

    def test_invalid_experiment_no_yaml(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        exp_dir = repo_root / "experiments" / "bad_exp"
        exp_dir.mkdir(parents=True)
        (repo_root / "experiment_types").mkdir()

        result = process_experiment(exp_dir, repo_root)
        assert not result.validation.is_valid

    def test_invalid_csv_stops_processing(self, tmp_path: Path, resistance_fixtures_dir: Path):
        """An experiment with bad CSV should fail validation and not produce outputs."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        (repo_root / "experiment_types").symlink_to(
            Path("experiment_types").resolve(), target_is_directory=True
        )
        (repo_root / "models").mkdir()

        exp_dir = repo_root / "experiments" / "test_resistance_bad_columns"
        exp_dir.mkdir(parents=True)
        src_exp = resistance_fixtures_dir / "bad_csv_columns"
        (exp_dir / "experiment.yaml").write_bytes((src_exp / "experiment.yaml").read_bytes())
        (exp_dir / "measurements.csv").write_bytes((src_exp / "measurements.csv").read_bytes())

        result = process_experiment(exp_dir, repo_root)
        assert not result.validation.is_valid
        assert result.outputs == {}
