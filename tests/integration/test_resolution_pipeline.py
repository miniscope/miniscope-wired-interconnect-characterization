"""Integration tests: resolution manifests generated during pipeline processing."""

import json
from pathlib import Path

from src.pipeline import process_session


class TestResolutionPipelineIntegration:
    def test_manifest_written_on_process(self, test_repo: Path):
        """Processing a session should write a resolution manifest alongside outputs."""
        session_dir = (
            test_repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250115_01"
        )

        result = process_session(session_dir, test_repo)
        assert result.error is None

        manifest_path = (
            test_repo
            / "derived"
            / "sessions"
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250115_01"
            / "resolution_manifest.json"
        )
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["session_ref"] == "test_cable/500mm/resistance/20250115_01"
        assert "models" in manifest
        assert "connector_model" in manifest["models"]

        connector = manifest["models"]["connector_model"]
        assert connector["resolved"] is True
        assert connector["source"] == "repo"
        assert connector["model_id"] == "test_connector"

    def test_manifest_records_unresolved_optional(self, test_repo: Path):
        """Optional model refs not provided should appear as unresolved."""
        session_dir = (
            test_repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250116_01"
        )

        result = process_session(session_dir, test_repo)
        assert result.error is None

        manifest_path = (
            test_repo
            / "derived"
            / "sessions"
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250116_01"
            / "resolution_manifest.json"
        )
        with open(manifest_path) as f:
            manifest = json.load(f)

        # connector_model is optional and not provided in this session
        connector = manifest["models"]["connector_model"]
        assert connector["resolved"] is False
        assert "not provided" in connector["reason"]
