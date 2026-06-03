"""Integration tests: load real definition.yaml files from measurement_types/."""

from pathlib import Path

import pytest

from src.core.schemas import MeasurementDefinition
from src.measurement_types.registry import MeasurementTypeRegistry


class TestRealDefinitions:
    @pytest.fixture
    def registry(self) -> MeasurementTypeRegistry:
        return MeasurementTypeRegistry(Path("measurement_types"))

    def test_all_definitions_load_successfully(self, registry: MeasurementTypeRegistry):
        all_defs = registry.load_all()
        assert len(all_defs) >= 2
        for key, defn in all_defs.items():
            assert isinstance(defn, MeasurementDefinition)
            assert defn.name == key[0]
            assert defn.version == key[1]

    def test_resistance_definition_has_expected_fields(self, registry: MeasurementTypeRegistry):
        defn = registry.get("resistance", 1)
        field_names = [f.name for f in defn.fields]
        assert "measurement_instrument" in field_names
        assert "measurement_method" in field_names

    def test_vna_definition_has_manifest_and_s2p(self, registry: MeasurementTypeRegistry):
        defn = registry.get("vna", 1)
        file_names = [f.name for f in defn.files]
        assert "manifest_csv" in file_names
        assert "s_parameter_files" in file_names

    def test_all_definitions_have_valid_processing_refs(self, registry: MeasurementTypeRegistry):
        """Every processing step must have a non-empty processor string."""
        all_defs = registry.load_all()
        for key, defn in all_defs.items():
            for step in defn.processing_steps:
                assert step.processor, f"{key}: step '{step.name}' has empty processor"

    def test_all_enum_fields_have_values(self, registry: MeasurementTypeRegistry):
        """Every enum field in every definition must have enum_values."""
        all_defs = registry.load_all()
        for key, defn in all_defs.items():
            for field in defn.fields:
                if field.field_type.value == "enum":
                    assert field.enum_values, f"{key}: enum field '{field.name}' has no enum_values"
