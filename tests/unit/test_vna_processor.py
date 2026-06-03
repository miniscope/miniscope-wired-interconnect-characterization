"""Tests for ProcessVNA processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.vna import ProcessVNA


class TestProcessVNA:
    @pytest.fixture
    def processor(self, fixture_models_dir: Path) -> ProcessVNA:
        return ProcessVNA(models_dir=fixture_models_dir)

    @pytest.fixture
    def definition(self):
        return load_definition(Path("measurement_types/vna/v1/definition.yaml"))

    def test_name_property(self, processor: ProcessVNA):
        assert processor.name == "process_vna"

    def test_process_valid(self, processor, definition, vna_session_dir: Path, tmp_path: Path):
        session = load_session(vna_session_dir / "session.yaml")
        output_dir = tmp_path / "output"

        outputs = processor.process(vna_session_dir, session, definition, output_dir)

        assert "vna_metrics_csv" in outputs
        assert "vna_traces_csv" in outputs
        assert "vna_summary_json" in outputs
        assert outputs["vna_metrics_csv"].exists()
        assert outputs["vna_traces_csv"].exists()
        assert outputs["vna_summary_json"].exists()

    def test_metrics_csv_columns(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        assert "filename" in df.columns
        assert "max_insertion_loss_db" in df.columns
        assert "characteristic_impedance_ohm" in df.columns
        assert "num_points" in df.columns
        assert len(df) == 2  # 2 .s2p files

    def test_traces_csv_has_all_points(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_traces_csv"])
        assert "frequency_hz" in df.columns
        assert "s21_db" in df.columns
        assert "s11_db" in df.columns
        assert "attenuation_db" in df.columns
        # 2 files * 101 points each = 202
        assert len(df) == 202

    def test_attenuation_is_negated_s21(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_traces_csv"])
        assert (df["attenuation_db"] == -df["s21_db"]).all()

    def test_insertion_loss_at_frequencies(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        has_il_cols = [
            c for c in df.columns if c.startswith("insertion_loss_") and c.endswith("_db")
        ]
        assert len(has_il_cols) > 0

    def test_summary_json(self, processor, definition, vna_session_dir: Path, tmp_path: Path):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        with open(outputs["vna_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250301_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 1000.0
        assert summary["num_files"] == 2
        assert "mean_max_insertion_loss_db" in summary
        assert summary["vna_instrument"] == "Test VNA"

    def test_minimal_session(
        self, processor, definition, measurements_fixtures_dir: Path, tmp_path: Path
    ):
        session_dir = measurements_fixtures_dir / "test_cable" / "1000mm" / "vna" / "20250302_01"
        session = load_session(session_dir / "session.yaml")
        outputs = processor.process(session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        assert len(df) == 1
