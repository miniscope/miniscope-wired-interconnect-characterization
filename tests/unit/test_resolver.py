"""Tests for model metadata resolution."""

import json
from pathlib import Path

import pytest
import yaml

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.wiki.base import BaseWikiClient
from src.wiki.resolver import (
    ModelResolver,
    ResolutionManifest,
    ResolvedModel,
    UnresolvedModel,
    session_ref,
)

RESISTANCE_DEFINITION = Path("measurement_types/resistance/v1/definition.yaml")


class MockWikiClient(BaseWikiClient):
    """Mock wiki client that returns predefined data for specific model_ids."""

    def __init__(self, models: dict[str, dict] | None = None):
        self._models = models or {}

    def fetch_model(self, model_type: str, model_id: str) -> dict | None:
        return self._models.get(f"{model_type}/{model_id}")


class TestSessionRef:
    def test_session_ref(self, resistance_session_dir: Path):
        session = load_session(resistance_session_dir / "session.yaml")
        assert session_ref(session) == "test_cable/500mm/resistance/20250115_01"


class TestResolvedModel:
    def test_to_dict(self):
        rm = ResolvedModel(
            field_name="connector_model",
            model_id="test_connector",
            model_type="connector_models",
            source="repo",
            path="models/connector_models/test_connector.yaml",
        )
        d = rm.to_dict()
        assert d["resolved"] is True
        assert d["source"] == "repo"
        assert d["model_id"] == "test_connector"


class TestUnresolvedModel:
    def test_to_dict(self):
        um = UnresolvedModel(
            field_name="connector_model",
            model_id=None,
            model_type="connector_models",
            reason="not provided",
        )
        d = um.to_dict()
        assert d["resolved"] is False
        assert d["reason"] == "not provided"


class TestResolutionManifest:
    def test_to_dict(self):
        manifest = ResolutionManifest(session_ref="test_cable/500mm/resistance/20250115_01")
        manifest.models["connector_model"] = ResolvedModel(
            field_name="connector_model",
            model_id="test_connector",
            model_type="connector_models",
            source="repo",
        )
        d = manifest.to_dict()
        assert d["session_ref"] == "test_cable/500mm/resistance/20250115_01"
        assert "resolved_at" in d
        assert d["models"]["connector_model"]["resolved"] is True

    def test_to_json(self):
        manifest = ResolutionManifest(session_ref="a/b/c/d")
        j = manifest.to_json()
        parsed = json.loads(j)
        assert parsed["session_ref"] == "a/b/c/d"

    def test_write(self, tmp_path: Path):
        manifest = ResolutionManifest(session_ref="a/b/c/d")
        manifest.models["connector_model"] = ResolvedModel(
            field_name="connector_model",
            model_id="test",
            model_type="connector_models",
            source="repo",
        )
        output = tmp_path / "manifest.json"
        manifest.write(output)
        assert output.exists()
        with open(output) as f:
            data = json.load(f)
        assert data["models"]["connector_model"]["resolved"] is True


class TestModelResolver:
    @pytest.fixture
    def models_dir(self, fixture_models_dir: Path) -> Path:
        return fixture_models_dir

    def test_resolve_from_repo(self, models_dir: Path):
        resolver = ModelResolver(models_dir=models_dir)
        result = resolver.resolve("connector_model", "connector_models", "test_connector")
        assert isinstance(result, ResolvedModel)
        assert result.source == "repo"
        assert result.model_id == "test_connector"
        assert result.data is not None
        assert result.data["model_id"] == "test_connector"

    def test_resolve_not_found(self, models_dir: Path):
        resolver = ModelResolver(models_dir=models_dir)
        result = resolver.resolve("connector_model", "connector_models", "nonexistent")
        assert isinstance(result, UnresolvedModel)
        assert "not found" in result.reason

    def test_wiki_takes_priority_over_repo(self, models_dir: Path):
        wiki_data = {"model_id": "test_connector", "source": "wiki_version"}
        wiki_client = MockWikiClient({"connector_models/test_connector": wiki_data})
        resolver = ModelResolver(models_dir=models_dir, wiki_client=wiki_client)
        result = resolver.resolve("connector_model", "connector_models", "test_connector")
        assert isinstance(result, ResolvedModel)
        assert result.source == "wiki"
        assert result.data["source"] == "wiki_version"

    def test_wiki_not_found_falls_back_to_repo(self, models_dir: Path):
        wiki_client = MockWikiClient({})  # empty -- nothing found
        resolver = ModelResolver(models_dir=models_dir, wiki_client=wiki_client)
        result = resolver.resolve("connector_model", "connector_models", "test_connector")
        assert isinstance(result, ResolvedModel)
        assert result.source == "repo"

    def test_no_wiki_client(self, models_dir: Path):
        resolver = ModelResolver(models_dir=models_dir, wiki_client=None)
        result = resolver.resolve("connector_model", "connector_models", "test_connector")
        assert isinstance(result, ResolvedModel)
        assert result.source == "repo"

    def test_resolve_session(self, models_dir: Path, resistance_session_dir: Path):
        session = load_session(resistance_session_dir / "session.yaml")
        definition = load_definition(RESISTANCE_DEFINITION)

        resolver = ModelResolver(models_dir=models_dir)
        manifest = resolver.resolve_session(session, definition)

        assert manifest.session_ref == "test_cable/500mm/resistance/20250115_01"
        assert "connector_model" in manifest.models
        connector = manifest.models["connector_model"]
        assert isinstance(connector, ResolvedModel)
        assert connector.source == "repo"

    def test_resolve_session_optional_not_provided(
        self, models_dir: Path, measurements_fixtures_dir: Path
    ):
        """Optional model_ref fields with no value should be recorded as 'not provided'."""
        session_dir = (
            measurements_fixtures_dir / "test_cable" / "500mm" / "resistance" / "20250116_01"
        )
        session = load_session(session_dir / "session.yaml")
        definition = load_definition(RESISTANCE_DEFINITION)

        resolver = ModelResolver(models_dir=models_dir)
        manifest = resolver.resolve_session(session, definition)

        assert "connector_model" in manifest.models
        conn = manifest.models["connector_model"]
        assert isinstance(conn, UnresolvedModel)
        assert "not provided" in conn.reason

    def test_resolve_session_model_not_in_repo(self, tmp_path: Path):
        """Model ID provided but doesn't exist in repo."""
        session_yaml = {
            "schema_version": "1.0",
            "session_id": "20250101_01",
            "profile_id": "test_cable",
            "cable_length_mm": 500,
            "measurement_type": "resistance",
            "measurement_type_version": 1,
            "date": "2025-01-01",
            "operator": "Test",
            "type_fields": {
                "connector_model": "nonexistent_connector",
                "measurement_instrument": "DMM",
                "measurement_method": "lcr_shorted_loop",
            },
        }
        session_path = tmp_path / "session.yaml"
        with open(session_path, "w") as f:
            yaml.dump(session_yaml, f)

        session = load_session(session_path)
        definition = load_definition(RESISTANCE_DEFINITION)

        empty_models = tmp_path / "models"
        (empty_models / "connector_models").mkdir(parents=True)
        resolver = ModelResolver(models_dir=empty_models)
        manifest = resolver.resolve_session(session, definition)

        conn = manifest.models["connector_model"]
        assert isinstance(conn, UnresolvedModel)
        assert "not found" in conn.reason
