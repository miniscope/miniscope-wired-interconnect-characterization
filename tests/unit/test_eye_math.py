"""Tests for pure eye-monitor grid and link-margin math."""

import numpy as np

from src.processing.eye import (
    UI_FULL_SCALE,
    V_FULL_SCALE_MV,
    _longest_open_run,
    extract_eye_opening,
    link_margin_metrics,
)


def _grid(open_fraction: float, n_phase: int = 16, n_vth: int = 8):
    """Build a raw EOM grid (parallel arrays) with an open elliptical center."""
    phase, vth, polarity, hits, errors = [], [], [], [], []
    phase_codes = np.linspace(0, 127, n_phase).astype(int)
    vth_codes = np.linspace(0, 63, n_vth).astype(int)
    for ph in phase_codes:
        x = (ph - 64) / (64.0 * open_fraction)
        for vt in vth_codes:
            y = (vt / 32.0) / open_fraction
            err = 0 if (x * x + y * y) <= 1.0 else 30000
            for pol in (0, 1):
                phase.append(ph)
                vth.append(vt)
                polarity.append(pol)
                hits.append(32768)
                errors.append(err)
    return (np.array(phase), np.array(vth), np.array(polarity), np.array(hits), np.array(errors))


class TestLongestOpenRun:
    def test_empty(self):
        assert len(_longest_open_run(np.array([2.0, 2.0, 2.0]), 1e-3)) == 0

    def test_all_open(self):
        run = _longest_open_run(np.zeros(5), 1e-3)
        assert len(run) == 5

    def test_middle_run(self):
        row = np.array([1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        run = _longest_open_run(row, 1e-3)
        assert list(run) == [1, 2, 3]


class TestExtractEyeOpening:
    def test_fully_closed_eye(self):
        phase, vth, polarity, hits, errors = _grid(open_fraction=0.0001)
        m = extract_eye_opening(phase, vth, polarity, errors, hits)
        assert m["eye_area_ratio"] < 0.2
        assert m["eye_width_ui"] == 0.0

    def test_fully_open_eye(self):
        # Every cell error-free -> full area, full width, full height.
        phase = np.array([0, 64, 127] * 2)
        vth = np.array([0, 0, 0, 63, 63, 63])
        polarity = np.array([1, 1, 1, 0, 0, 0])
        hits = np.full(6, 32768)
        errors = np.zeros(6, dtype=int)
        m = extract_eye_opening(phase, vth, polarity, errors, hits)
        assert m["eye_area_ratio"] == 1.0
        assert m["zero_error_fraction"] == 1.0
        assert m["eye_width_ui"] == UI_FULL_SCALE

    def test_open_center(self):
        phase, vth, polarity, hits, errors = _grid(open_fraction=0.6)
        m = extract_eye_opening(phase, vth, polarity, errors, hits)
        assert 0.0 < m["eye_area_ratio"] < 1.0
        assert 0.0 < m["eye_width_ui"] <= UI_FULL_SCALE
        assert 0.0 < m["eye_height_mv"] <= 2 * V_FULL_SCALE_MV

    def test_timeout_cells_excluded(self):
        # errors == -1 marks a timeout; such cells are not counted as measured,
        # so fractions are taken over the valid cells only.
        phase = np.array([64, 64, 64])
        vth = np.array([0, 10, 20])
        polarity = np.array([1, 1, 1])
        hits = np.array([32768, 32768, 0])
        errors = np.array([0, 30000, -1])  # one clean, one erroring, one timeout
        m = extract_eye_opening(phase, vth, polarity, errors, hits)
        assert m["zero_error_fraction"] == 0.5  # 1 of 2 valid cells


class TestLinkMarginMetrics:
    def test_clean_sweep(self):
        amps = np.array([20.0, 40.0, 60.0, 80.0, 100.0])
        errors = np.array([200, 50, 5, 0, 0])
        m = link_margin_metrics(amps, errors)
        assert m["error_onset_mv"] == 60.0
        assert m["link_margin_mv"] == 80.0

    def test_no_errors_at_all(self):
        amps = np.array([20.0, 40.0, 60.0])
        errors = np.array([0, 0, 0])
        m = link_margin_metrics(amps, errors)
        assert m["error_onset_mv"] is None
        assert m["link_margin_mv"] == 20.0

    def test_lost_lock_counts_as_error(self):
        # A lost-lock step (-1) is treated as erroring, not error-free.
        amps = np.array([60.0, 80.0, 100.0])
        errors = np.array([-1, 0, 0])
        m = link_margin_metrics(amps, errors)
        assert m["error_onset_mv"] == 60.0
        assert m["link_margin_mv"] == 80.0

    def test_nonmonotonic_sweep(self):
        amps = np.array([20.0, 40.0, 60.0, 80.0])
        errors = np.array([10, 0, 3, 0])  # 40 mV fluked a clean window
        m = link_margin_metrics(amps, errors)
        assert m["error_onset_mv"] == 60.0
        assert m["link_margin_mv"] == 80.0
