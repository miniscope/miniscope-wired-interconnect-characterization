"""Tests for NormalizeWeight processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.weight import NormalizeWeight
from tests.conftest import make_weight_session

WEIGHT_DEFINITION = Path("measurement_types/weight/v1/definition.yaml")


class TestNormalizeWeight:
    @pytest.fixture
    def processor(self) -> NormalizeWeight:
        return NormalizeWeight()

    @pytest.fixture
    def definition(self):
        return load_definition(WEIGHT_DEFINITION)

    def test_process_valid(self, processor, definition, weight_session_dir: Path, tmp_path: Path):
        session = load_session(weight_session_dir / "session.yaml")
        outputs = processor.process(weight_session_dir, session, definition, tmp_path / "output")

        assert "normalized_weight_csv" in outputs
        assert "weight_summary_json" in outputs
        assert outputs["normalized_weight_csv"].exists()
        assert outputs["weight_summary_json"].exists()

    def test_normalized_csv_columns(
        self, processor, definition, weight_session_dir: Path, tmp_path: Path
    ):
        session = load_session(weight_session_dir / "session.yaml")
        outputs = processor.process(weight_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_weight_csv"])
        assert "cable_weight_g" in df.columns
        assert "cable_weight_g_per_cm" in df.columns
        assert len(df) == 4

    def test_net_and_per_cm_computed(
        self, processor, definition, weight_session_dir: Path, tmp_path: Path
    ):
        session = load_session(weight_session_dir / "session.yaml")
        outputs = processor.process(weight_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_weight_csv"])
        expected_net = df["assembly_weight_g"] - df["fixture_weight_g"]
        pd.testing.assert_series_equal(df["cable_weight_g"], expected_net, check_names=False)
        # Session is 500 mm = 50 cm, so per-centimetre = net / 50
        pd.testing.assert_series_equal(
            df["cable_weight_g_per_cm"], expected_net / 50, check_names=False
        )

    def test_summary_json_keys(
        self, processor, definition, weight_session_dir: Path, tmp_path: Path
    ):
        session = load_session(weight_session_dir / "session.yaml")
        outputs = processor.process(weight_session_dir, session, definition, tmp_path / "output")

        with open(outputs["weight_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250115_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 500.0
        assert summary["num_measurements"] == 4
        assert "mean_cable_weight_g" in summary
        assert "mean_cable_weight_g_per_cm" in summary
        assert summary["measurement_method"] == "digital_balance"
        assert summary["measurement_instrument"] == "Test Balance"
        # net ~ 8 g over 50 cm -> ~0.16 g/cm
        assert 0.15 < summary["mean_cable_weight_g_per_cm"] < 0.17

    def test_commutator_has_no_per_cm(self, processor, definition, tmp_path: Path):
        """Without a length, only the net mass is computed."""
        session_dir = make_weight_session(
            tmp_path,
            profile_id="test_commutator",
            length_mm=None,
            condition="static",
            rows=[(5.0, 2.0, "")],
        )
        session = load_session(session_dir / "session.yaml")
        outputs = processor.process(session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["normalized_weight_csv"])
        assert "cable_weight_g" in df.columns
        assert "cable_weight_g_per_cm" not in df.columns
        with open(outputs["weight_summary_json"]) as f:
            summary = json.load(f)
        assert summary["mean_cable_weight_g"] == 3.0
        assert "mean_cable_weight_g_per_cm" not in summary

    def test_output_dir_created(
        self, processor, definition, weight_session_dir: Path, tmp_path: Path
    ):
        session = load_session(weight_session_dir / "session.yaml")
        output_dir = tmp_path / "deep" / "nested" / "output"
        processor.process(weight_session_dir, session, definition, output_dir)
        assert output_dir.exists()
