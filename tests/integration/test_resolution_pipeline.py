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
        # The resistance type declares no model_ref fields (connector models
        # were retired), so the manifest records an empty model set. The
        # resolve/unresolve paths themselves are covered in test_resolver.py.
        assert manifest["models"] == {}
