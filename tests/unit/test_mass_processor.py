"""Tests for NormalizeMass processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.mass import NormalizeMass
from tests.conftest import make_mass_session

MASS_DEFINITION = Path("measurement_types/mass/v1/definition.yaml")


class TestNormalizeMass:
    @pytest.fixture
    def processor(self) -> NormalizeMass:
        return NormalizeMass()

    @pytest.fixture
    def definition(self):
        return load_definition(MASS_DEFINITION)

    def test_process_valid(self, processor, definition, mass_session_dir: Path, tmp_path: Path):
        session = load_session(mass_session_dir / "session.yaml")
        outputs = processor.process(mass_session_dir, session, definition, tmp_path / "output")

        assert "normalized_mass_csv" in outputs
        assert "mass_summary_json" in outputs
        assert outputs["normalized_mass_csv"].exists()
        assert outputs["mass_summary_json"].exists()

    def test_normalized_csv_columns(
        self, processor, definition, mass_session_dir: Path, tmp_path: Path
    ):
        session = load_session(mass_session_dir / "session.yaml")
        outputs = processor.process(mass_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_mass_csv"])
        assert "cable_mass_g" in df.columns
        assert "cable_mass_g_per_cm" in df.columns
        assert len(df) == 4

    def test_net_and_per_cm_computed(
        self, processor, definition, mass_session_dir: Path, tmp_path: Path
    ):
        session = load_session(mass_session_dir / "session.yaml")
        outputs = processor.process(mass_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_mass_csv"])
        expected_net = df["assembly_mass_g"] - df["fixture_mass_g"]
        pd.testing.assert_series_equal(df["cable_mass_g"], expected_net, check_names=False)
        # Session is 500 mm = 50 cm, so per-centimetre = net / 50
        pd.testing.assert_series_equal(
            df["cable_mass_g_per_cm"], expected_net / 50, check_names=False
        )

    def test_summary_json_keys(self, processor, definition, mass_session_dir: Path, tmp_path: Path):
        session = load_session(mass_session_dir / "session.yaml")
        outputs = processor.process(mass_session_dir, session, definition, tmp_path / "output")

        with open(outputs["mass_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250115_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 500.0
        assert summary["num_measurements"] == 4
        assert "mean_cable_mass_g" in summary
        assert "mean_cable_mass_g_per_cm" in summary
        assert summary["measurement_method"] == "digital_balance"
        assert summary["measurement_instrument"] == "Test Balance"
        # net ~ 8 g over 50 cm -> ~0.16 g/cm
        assert 0.15 < summary["mean_cable_mass_g_per_cm"] < 0.17

    def test_commutator_has_no_per_cm(self, processor, definition, tmp_path: Path):
        """Without a length, only the net mass is computed."""
        session_dir = make_mass_session(
            tmp_path,
            profile_id="test_commutator",
            length_mm=None,
            condition="static",
            rows=[(5.0, 2.0, "")],
        )
        session = load_session(session_dir / "session.yaml")
        outputs = processor.process(session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_mass_csv"])
        assert "cable_mass_g" in df.columns
        assert "cable_mass_g_per_cm" not in df.columns
        with open(outputs["mass_summary_json"]) as f:
            summary = json.load(f)
        assert summary["mean_cable_mass_g"] == 3.0
        assert "mean_cable_mass_g_per_cm" not in summary

    def test_output_dir_created(
        self, processor, definition, mass_session_dir: Path, tmp_path: Path
    ):
        session = load_session(mass_session_dir / "session.yaml")
        output_dir = tmp_path / "deep" / "nested" / "output"
        processor.process(mass_session_dir, session, definition, output_dir)
        assert output_dir.exists()
