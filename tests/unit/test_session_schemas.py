"""Tests for SessionRecord schema and length directory helpers."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.core.session_schemas import (
    SessionRecord,
    length_dir_name,
    parse_length_dir_name,
)


def make_session_kwargs(**overrides) -> dict:
    kwargs = {
        "schema_version": "1.0",
        "session_id": "20250101_01",
        "profile_id": "test_cable",
        "cable_length_mm": 500,
        "measurement_type": "test_type",
        "measurement_type_version": 1,
        "date": "2025-01-01",
        "operator": "Test Operator",
    }
    kwargs.update(overrides)
    return kwargs


class TestSessionRecord:
    def test_load_valid(self, valid_session_path: Path):
        with open(valid_session_path) as f:
            raw = yaml.safe_load(f)
        record = SessionRecord.model_validate(raw)
        assert record.session_id == "20250101_01"
        assert record.profile_id == "test_cable"
        assert record.cable_length_mm == 500
        assert record.measurement_type == "test_type"
        assert record.type_fields["sample_id"] == "SAMPLE_001"

    def test_invalid_missing_operator(self, fixtures_dir: Path):
        path = fixtures_dir / "sessions" / "invalid_no_operator.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(raw)

    def test_schema_version_pattern(self):
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(make_session_kwargs(schema_version="bad"))

    def test_valid_minimal(self):
        record = SessionRecord.model_validate(make_session_kwargs())
        assert record.type_fields == {}
        assert record.notes == ""

    def test_session_id_pattern(self):
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(make_session_kwargs(session_id="session-one"))

    def test_measurement_type_version_must_be_positive(self):
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(make_session_kwargs(measurement_type_version=0))

    def test_cable_length_must_be_positive(self):
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(make_session_kwargs(cable_length_mm=0))

    def test_operator_not_empty(self):
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(make_session_kwargs(operator=""))

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            SessionRecord.model_validate(make_session_kwargs(unknown_field="bad"))


class TestLengthDirName:
    def test_integer_length(self):
        assert length_dir_name(1000) == "1000mm"

    def test_float_length_strips_trailing_zeros(self):
        assert length_dir_name(1524.5) == "1524.5mm"
        assert length_dir_name(500.0) == "500mm"

    def test_parse_roundtrip(self):
        for value in [500.0, 1000.0, 1524.5]:
            assert parse_length_dir_name(length_dir_name(value)) == value

    def test_parse_invalid(self):
        with pytest.raises(ValueError):
            parse_length_dir_name("1000")
        with pytest.raises(ValueError):
            parse_length_dir_name("longmm")
