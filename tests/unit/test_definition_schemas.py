"""Tests for ExperimentDefinition and related Pydantic models."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.core.schemas import (
    ExperimentDefinition,
    FieldSpec,
    FieldType,
    FileSpec,
    ProcessingStep,
)


class TestFieldSpec:
    def test_basic_string_field(self):
        spec = FieldSpec(name="test", field_type=FieldType.STRING)
        assert spec.name == "test"
        assert spec.required is True

    def test_enum_field_requires_values(self):
        with pytest.raises(ValidationError):
            FieldSpec(name="method", field_type=FieldType.ENUM, enum_values=None)

    def test_enum_field_with_values(self):
        spec = FieldSpec(
            name="method",
            field_type=FieldType.ENUM,
            enum_values=["a", "b"],
        )
        assert spec.enum_values == ["a", "b"]

    def test_model_ref_field(self):
        spec = FieldSpec(
            name="cable",
            field_type=FieldType.MODEL_REF,
            model_ref_type="cable_models",
        )
        assert spec.model_ref_type == "cable_models"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            FieldSpec(name="x", field_type=FieldType.STRING, bogus="nope")

    def test_optional_field_with_default(self):
        spec = FieldSpec(
            name="temp",
            field_type=FieldType.FLOAT,
            required=False,
            default=25.0,
        )
        assert spec.default == 25.0
        assert spec.required is False


class TestFileSpec:
    def test_basic_file_spec(self):
        spec = FileSpec(
            name="data",
            filename_pattern="*.csv",
            file_format="csv",
        )
        assert spec.required is True

    def test_optional_file(self):
        spec = FileSpec(
            name="notes",
            filename_pattern="*.txt",
            file_format="txt",
            required=False,
        )
        assert spec.required is False


class TestProcessingStep:
    def test_basic_step(self):
        step = ProcessingStep(
            name="normalize",
            processor="src.processing.test.Normalize",
        )
        assert step.depends_on == []
        assert step.outputs == []

    def test_step_with_dependencies(self):
        step = ProcessingStep(
            name="compute",
            processor="src.processing.test.Compute",
            depends_on=["normalize"],
            outputs=["result_csv"],
        )
        assert step.depends_on == ["normalize"]


class TestExperimentDefinition:
    def test_load_valid_minimal(self, valid_definition_path: Path):
        with open(valid_definition_path) as f:
            raw = yaml.safe_load(f)
        defn = ExperimentDefinition.model_validate(raw)
        assert defn.name == "test_type"
        assert defn.version == 1
        assert len(defn.fields) == 1

    def test_load_valid_full(self, full_definition_path: Path):
        with open(full_definition_path) as f:
            raw = yaml.safe_load(f)
        defn = ExperimentDefinition.model_validate(raw)
        assert defn.name == "full_test_type"
        assert len(defn.fields) == 3
        assert len(defn.files) == 1
        assert len(defn.processing_steps) == 1
        assert len(defn.aggregation) == 1

    def test_invalid_missing_name(self, fixtures_dir: Path):
        path = fixtures_dir / "definitions" / "invalid_missing_name.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        with pytest.raises(ValidationError):
            ExperimentDefinition.model_validate(raw)

    def test_invalid_enum_no_values(self, fixtures_dir: Path):
        path = fixtures_dir / "definitions" / "invalid_enum_no_values.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        with pytest.raises(ValidationError):
            ExperimentDefinition.model_validate(raw)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ExperimentDefinition(
                name="test",
                version=1,
                description="test",
                fields=[],
                unknown_field="bad",
            )
