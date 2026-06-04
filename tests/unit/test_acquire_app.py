"""Smoke tests for the NiceGUI app (skipped when the acquire extra is absent)."""

from pathlib import Path

import pytest

nicegui = pytest.importorskip("nicegui", reason="acquire extra not installed")

pytestmark = pytest.mark.acquire


class TestAppBuild:
    def test_build_registers_pages(self, test_repo: Path):
        from nicegui import app as nicegui_app

        from src.acquire.app import build_app
        from src.acquire.state import STATE

        build_app(test_repo, simulate=True)

        assert STATE.repo_root == test_repo.resolve()
        assert STATE.simulate is True

        routes = {r.path for r in nicegui_app.routes}
        assert "/" in routes
        assert "/miniscopes" in routes
        assert "/profile/{profile_id}" in routes
        assert "/measure/resistance/{profile_id}/{condition}" in routes
        assert "/measure/serdes/{profile_id}/{condition}" in routes
        assert "/measure/vna/{profile_id}/{condition}" in routes
