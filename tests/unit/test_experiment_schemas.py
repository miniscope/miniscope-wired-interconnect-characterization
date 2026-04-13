"""Tests for ExperimentRecord schema."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.core.experiment_schemas import ExperimentRecord


class TestExperimentRecord:
    def test_load_valid(self, valid_experiment_path: Path):
        with open(valid_experiment_path) as f:
            raw = yaml.safe_load(f)
        record = ExperimentRecord.model_validate(raw)
        assert record.experiment_id == "test_exp_001"
        assert record.experiment_type == "test_type"
        assert record.type_fields["sample_id"] == "SAMPLE_001"

    def test_invalid_missing_id(self, fixtures_dir: Path):
        path = fixtures_dir / "experiments" / "invalid_no_id.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        with pytest.raises(ValidationError):
            ExperimentRecord.model_validate(raw)

    def test_schema_version_pattern(self):
        with pytest.raises(ValidationError):
            ExperimentRecord(
                schema_version="bad",
                experiment_id="x",
                experiment_type="t",
                experiment_type_version=1,
                date="2025-01-01",
            )

    def test_valid_minimal(self):
        record = ExperimentRecord(
            schema_version="1.0",
            experiment_id="minimal",
            experiment_type="test",
            experiment_type_version=1,
            date="2025-01-01",
        )
        assert record.type_fields == {}

    def test_experiment_type_version_must_be_positive(self):
        with pytest.raises(ValidationError):
            ExperimentRecord(
                schema_version="1.0",
                experiment_id="x",
                experiment_type="t",
                experiment_type_version=0,
                date="2025-01-01",
            )

    def test_experiment_id_not_empty(self):
        with pytest.raises(ValidationError):
            ExperimentRecord(
                schema_version="1.0",
                experiment_id="",
                experiment_type="t",
                experiment_type_version=1,
                date="2025-01-01",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ExperimentRecord(
                schema_version="1.0",
                experiment_id="x",
                experiment_type="t",
                experiment_type_version=1,
                date="2025-01-01",
                unknown_field="bad",
            )
