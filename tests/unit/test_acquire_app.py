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


class TestLaneSectionTitle:
    def test_titles_separate_speeds(self):
        from src.acquire.pages.serdes import lane_section_title
        from src.instruments.types import FORWARD_3G, FORWARD_6G, REVERSE_187M

        assert lane_section_title(FORWARD_3G) == "Forward link -- 3 Gbps"
        assert lane_section_title(FORWARD_6G) == "Forward link -- 6 Gbps"
        assert lane_section_title(REVERSE_187M) == "Reverse link -- 187.5 Mbps"


class TestMarginSummaryRow:
    def test_reports_floor_and_first_failure(self):
        from src.acquire.pages.serdes import margin_summary_row
        from src.instruments.types import FORWARD_3G, MarginPoint, MarginSweep

        pts = [
            MarginPoint(410.0, 41, 0, True, 0, "ok"),
            MarginPoint(400.0, 40, 0, True, 0, "ok"),
            MarginPoint(390.0, 39, 0, True, 5, "errors"),
        ]
        row = margin_summary_row(MarginSweep(FORWARD_3G, pts))
        assert row["lane"] == "Forward 3 Gbps"
        assert row["steps"] == 3
        assert row["clean_mv"] == "400"  # lowest error-free amplitude
        assert row["fail_mv"] == "390"
        assert row["outcome"] == "errors at 390 mV"

    def test_clean_throughout(self):
        from src.acquire.pages.serdes import margin_summary_row
        from src.instruments.types import REVERSE_187M, MarginPoint, MarginSweep

        pts = [MarginPoint(250.0, 25, 0, True, 0, "ok"), MarginPoint(50.0, 5, 0, True, 0, "ok")]
        row = margin_summary_row(MarginSweep(REVERSE_187M, pts))
        assert row["lane"] == "Reverse 187.5 Mbps"
        assert row["clean_mv"] == "50"
        assert row["fail_mv"] == "--"
        assert row["outcome"] == "clean throughout"

    def test_lost_lock_outcome(self):
        from src.acquire.pages.serdes import margin_summary_row
        from src.instruments.types import FORWARD_6G, MarginPoint, MarginSweep

        pts = [
            MarginPoint(410.0, 80, 0, True, 0, "ok"),
            MarginPoint(400.0, 78, 0, False, -1, "lost_lock"),
        ]
        row = margin_summary_row(MarginSweep(FORWARD_6G, pts))
        assert row["clean_mv"] == "410"
        assert row["outcome"] == "lost lock at 400 mV"
