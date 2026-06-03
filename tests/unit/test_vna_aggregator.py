"""Tests for VNASummary aggregator."""

from pathlib import Path

import pandas as pd
import pytest

from src.aggregation.base import SessionContext
from src.aggregation.vna import VNASummary
from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.vna import ProcessVNA

VNA_DEFINITION = Path("measurement_types/vna/v1/definition.yaml")


class TestVNASummary:
    @pytest.fixture
    def definition(self):
        return load_definition(VNA_DEFINITION)

    @pytest.fixture
    def processed_session(self, vna_session_dir: Path, tmp_path: Path) -> SessionContext:
        session = load_session(vna_session_dir / "session.yaml")
        definition = load_definition(VNA_DEFINITION)
        derived_dir = tmp_path / "derived" / "20250301_01"

        processor = ProcessVNA()
        processor.process(vna_session_dir, session, definition, derived_dir)

        return SessionContext(session_dir=vna_session_dir, derived_dir=derived_dir, record=session)

    def test_name_property(self):
        aggregator = VNASummary()
        assert aggregator.name == "vna_summary"

    def test_aggregate_single(self, processed_session, definition, tmp_path: Path):
        aggregator = VNASummary()
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([processed_session], definition, output_dir)

        assert "vna_comparison_table" in outputs
        assert "vna_overlay_plot" in outputs
        assert outputs["vna_comparison_table"].exists()
        assert outputs["vna_overlay_plot"].exists()

    def test_comparison_table_columns(self, processed_session, definition, tmp_path: Path):
        aggregator = VNASummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        df = pd.read_csv(outputs["vna_comparison_table"])

        assert len(df) == 1
        assert "profile_id" in df.columns
        assert "session_id" in df.columns
        assert "mean_max_insertion_loss_db" in df.columns
        assert df.iloc[0]["profile_id"] == "test_cable"
        assert df.iloc[0]["session_id"] == "20250301_01"

    def test_overlay_plot_is_png(self, processed_session, definition, tmp_path: Path):
        aggregator = VNASummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        plot_path = outputs["vna_overlay_plot"]
        assert plot_path.suffix == ".png"
        assert plot_path.stat().st_size > 0

    def test_impedance_plot_generated(self, processed_session, definition, tmp_path: Path):
        aggregator = VNASummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        assert "vna_impedance_plot" in outputs
        assert outputs["vna_impedance_plot"].exists()

    def test_skips_unprocessed(self, definition, vna_session_dir: Path, tmp_path: Path):
        session = load_session(vna_session_dir / "session.yaml")
        ctx = SessionContext(
            session_dir=vna_session_dir,
            derived_dir=tmp_path / "nonexistent",
            record=session,
        )
        aggregator = VNASummary()
        outputs = aggregator.aggregate([ctx], definition, tmp_path / "aggregated")
        assert outputs == {}
