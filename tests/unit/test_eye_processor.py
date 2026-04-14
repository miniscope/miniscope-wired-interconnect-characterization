"""Tests for ExtractEyeMetrics processor."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.core.loading import load_experiment
from src.experiment_types.loader import load_definition
from src.processing.eye_diagram import (
    ExtractEyeMetrics,
    _longest_zero_run,
    extract_eye_opening,
)


class TestLongestZeroRun:
    def test_all_zeros(self):
        arr = np.array([0, 0, 0, 0, 0])
        start, length = _longest_zero_run(arr)
        assert length == 5
        assert start == 0

    def test_no_zeros(self):
        arr = np.array([1, 2, 3, 4])
        start, length = _longest_zero_run(arr)
        assert length == 0

    def test_center_gap(self):
        arr = np.array([5, 5, 0, 0, 0, 5, 5])
        start, length = _longest_zero_run(arr)
        assert start == 2
        assert length == 3

    def test_multiple_runs_picks_longest(self):
        arr = np.array([0, 0, 5, 0, 0, 0, 5, 0])
        start, length = _longest_zero_run(arr)
        assert start == 3
        assert length == 3

    def test_empty_array(self):
        arr = np.array([])
        start, length = _longest_zero_run(arr)
        assert length == 0


class TestExtractEyeOpening:
    def test_known_opening(self):
        """A 64x64 histogram with a 32x32 center opening (50% each)."""
        hist = np.full((64, 64), 10, dtype=np.int32)
        hist[16:48, 16:48] = 0  # 32x32 opening centered

        metrics = extract_eye_opening(hist)
        assert metrics["eye_height_bins"] == 32
        assert metrics["eye_width_bins"] == 32
        assert abs(metrics["eye_height_ratio"] - 0.5) < 0.01
        assert abs(metrics["eye_width_ratio"] - 0.5) < 0.01
        assert abs(metrics["eye_area_ratio"] - 0.25) < 0.01

    def test_closed_eye(self):
        """Full density everywhere — no opening."""
        hist = np.full((64, 64), 10, dtype=np.int32)
        metrics = extract_eye_opening(hist)
        assert metrics["eye_height_bins"] == 0
        assert metrics["eye_width_bins"] == 0
        assert metrics["eye_area_ratio"] == 0.0

    def test_wide_open_eye(self):
        """All zeros — fully open."""
        hist = np.zeros((64, 64), dtype=np.int32)
        metrics = extract_eye_opening(hist)
        assert metrics["eye_height_bins"] == 64
        assert metrics["eye_width_bins"] == 64
        assert abs(metrics["eye_area_ratio"] - 1.0) < 0.01


class TestExtractEyeMetrics:
    @pytest.fixture
    def processor(self, fixture_models_dir: Path) -> ExtractEyeMetrics:
        return ExtractEyeMetrics(models_dir=fixture_models_dir)

    @pytest.fixture
    def definition(self):
        return load_definition(
            Path("experiment_types/eye_diagram_characterization/v1/definition.yaml")
        )

    def test_name_property(self, processor: ExtractEyeMetrics):
        assert processor.name == "extract_eye_metrics"

    def test_process_valid(self, processor, definition, eye_fixtures_dir: Path, tmp_path: Path):
        exp_dir = eye_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        output_dir = tmp_path / "output"

        outputs = processor.process(exp_dir, experiment, definition, output_dir)

        assert "eye_metrics_csv" in outputs
        assert "eye_summary_json" in outputs
        assert outputs["eye_metrics_csv"].exists()
        assert outputs["eye_summary_json"].exists()

    def test_metrics_csv_columns(
        self, processor, definition, eye_fixtures_dir: Path, tmp_path: Path
    ):
        exp_dir = eye_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["eye_metrics_csv"])
        assert "filename" in df.columns
        assert "phase" in df.columns
        assert "eye_height_bins" in df.columns
        assert "eye_width_bins" in df.columns
        assert "eye_height_ratio" in df.columns
        assert "eye_area_ratio" in df.columns
        assert "cable_length_mm" in df.columns

    def test_two_rows_per_file(self, processor, definition, eye_fixtures_dir: Path, tmp_path: Path):
        """Each .npz produces 2 rows (rising + falling phases)."""
        exp_dir = eye_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["eye_metrics_csv"])
        # 2 files * 2 phases = 4 rows
        assert len(df) == 4
        assert set(df["phase"].unique()) == {"rising", "falling"}

    def test_physical_units_when_available(
        self, processor, definition, eye_fixtures_dir: Path, tmp_path: Path
    ):
        """Fixture npz files include voltage_range/time_range, so physical units should appear."""
        exp_dir = eye_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["eye_metrics_csv"])
        assert "eye_height_mv" in df.columns
        assert "eye_width_ps" in df.columns

    def test_summary_json(self, processor, definition, eye_fixtures_dir: Path, tmp_path: Path):
        exp_dir = eye_fixtures_dir / "valid_experiment"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        with open(outputs["eye_summary_json"]) as f:
            summary = json.load(f)

        assert summary["experiment_id"] == "test_eye_valid"
        assert summary["num_files"] == 2
        assert summary["num_measurements"] == 4
        assert "mean_eye_height_ratio" in summary
        assert "mean_eye_area_ratio" in summary

    def test_minimal_experiment(
        self, processor, definition, eye_fixtures_dir: Path, tmp_path: Path
    ):
        exp_dir = eye_fixtures_dir / "valid_minimal"
        experiment = load_experiment(exp_dir / "experiment.yaml")
        outputs = processor.process(exp_dir, experiment, definition, tmp_path / "output")

        df = pd.read_csv(outputs["eye_metrics_csv"])
        assert len(df) == 2  # 1 file * 2 phases
