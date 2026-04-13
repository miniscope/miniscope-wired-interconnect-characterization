"""Tests for experiment loading utilities."""

from pathlib import Path

import pytest

from src.core.experiment_schemas import ExperimentRecord
from src.core.loading import load_experiment


class TestLoadExperiment:
    def test_load_valid(self, valid_experiment_path: Path):
        record = load_experiment(valid_experiment_path)
        assert isinstance(record, ExperimentRecord)
        assert record.experiment_id == "test_exp_001"

    def test_load_nonexistent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_experiment(tmp_path / "nope.yaml")
