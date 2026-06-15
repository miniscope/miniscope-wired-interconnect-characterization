"""Tests for WeightSummary aggregator."""

from pathlib import Path

import pandas as pd
import pytest

from src.aggregation.base import SessionContext
from src.aggregation.weight import WeightSummary
from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.weight import NormalizeWeight
from tests.conftest import make_weight_session

WEIGHT_DEFINITION = Path("measurement_types/weight/v1/definition.yaml")


def process_session_ctx(session_dir: Path, derived_root: Path) -> SessionContext:
    """Process one weight session and return its SessionContext."""
    session = load_session(session_dir / "session.yaml")
    definition = load_definition(WEIGHT_DEFINITION)
    derived_dir = derived_root / session_dir.name

    NormalizeWeight().process(session_dir, session, definition, derived_dir)

    return SessionContext(session_dir=session_dir, derived_dir=derived_dir, record=session)


class TestWeightSummary:
    @pytest.fixture
    def definition(self):
        return load_definition(WEIGHT_DEFINITION)

    @pytest.fixture
    def processed_session(self, weight_session_dir: Path, tmp_path: Path) -> SessionContext:
        return process_session_ctx(weight_session_dir, tmp_path / "derived")

    def test_aggregate_single(self, processed_session, definition, tmp_path: Path):
        aggregator = WeightSummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")

        assert "weight_summary_table" in outputs
        assert "weight_boxplot" in outputs
        assert outputs["weight_summary_table"].exists()
        assert outputs["weight_boxplot"].exists()

    def test_summary_table_columns(self, processed_session, definition, tmp_path: Path):
        aggregator = WeightSummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        df = pd.read_csv(outputs["weight_summary_table"])

        assert len(df) == 1
        assert "profile_id" in df.columns
        assert "session_id" in df.columns
        assert "cable_length_mm" in df.columns
        assert "mean_cable_weight_g" in df.columns
        assert "mean_cable_weight_g_per_cm" in df.columns
        assert df.iloc[0]["profile_id"] == "test_cable"
        assert df.iloc[0]["session_id"] == "20250115_01"

    def test_boxplot_is_png(self, processed_session, definition, tmp_path: Path):
        aggregator = WeightSummary()
        outputs = aggregator.aggregate([processed_session], definition, tmp_path / "aggregated")
        boxplot_path = outputs["weight_boxplot"]
        assert boxplot_path.suffix == ".png"
        assert boxplot_path.stat().st_size > 0

    def test_skips_unprocessed(self, definition, weight_session_dir: Path, tmp_path: Path):
        """A session with no processed output should be skipped."""
        session = load_session(weight_session_dir / "session.yaml")
        ctx = SessionContext(
            session_dir=weight_session_dir,
            derived_dir=tmp_path / "nonexistent",
            record=session,
        )

        aggregator = WeightSummary()
        outputs = aggregator.aggregate([ctx], definition, tmp_path / "aggregated")
        assert outputs == {}

    def test_aggregate_multiple(self, definition, tmp_path: Path):
        """Process two sessions at different lengths and aggregate them together."""
        contexts = [
            process_session_ctx(
                make_weight_session(tmp_path / "s1", session_id="20250115_01", length_mm=500.0),
                tmp_path / "derived",
            ),
            process_session_ctx(
                make_weight_session(tmp_path / "s2", session_id="20250116_01", length_mm=1000.0),
                tmp_path / "derived",
            ),
        ]

        aggregator = WeightSummary()
        outputs = aggregator.aggregate(contexts, definition, tmp_path / "aggregated")

        df = pd.read_csv(outputs["weight_summary_table"])
        assert len(df) == 2
        assert set(df["session_id"]) == {"20250115_01", "20250116_01"}
