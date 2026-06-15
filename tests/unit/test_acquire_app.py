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
        assert "/measure/weight/{profile_id}/{condition}" in routes
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

    def test_unknown_status_falls_through(self):
        # Any non-lost_lock status renders via the generic fallback, not dropped.
        from src.acquire.pages.serdes import margin_summary_row
        from src.instruments.types import FORWARD_3G, MarginPoint, MarginSweep

        pts = [
            MarginPoint(410.0, 41, 0, True, 0, "ok"),
            MarginPoint(400.0, 40, 0, False, -1, "ser_unreachable"),
        ]
        row = margin_summary_row(MarginSweep(FORWARD_3G, pts))
        assert row["outcome"] == "ser_unreachable at 400 mV"

    def test_floor_is_clean_prefix_not_global_min(self):
        # An averaged sweep can have an "ok" step below the first failure; the
        # floor must be the clean run above the failure, not the global min ok.
        from src.acquire.pages.serdes import margin_summary_row
        from src.instruments.types import FORWARD_6G, MarginPoint, MarginSweep

        pts = [
            MarginPoint(400.0, 40, 0, True, 0, "ok"),
            MarginPoint(390.0, 39, 0, True, 3, "errors"),
            MarginPoint(380.0, 38, 0, True, 0, "ok"),  # spurious clean below failure
        ]
        row = margin_summary_row(MarginSweep(FORWARD_6G, pts))
        assert row["clean_mv"] == "400"  # not 380
        assert row["fail_mv"] == "390"


class TestRenderMarginSummary:
    def test_no_op_when_no_margins(self):
        from src.acquire.pages.serdes import render_margin_summary
        from src.instruments.types import SerdesResult

        class FakeContainer:
            def __init__(self):
                self.cleared = 0

            def clear(self):
                self.cleared += 1

        container = FakeContainer()
        render_margin_summary(container, SerdesResult())
        assert container.cleared == 1


class TestMarginSummaryTables:
    def _runs(self, lane, n, first_error_mv, status="errors"):
        from src.instruments.types import MarginPoint, MarginSweep

        sweeps = []
        for _ in range(n):
            pts = [
                MarginPoint(400.0, 40, 0, True, 0, "ok"),
                MarginPoint(first_error_mv, 39, 0, status == "ok", 5, status),
            ]
            sweeps.append(MarginSweep(lane, pts))
        return sweeps

    def test_iteration_rows_are_labelled_per_lane(self):
        from src.acquire.pages.serdes import margin_iteration_rows
        from src.instruments.types import FORWARD_3G, FORWARD_6G

        margins = self._runs(FORWARD_3G, 2, 390.0) + self._runs(FORWARD_6G, 2, 380.0)
        rows = margin_iteration_rows(margins)

        # Iterations stay grouped by lane, numbered 1..N (not "avg").
        assert [(r["lane"], r["iteration"]) for r in rows] == [
            ("Forward 3 Gbps", "1"),
            ("Forward 3 Gbps", "2"),
            ("Forward 6 Gbps", "1"),
            ("Forward 6 Gbps", "2"),
        ]

    def test_average_rows_are_one_per_lane(self):
        from src.acquire.pages.serdes import margin_average_rows
        from src.instruments.types import FORWARD_3G, FORWARD_6G

        margins = self._runs(FORWARD_3G, 3, 390.0) + self._runs(FORWARD_6G, 3, 380.0)
        rows = margin_average_rows(margins)

        assert [r["lane"] for r in rows] == ["Forward 3 Gbps", "Forward 6 Gbps"]
        assert "iteration" not in rows[0]  # averages table has no Iteration column
        # Identical runs -> the average matches them.
        assert rows[0]["clean_mv"] == "400"
        assert rows[0]["fail_mv"] == "390"


class TestLockWasLost:
    def _sweep(self, lane, status):
        from src.instruments.types import MarginPoint, MarginSweep

        errors = -1 if status in {"lost_lock", "ser_unreachable"} else 5
        return MarginSweep(
            lane,
            [
                MarginPoint(400.0, 40, 0, True, 0, "ok"),
                MarginPoint(390.0, 39, 0, status == "ok", errors, status),
            ],
        )

    def test_normal_error_floor_is_not_lock_loss(self):
        from src.acquire.pages.serdes import lock_was_lost
        from src.instruments.types import FORWARD_3G, SerdesResult

        result = SerdesResult(margins=[self._sweep(FORWARD_3G, "errors")])
        assert lock_was_lost(result) is False

    def test_lost_lock_and_unreachable_are_flagged(self):
        from src.acquire.pages.serdes import lock_was_lost
        from src.instruments.types import FORWARD_3G, FORWARD_6G, REVERSE_187M, SerdesResult

        lost = SerdesResult(
            margins=[self._sweep(FORWARD_3G, "ok"), self._sweep(FORWARD_6G, "lost_lock")]
        )
        unreachable = SerdesResult(margins=[self._sweep(REVERSE_187M, "ser_unreachable")])
        assert lock_was_lost(lost) is True
        assert lock_was_lost(unreachable) is True
