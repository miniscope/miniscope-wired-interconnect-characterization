"""Tests for ResistanceSummary aggregator."""

from pathlib import Path

import pandas as pd
import pytest

from src.aggregation.base import SessionContext
from src.aggregation.resistance import ResistanceSummary
from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.resistance import NormalizeResistance

RESISTANCE_DEFINITION = Path("measurement_types/resistance/v1/definition.yaml")


def process_fixture_session(session_dir: Path, derived_root: Path) -> SessionContext:
    """Process one fixture session and return its SessionContext."""
    session = load_session(session_dir / "session.yaml")
    definition = load_definition(RESISTANCE_DEFINITION)
    derived_dir = derived_root / session_dir.name

    processor = NormalizeResistance()
    processor.process(session_dir, session, definition, derived_dir)

    return SessionContext(session_dir=session_dir, derived_dir=derived_dir, record=session)


class TestResistanceSummary:
    @pytest.fixture
    def definition(self):
        return load_definition(RESISTANCE_DEFINITION)

    @pytest.fixture
    def processed_session(self, resistance_session_dir: Path, tmp_path: Path) -> SessionContext:
        return process_fixture_session(resistance_session_dir, tmp_path / "derived")

    def test_name_property(self):
        aggregator = ResistanceSummary()
        assert aggregator.name == "resistance_summary"

    def test_aggregate_single(self, processed_session, definition, tmp_path: Path):
        aggregator = ResistanceSummary()
        output_dir = tmp_path / "aggregated"

        outputs = aggregator.aggregate([processed_session], definition, output_dir)

        assert "resistance_summary_table" in outputs
        assert "resistance_boxplot" in outputs
        assert outputs["resistance_summary_table"].exists()
        assert outputs["resistance_boxplot"].exists()

    def test_summary_table_columns(self, processed_session, definition, tmp_path: Path):
        aggregator = ResistanceSummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        df = pd.read_csv(outputs["resistance_summary_table"])

        assert len(df) == 1
        assert "profile_id" in df.columns
        assert "session_id" in df.columns
        assert "cable_length_mm" in df.columns
        assert "mean_resistance_ohm" in df.columns
        assert "mean_roundtrip_resistance_ohm_per_m" in df.columns
        assert df.iloc[0]["profile_id"] == "test_cable"
        assert df.iloc[0]["session_id"] == "20250115_01"

    def test_boxplot_is_png(self, processed_session, definition, tmp_path: Path):
        aggregator = ResistanceSummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        boxplot_path = outputs["resistance_boxplot"]
        assert boxplot_path.suffix == ".png"
        assert boxplot_path.stat().st_size > 0

    def test_skips_unprocessed(self, definition, resistance_session_dir: Path, tmp_path: Path):
        """A session with no processed output should be skipped."""
        session = load_session(resistance_session_dir / "session.yaml")
        ctx = SessionContext(
            session_dir=resistance_session_dir,
            derived_dir=tmp_path / "nonexistent",
            record=session,
        )

        aggregator = ResistanceSummary()
        outputs = aggregator.aggregate([ctx], definition, tmp_path / "aggregated")
        assert outputs == {}

    def test_aggregate_multiple(
        self,
        measurements_fixtures_dir: Path,
        definition,
        tmp_path: Path,
    ):
        """Process two fixture sessions and aggregate them together."""
        base = measurements_fixtures_dir / "test_cable" / "500mm" / "resistance"
        contexts = [
            process_fixture_session(base / session_id, tmp_path / "derived")
            for session_id in ["20250115_01", "20250116_01"]
        ]

        aggregator = ResistanceSummary()
        outputs = aggregator.aggregate(contexts, definition, tmp_path / "aggregated")

        df = pd.read_csv(outputs["resistance_summary_table"])
        assert len(df) == 2
