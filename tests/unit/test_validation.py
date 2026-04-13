"""Tests for TypeFieldValidator -- dynamic validation of type_fields."""

from pathlib import Path

import pytest
import yaml

from src.core.schemas import ExperimentDefinition
from src.core.validation import TypeFieldValidator


class TestTypeFieldValidator:
    @pytest.fixture
    def full_definition(self, full_definition_path: Path) -> ExperimentDefinition:
        with open(full_definition_path) as f:
            raw = yaml.safe_load(f)
        return ExperimentDefinition.model_validate(raw)

    def test_valid_fields(self, full_definition: ExperimentDefinition):
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate(
            {
                "cable_model": "some_cable",
                "method": "method_a",
                "temperature_c": 22.5,
            }
        )
        assert errors == []

    def test_missing_required(self, full_definition: ExperimentDefinition):
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate({"method": "method_a"})
        assert any("cable_model" in e for e in errors)

    def test_unknown_field(self, full_definition: ExperimentDefinition):
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate(
            {
                "cable_model": "x",
                "method": "method_a",
                "unknown_field": "bad",
            }
        )
        assert any("Unknown field" in e for e in errors)

    def test_invalid_enum_value(self, full_definition: ExperimentDefinition):
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate(
            {
                "cable_model": "x",
                "method": "invalid_method",
            }
        )
        assert any("not in" in e for e in errors)

    def test_wrong_type(self, full_definition: ExperimentDefinition):
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate(
            {
                "cable_model": "x",
                "method": "method_a",
                "temperature_c": "not_a_float",
            }
        )
        assert any("temperature_c" in e for e in errors)

    def test_optional_field_not_required(self, full_definition: ExperimentDefinition):
        """temperature_c is optional with a default, so omitting it is fine."""
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate(
            {
                "cable_model": "x",
                "method": "method_a",
            }
        )
        assert errors == []

    def test_int_accepted_for_float(self, full_definition: ExperimentDefinition):
        """Integer values should be accepted for float fields."""
        validator = TypeFieldValidator(full_definition)
        errors = validator.validate(
            {
                "cable_model": "x",
                "method": "method_a",
                "temperature_c": 25,
            }
        )
        assert errors == []
