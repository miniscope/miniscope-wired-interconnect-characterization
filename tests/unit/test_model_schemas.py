"""Tests for hardware model Pydantic schemas."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.core.loading import load_model
from src.core.model_schemas import CableModel, ConnectorModel, MiniscopeModel


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


class TestMiniscopeModel:
    def test_power_fields(self):
        scope = MiniscopeModel(
            schema_version="1.0",
            model_id="test_scope",
            min_operating_voltage_v=3.3,
            baseline_current_ma=150.0,
            max_current_ma=300.0,
        )
        assert scope.min_operating_voltage_v == 3.3
        assert scope.baseline_current_ma == 150.0
        assert scope.max_current_ma == 300.0

    def test_power_fields_optional(self):
        scope = MiniscopeModel(schema_version="1.0", model_id="test_scope")
        assert scope.min_operating_voltage_v is None

    def test_power_fields_must_be_positive(self):
        with pytest.raises(ValidationError):
            MiniscopeModel(
                schema_version="1.0",
                model_id="bad",
                min_operating_voltage_v=-1.0,
            )

    def test_daq_folded_defaults(self):
        """DAQ/PoC/link fields default sensibly when unspecified."""
        scope = MiniscopeModel(schema_version="1.0", model_id="defaults")
        assert scope.poc_dcr_supply_ohm == 0.0
        assert scope.poc_dcr_receive_ohm == 0.0
        assert scope.supply_mode == "fixed_5v"
        assert scope.default_supply_v == 5.0
        assert scope.max_operating_voltage_v is None
        assert scope.min_current_ma is None
        assert scope.serdes_family == ""
        assert scope.serdes_rate_gbps is None

    def test_daq_folded_fields(self):
        scope = MiniscopeModel(
            schema_version="1.0",
            model_id="full",
            max_operating_voltage_v=5.5,
            min_current_ma=20.0,
            poc_dcr_supply_ohm=0.05,
            poc_dcr_receive_ohm=0.04,
            supply_mode="adjustable",
            default_supply_v=12.0,
            serdes_family="GMSL2",
            serdes_rate_gbps=6.0,
        )
        assert scope.max_operating_voltage_v == 5.5
        assert scope.min_current_ma == 20.0
        assert scope.poc_dcr_supply_ohm == 0.05
        assert scope.supply_mode == "adjustable"
        assert scope.serdes_rate_gbps == 6.0

    def test_invalid_supply_mode_rejected(self):
        with pytest.raises(ValidationError):
            MiniscopeModel(schema_version="1.0", model_id="bad", supply_mode="battery")

    def test_negative_poc_dcr_rejected(self):
        with pytest.raises(ValidationError):
            MiniscopeModel(schema_version="1.0", model_id="bad", poc_dcr_supply_ohm=-0.1)


class TestLoadModel:
    def test_load_cable(self, valid_cable_path: Path):
        model = load_model(valid_cable_path, model_type="cable_models")
        assert isinstance(model, CableModel)
        assert model.model_id == "test_cable_001"

    def test_unknown_model_type(self, valid_cable_path: Path):
        with pytest.raises(ValueError, match="Unknown model type"):
            load_model(valid_cable_path, model_type="nonexistent")
