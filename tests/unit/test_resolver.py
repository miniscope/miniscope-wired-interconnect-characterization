"""Tests for model metadata resolution."""

import json
from pathlib import Path

import pytest
import yaml

from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition
from src.wiki.base import BaseWikiClient
from src.wiki.resolver import (
    ModelResolver,
    ResolutionManifest,
    ResolvedModel,
    UnresolvedModel,
)


class MockWikiClient(BaseWikiClient):
    """Mock wiki client that returns predefined data for specific model_ids."""

    def __init__(self, models: dict[str, dict] | None = None):
        self._models = models or {}

    def fetch_model(self, model_type: str, model_id: str) -> dict | None:
        return self._models.get(f"{model_type}/{model_id}")


class TestResolvedModel:
    def test_to_dict(self):
        rm = ResolvedModel(
            field_name="cable_model",
            model_id="test_cable",
            model_type="cable_models",
            source="repo",
            path="models/cable_models/test_cable.yaml",
        )
        d = rm.to_dict()
        assert d["resolved"] is True
        assert d["source"] == "repo"
        assert d["model_id"] == "test_cable"


class TestUnresolvedModel:
    def test_to_dict(self):
        um = UnresolvedModel(
            field_name="cable_model",
            model_id=None,
            model_type="cable_models",
            reason="not provided",
        )
        d = um.to_dict()
        assert d["resolved"] is False
        assert d["reason"] == "not provided"


class TestResolutionManifest:
    def test_to_dict(self):
        manifest = ResolutionManifest(experiment_id="test_exp")
        manifest.models["cable_model"] = ResolvedModel(
            field_name="cable_model",
            model_id="test_cable",
            model_type="cable_models",
            source="repo",
        )
        d = manifest.to_dict()
        assert d["experiment_id"] == "test_exp"
        assert "resolved_at" in d
        assert d["models"]["cable_model"]["resolved"] is True

    def test_to_json(self):
        manifest = ResolutionManifest(experiment_id="test_exp")
        j = manifest.to_json()
        parsed = json.loads(j)
        assert parsed["experiment_id"] == "test_exp"

    def test_write(self, tmp_path: Path):
        manifest = ResolutionManifest(experiment_id="test_exp")
        manifest.models["cable_model"] = ResolvedModel(
            field_name="cable_model",
            model_id="test",
            model_type="cable_models",
            source="repo",
        )
        output = tmp_path / "manifest.json"
        manifest.write(output)
        assert output.exists()
        with open(output) as f:
            data = json.load(f)
        assert data["models"]["cable_model"]["resolved"] is True


class TestModelResolver:
    @pytest.fixture
    def models_dir(self, fixture_models_dir: Path) -> Path:
        return fixture_models_dir

    def test_resolve_from_repo(self, models_dir: Path):
        resolver = ModelResolver(models_dir=models_dir)
        result = resolver.resolve("cable_model", "cable_models", "test_cable_for_resistance")
        assert isinstance(result, ResolvedModel)
        assert result.source == "repo"
        assert result.model_id == "test_cable_for_resistance"
        assert result.data is not None
        assert result.data["model_id"] == "test_cable_for_resistance"

    def test_resolve_not_found(self, models_dir: Path):
        resolver = ModelResolver(models_dir=models_dir)
        result = resolver.resolve("cable_model", "cable_models", "nonexistent_cable")
        assert isinstance(result, UnresolvedModel)
        assert "not found" in result.reason

    def test_wiki_takes_priority_over_repo(self, models_dir: Path):
        wiki_data = {"model_id": "test_cable_for_resistance", "source": "wiki_version"}
        wiki_client = MockWikiClient({"cable_models/test_cable_for_resistance": wiki_data})
        resolver = ModelResolver(models_dir=models_dir, wiki_client=wiki_client)
        result = resolver.resolve("cable_model", "cable_models", "test_cable_for_resistance")
        assert isinstance(result, ResolvedModel)
        assert result.source == "wiki"
        assert result.data["source"] == "wiki_version"

    def test_wiki_not_found_falls_back_to_repo(self, models_dir: Path):
        wiki_client = MockWikiClient({})  # empty — nothing found
        resolver = ModelResolver(models_dir=models_dir, wiki_client=wiki_client)
        result = resolver.resolve("cable_model", "cable_models", "test_cable_for_resistance")
        assert isinstance(result, ResolvedModel)
        assert result.source == "repo"

    def test_no_wiki_client(self, models_dir: Path):
        resolver = ModelResolver(models_dir=models_dir, wiki_client=None)
        result = resolver.resolve("cable_model", "cable_models", "test_cable_for_resistance")
        assert isinstance(result, ResolvedModel)
        assert result.source == "repo"

    def test_resolve_experiment(self, models_dir: Path, resistance_fixtures_dir: Path):
        exp_dir = resistance_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )

        resolver = ModelResolver(models_dir=models_dir)
        manifest = resolver.resolve_experiment(experiment, definition)

        assert manifest.experiment_id == "test_resistance_valid"
        assert "cable_model" in manifest.models
        cable = manifest.models["cable_model"]
        assert isinstance(cable, ResolvedModel)
        assert cable.source == "repo"

    def test_resolve_experiment_optional_not_provided(self, models_dir: Path):
        """Optional model_ref fields with no value should be recorded as 'not provided'."""
        experiment = load_experiment(
            Path("experiments/EXP_2025_01_15_resistance_coax_40awg/experiment.yaml")
        )
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )

        resolver = ModelResolver(models_dir=models_dir)
        manifest = resolver.resolve_experiment(experiment, definition)

        # connector_model is optional and not provided
        assert "connector_model" in manifest.models
        conn = manifest.models["connector_model"]
        assert isinstance(conn, UnresolvedModel)
        assert "not provided" in conn.reason

    def test_resolve_experiment_model_not_in_repo(self, tmp_path: Path):
        """Model ID provided but doesn't exist in repo."""
        # Create a minimal experiment referencing a nonexistent model
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        exp_yaml = {
            "schema_version": "1.0",
            "experiment_id": "test",
            "experiment_type": "resistance_characterization",
            "experiment_type_version": 1,
            "date": "2025-01-01",
            "type_fields": {
                "cable_model": "nonexistent_cable",
                "measurement_instrument": "DMM",
                "measurement_method": "two_wire",
            },
        }
        with open(exp_dir / "experiment.yaml", "w") as f:
            yaml.dump(exp_yaml, f)

        experiment = load_experiment(exp_dir / "experiment.yaml")
        definition = load_definition(
            Path("experiment_types/resistance_characterization/v1/definition.yaml")
        )

        empty_models = tmp_path / "models"
        (empty_models / "cable_models").mkdir(parents=True)
        resolver = ModelResolver(models_dir=empty_models)
        manifest = resolver.resolve_experiment(experiment, definition)

        cable = manifest.models["cable_model"]
        assert isinstance(cable, UnresolvedModel)
        assert "not found" in cable.reason
