"""Integration tests: load real definition.yaml files from experiment_types/."""

from pathlib import Path

import pytest

from src.core.schemas import ExperimentDefinition
from src.experiment_types.registry import ExperimentTypeRegistry


class TestRealDefinitions:
    @pytest.fixture
    def registry(self) -> ExperimentTypeRegistry:
        return ExperimentTypeRegistry(Path("experiment_types"))

    def test_all_definitions_load_successfully(self, registry: ExperimentTypeRegistry):
        all_defs = registry.load_all()
        assert len(all_defs) >= 3
        for key, defn in all_defs.items():
            assert isinstance(defn, ExperimentDefinition)
            assert defn.name == key[0]
            assert defn.version == key[1]

    def test_resistance_definition_has_expected_fields(self, registry: ExperimentTypeRegistry):
        defn = registry.get("resistance_characterization", 1)
        field_names = [f.name for f in defn.fields]
        assert "cable_model" in field_names
        assert "measurement_instrument" in field_names
        assert "measurement_method" in field_names

    def test_vna_definition_has_manifest_and_s2p(self, registry: ExperimentTypeRegistry):
        defn = registry.get("vna_characterization", 1)
        file_names = [f.name for f in defn.files]
        assert "manifest_csv" in file_names
        assert "s_parameter_files" in file_names

    def test_eye_definition_has_npz_files(self, registry: ExperimentTypeRegistry):
        defn = registry.get("eye_diagram_characterization", 1)
        file_names = [f.name for f in defn.files]
        assert "eye_data_files" in file_names
        file_formats = [f.file_format for f in defn.files]
        assert "npz" in file_formats

    def test_all_definitions_have_valid_processing_refs(self, registry: ExperimentTypeRegistry):
        """Every processing step must have a non-empty processor string."""
        all_defs = registry.load_all()
        for key, defn in all_defs.items():
            for step in defn.processing_steps:
                assert step.processor, f"{key}: step '{step.name}' has empty processor"

    def test_all_enum_fields_have_values(self, registry: ExperimentTypeRegistry):
        """Every enum field in every definition must have enum_values."""
        all_defs = registry.load_all()
        for key, defn in all_defs.items():
            for field in defn.fields:
                if field.field_type.value == "enum":
                    assert field.enum_values, f"{key}: enum field '{field.name}' has no enum_values"
