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


class TestAverageMarginSweeps:
    def _sweep(self, lane, points):
        from src.instruments.types import MarginPoint, MarginSweep

        return MarginSweep(
            lane, [MarginPoint(a, int(a // 10), 0, e == 0, e, s) for a, e, s in points]
        )

    def test_single_run_returned_unchanged(self):
        from src.acquire.pages.serdes import average_margin_sweeps
        from src.instruments.types import FORWARD_3G

        sweep = self._sweep(FORWARD_3G, [(400.0, 0, "ok"), (390.0, 5, "errors")])
        assert average_margin_sweeps([sweep]) is sweep

    def test_averages_errors_and_penalizes_early_stop(self):
        """Different-length runs: a run that stopped above an amplitude counts as
        failed (error ceiling) at that harder, lower step."""
        from src.acquire.pages.serdes import _ERROR_CEILING, average_margin_sweeps
        from src.instruments.types import FORWARD_3G

        run_a = self._sweep(  # stopped at 390 (errored)
            FORWARD_3G, [(410.0, 0, "ok"), (400.0, 0, "ok"), (390.0, 4, "errors")]
        )
        run_b = self._sweep(  # reached 380 before erroring
            FORWARD_3G,
            [(410.0, 0, "ok"), (400.0, 0, "ok"), (390.0, 0, "ok"), (380.0, 10, "errors")],
        )

        avg = average_margin_sweeps([run_a, run_b])
        by_amp = {p.tx_amplitude_mv: p for p in avg.points}

        assert sorted(by_amp, reverse=True) == [410.0, 400.0, 390.0, 380.0]
        assert by_amp[410.0].errors == 0 and by_amp[410.0].status == "ok"
        assert by_amp[390.0].errors == 2 and by_amp[390.0].status == "errors"  # mean(4, 0)
        # 380 mV: run A stopped above it -> failure ceiling; mean(256, 10) -> 133.
        assert by_amp[380.0].errors == round((_ERROR_CEILING + 10) / 2)
        assert by_amp[380.0].status == "errors"

    def test_lost_lock_clamped_to_ceiling(self):
        from src.acquire.pages.serdes import _ERROR_CEILING, average_margin_sweeps
        from src.instruments.types import REVERSE_187M

        run_a = self._sweep(REVERSE_187M, [(250.0, 0, "ok"), (240.0, -1, "lost_lock")])
        run_b = self._sweep(REVERSE_187M, [(250.0, 0, "ok"), (240.0, 0, "ok")])

        avg = average_margin_sweeps([run_a, run_b])
        by_amp = {p.tx_amplitude_mv: p for p in avg.points}
        assert by_amp[240.0].errors == round(_ERROR_CEILING / 2)  # mean(256, 0)


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
