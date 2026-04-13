"""Tests for experiment type loader and registry."""

from pathlib import Path

import pytest

from src.experiment_types.loader import load_definition
from src.experiment_types.registry import ExperimentTypeRegistry


class TestLoadDefinition:
    def test_load_valid(self, valid_definition_path: Path):
        defn = load_definition(valid_definition_path)
        assert defn.name == "test_type"

    def test_load_nonexistent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_definition(tmp_path / "nope.yaml")


class TestExperimentTypeRegistry:
    def test_discover_real_definitions(self):
        """Test discovery against the actual experiment_types/ directory."""
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        found = registry.discover()
        assert len(found) >= 3
        type_names = [t for t, v in found]
        assert "resistance_characterization" in type_names
        assert "vna_characterization" in type_names
        assert "eye_diagram_characterization" in type_names

    def test_get_specific_version(self):
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        defn = registry.get("resistance_characterization", 1)
        assert defn.name == "resistance_characterization"
        assert defn.version == 1

    def test_get_nonexistent_raises(self):
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        with pytest.raises(FileNotFoundError):
            registry.get("nonexistent_type", 1)

    def test_get_latest(self):
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        defn = registry.get_latest("resistance_characterization")
        assert defn.version == 1

    def test_load_all(self):
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        all_defs = registry.load_all()
        assert len(all_defs) >= 3

    def test_discover_with_fixtures(self, tmp_path: Path):
        """Test discovery with a synthetic directory structure."""
        type_dir = tmp_path / "my_type" / "v1"
        type_dir.mkdir(parents=True)
        defn_file = type_dir / "definition.yaml"
        defn_file.write_text("name: my_type\nversion: 1\ndescription: test\nfields: []\n")
        registry = ExperimentTypeRegistry(tmp_path)
        found = registry.discover()
        assert ("my_type", 1) in found

    def test_caching(self):
        """Loading the same definition twice should return the cached version."""
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        defn1 = registry.get("resistance_characterization", 1)
        defn2 = registry.get("resistance_characterization", 1)
        assert defn1 is defn2

    def test_empty_directory(self, tmp_path: Path):
        registry = ExperimentTypeRegistry(tmp_path)
        assert registry.discover() == []

    def test_get_latest_nonexistent(self):
        registry = ExperimentTypeRegistry(Path("experiment_types"))
        with pytest.raises(FileNotFoundError):
            registry.get_latest("nonexistent_type")
