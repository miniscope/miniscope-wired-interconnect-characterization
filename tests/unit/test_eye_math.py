"""Tests for pure eye-diagram and link-margin math."""

import numpy as np

from src.processing.eye import (
    _longest_zero_run,
    extract_eye_opening,
    eye_opening_physical,
    link_margin_metrics,
)


class TestLongestZeroRun:
    def test_empty(self):
        assert _longest_zero_run(np.array([])) == (0, 0)

    def test_no_zeros(self):
        assert _longest_zero_run(np.array([1, 2, 3])) == (0, 0)

    def test_all_zeros(self):
        assert _longest_zero_run(np.zeros(5)) == (0, 5)

    def test_middle_run(self):
        arr = np.array([1, 0, 0, 0, 1, 0])
        assert _longest_zero_run(arr) == (1, 3)


class TestExtractEyeOpening:
    def test_fully_closed_eye(self):
        eye = np.ones((16, 16))
        metrics = extract_eye_opening(eye)
        assert metrics["eye_height_bins"] == 0
        assert metrics["eye_width_bins"] == 0
        assert metrics["eye_area_ratio"] == 0.0

    def test_fully_open_eye(self):
        eye = np.zeros((16, 16))
        metrics = extract_eye_opening(eye)
        assert metrics["eye_height_ratio"] == 1.0
        assert metrics["eye_width_ratio"] == 1.0
        assert metrics["eye_area_ratio"] == 1.0

    def test_half_open_eye(self):
        """Eye open in the center half of both axes."""
        eye = np.ones((16, 16))
        eye[4:12, 4:12] = 0
        metrics = extract_eye_opening(eye)
        assert metrics["eye_height_bins"] == 8
        assert metrics["eye_width_bins"] == 8
        assert metrics["eye_height_ratio"] == 0.5
        assert metrics["eye_area_ratio"] == 0.25


class TestEyeOpeningPhysical:
    def test_conversion(self):
        metrics = {"eye_height_ratio": 0.5, "eye_width_ratio": 0.25}
        physical = eye_opening_physical(
            metrics,
            voltage_range_mv=np.array([-400.0, 400.0]),
            time_range_ps=np.array([0.0, 400.0]),
        )
        assert physical["eye_height_mv"] == 400.0
        assert physical["eye_width_ps"] == 100.0


class TestLinkMarginMetrics:
    def test_clean_sweep(self):
        """Errors below 60 mV, clean above."""
        amps = np.array([20.0, 40.0, 60.0, 80.0, 100.0])
        errors = np.array([200, 50, 5, 0, 0])
        metrics = link_margin_metrics(amps, errors)
        assert metrics["error_onset_mv"] == 60.0
        assert metrics["link_margin_mv"] == 80.0

    def test_no_errors_at_all(self):
        amps = np.array([20.0, 40.0, 60.0])
        errors = np.array([0, 0, 0])
        metrics = link_margin_metrics(amps, errors)
        assert metrics["error_onset_mv"] is None
        assert metrics["link_margin_mv"] == 20.0

    def test_all_errors(self):
        amps = np.array([20.0, 40.0])
        errors = np.array([10, 5])
        metrics = link_margin_metrics(amps, errors)
        assert metrics["error_onset_mv"] == 40.0
        assert metrics["link_margin_mv"] is None

    def test_unsorted_input(self):
        amps = np.array([100.0, 20.0, 60.0, 40.0, 80.0])
        errors = np.array([0, 200, 5, 50, 0])
        metrics = link_margin_metrics(amps, errors)
        assert metrics["error_onset_mv"] == 60.0
        assert metrics["link_margin_mv"] == 80.0

    def test_nonmonotonic_sweep(self):
        """A zero-error point BELOW the onset must not count as the margin."""
        amps = np.array([20.0, 40.0, 60.0, 80.0])
        errors = np.array([10, 0, 3, 0])  # 40 mV fluked a clean window
        metrics = link_margin_metrics(amps, errors)
        assert metrics["error_onset_mv"] == 60.0
        assert metrics["link_margin_mv"] == 80.0
