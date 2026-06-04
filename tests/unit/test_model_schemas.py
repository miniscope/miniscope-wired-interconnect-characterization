"""Tests for hardware model Pydantic schemas."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.loading import load_model
from src.core.model_schemas import MiniscopeModel


class TestMiniscopeModel:
    def test_extra_fields_allowed(self):
        """Hardware models tolerate vendor extras (extra='allow')."""
        scope = MiniscopeModel(
            schema_version="1.0",
            model_id="flex",
            custom_vendor_field="allowed",
        )
        assert scope.model_id == "flex"

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
            serdes_family="GMSL2",
            serdes_rate_gbps=6.0,
        )
        assert scope.max_operating_voltage_v == 5.5
        assert scope.min_current_ma == 20.0
        assert scope.poc_dcr_supply_ohm == 0.05
        assert scope.serdes_rate_gbps == 6.0

    def test_no_supply_voltage_on_model(self):
        """Supply is a user/DAQ-side choice; the model must not carry one."""
        assert "supply_mode" not in MiniscopeModel.model_fields
        assert "default_supply_v" not in MiniscopeModel.model_fields

    def test_negative_poc_dcr_rejected(self):
        with pytest.raises(ValidationError):
            MiniscopeModel(schema_version="1.0", model_id="bad", poc_dcr_supply_ohm=-0.1)


class TestLoadModel:
    def test_load_miniscope(self, fixture_models_dir: Path):
        path = fixture_models_dir / "miniscope_models" / "test_miniscope.yaml"
        model = load_model(path, model_type="miniscope_models")
        assert isinstance(model, MiniscopeModel)
        assert model.model_id == "test_miniscope"

    def test_unknown_model_type(self, fixture_models_dir: Path):
        path = fixture_models_dir / "miniscope_models" / "test_miniscope.yaml"
        with pytest.raises(ValueError, match="Unknown model type"):
            load_model(path, model_type="cable_models")  # retired model type
