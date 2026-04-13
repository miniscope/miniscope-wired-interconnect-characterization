"""Tests for hardware model Pydantic schemas."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.core.loading import load_model
from src.core.model_schemas import CableModel, ConnectorModel


class TestCableModel:
    def test_load_valid(self, valid_cable_path: Path):
        with open(valid_cable_path) as f:
            raw = yaml.safe_load(f)
        cable = CableModel.model_validate(raw)
        assert cable.model_id == "test_cable_001"
        assert cable.conductor_count == 4

    def test_conductor_count_ge_1(self):
        with pytest.raises(ValidationError):
            CableModel(
                schema_version="1.0",
                model_id="bad",
                conductor_count=0,
            )

    def test_extra_fields_allowed(self):
        cable = CableModel(
            schema_version="1.0",
            model_id="flex",
            conductor_count=2,
            custom_vendor_field="allowed",
        )
        assert cable.model_id == "flex"

    def test_invalid_fixture(self, fixtures_dir: Path):
        path = fixtures_dir / "models" / "invalid_cable_no_conductors.yaml"
        with open(path) as f:
            raw = yaml.safe_load(f)
        with pytest.raises(ValidationError):
            CableModel.model_validate(raw)


class TestConnectorModel:
    def test_defaults(self):
        conn = ConnectorModel(
            schema_version="1.0",
            model_id="test_conn",
        )
        assert conn.pin_count == 1
        assert conn.connector_family == ""

    def test_pin_count_ge_1(self):
        with pytest.raises(ValidationError):
            ConnectorModel(
                schema_version="1.0",
                model_id="bad",
                pin_count=0,
            )


class TestLoadModel:
    def test_load_cable(self, valid_cable_path: Path):
        model = load_model(valid_cable_path, model_type="cable_models")
        assert isinstance(model, CableModel)
        assert model.model_id == "test_cable_001"

    def test_unknown_model_type(self, valid_cable_path: Path):
        with pytest.raises(ValueError, match="Unknown model type"):
            load_model(valid_cable_path, model_type="nonexistent")
