"""Tests for NormalizeResistance processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.resistance import NormalizeResistance


class TestNormalizeResistance:
    @pytest.fixture
    def processor(self, fixture_models_dir: Path) -> NormalizeResistance:
        return NormalizeResistance(models_dir=fixture_models_dir)

    @pytest.fixture
    def definition(self):
        return load_definition(Path("measurement_types/resistance/v1/definition.yaml"))

    def test_name_property(self, processor: NormalizeResistance):
        assert processor.name == "normalize_resistance"

    def test_process_valid(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_session_dir: Path,
        tmp_path: Path,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        output_dir = tmp_path / "output"

        outputs = processor.process(resistance_session_dir, session, definition, output_dir)

        assert "normalized_resistance_csv" in outputs
        assert "resistance_summary_json" in outputs
        assert outputs["normalized_resistance_csv"].exists()
        assert outputs["resistance_summary_json"].exists()

    def test_output_normalized_csv_columns(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_session_dir: Path,
        tmp_path: Path,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        outputs = processor.process(
            resistance_session_dir, session, definition, tmp_path / "output"
        )

        df = pd.read_csv(outputs["normalized_resistance_csv"])
        assert "resistance_ohm" in df.columns
        assert "roundtrip_resistance_ohm_per_m" in df.columns
        assert len(df) == 4

    def test_roundtrip_resistance_per_m_computed(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_session_dir: Path,
        tmp_path: Path,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        outputs = processor.process(
            resistance_session_dir, session, definition, tmp_path / "output"
        )

        df = pd.read_csv(outputs["normalized_resistance_csv"])
        # Session is 500 mm, so per-meter = resistance / 0.5
        expected_per_m = df["resistance_ohm"] / 0.5
        pd.testing.assert_series_equal(
            df["roundtrip_resistance_ohm_per_m"], expected_per_m, check_names=False
        )

    def test_summary_json_keys(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_session_dir: Path,
        tmp_path: Path,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        outputs = processor.process(
            resistance_session_dir, session, definition, tmp_path / "output"
        )

        with open(outputs["resistance_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250115_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 500.0
        assert summary["num_measurements"] == 4
        assert "mean_resistance_ohm" in summary
        assert "std_resistance_ohm" in summary
        assert "min_resistance_ohm" in summary
        assert "max_resistance_ohm" in summary
        assert "median_resistance_ohm" in summary
        assert "mean_roundtrip_resistance_ohm_per_m" in summary

    def test_summary_includes_metadata(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_session_dir: Path,
        tmp_path: Path,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        outputs = processor.process(
            resistance_session_dir, session, definition, tmp_path / "output"
        )

        with open(outputs["resistance_summary_json"]) as f:
            summary = json.load(f)

        assert summary["measurement_method"] == "lcr_shorted_loop"
        assert summary["measurement_instrument"] == "Test LCR Meter"
        assert summary["operator"] == "Test Operator"

    def test_output_dir_created(
        self,
        processor: NormalizeResistance,
        definition,
        resistance_session_dir: Path,
        tmp_path: Path,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        output_dir = tmp_path / "deep" / "nested" / "output"

        processor.process(resistance_session_dir, session, definition, output_dir)
        assert output_dir.exists()

    def test_minimal_csv_no_notes(
        self,
        processor: NormalizeResistance,
        definition,
        measurements_fixtures_dir: Path,
        tmp_path: Path,
    ):
        session_dir = (
            measurements_fixtures_dir / "test_cable" / "500mm" / "resistance" / "20250116_01"
        )
        session = load_session(session_dir / "session.yaml")
        outputs = processor.process(session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_resistance_csv"])
        assert len(df) == 3
        assert "roundtrip_resistance_ohm_per_m" in df.columns
