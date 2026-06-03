"""Tests for SerdesSummary aggregator."""

from pathlib import Path

import pandas as pd
import pytest

from src.aggregation.base import SessionContext
from src.aggregation.serdes import SerdesSummary
from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.serdes import ProcessSerdes

SERDES_DEFINITION = Path("measurement_types/serdes/v1/definition.yaml")


def process_fixture_session(session_dir: Path, derived_root: Path) -> SessionContext:
    session = load_session(session_dir / "session.yaml")
    definition = load_definition(SERDES_DEFINITION)
    derived_dir = derived_root / session_dir.name

    processor = ProcessSerdes()
    processor.process(session_dir, session, definition, derived_dir)

    return SessionContext(session_dir=session_dir, derived_dir=derived_dir, record=session)


class TestSerdesSummary:
    @pytest.fixture
    def definition(self):
        return load_definition(SERDES_DEFINITION)

    @pytest.fixture
    def processed_sessions(
        self, measurements_fixtures_dir: Path, tmp_path: Path
    ) -> list[SessionContext]:
        """Two serdes sessions at different lengths."""
        base = measurements_fixtures_dir / "test_cable"
        return [
            process_fixture_session(
                base / "500mm" / "serdes" / "20250401_01", tmp_path / "derived"
            ),
            process_fixture_session(
                base / "1000mm" / "serdes" / "20250402_01", tmp_path / "derived"
            ),
        ]

    def test_name_property(self):
        assert SerdesSummary().name == "serdes_summary"

    def test_aggregate(self, processed_sessions, definition, tmp_path: Path):
        aggregator = SerdesSummary()
        outputs = aggregator.aggregate(processed_sessions, definition, tmp_path / "aggregated")

        assert "serdes_metrics_table" in outputs
        assert "serdes_eye_vs_length_plot" in outputs
        assert "serdes_margin_vs_length_plot" in outputs
        for path in outputs.values():
            assert path.exists()
            assert path.stat().st_size > 0

    def test_table_contents(self, processed_sessions, definition, tmp_path: Path):
        aggregator = SerdesSummary()
        outputs = aggregator.aggregate(processed_sessions, definition, tmp_path / "aggregated")

        df = pd.read_csv(outputs["serdes_metrics_table"])
        # 2 sessions * 4 combos
        assert len(df) == 8
        assert set(df["cable_length_mm"]) == {500.0, 1000.0}
        assert "eye_area_ratio" in df.columns
        assert "link_margin_mv" in df.columns

    def test_longer_cable_worse_eye(self, processed_sessions, definition, tmp_path: Path):
        """Fixture generator makes the 1000mm eyes smaller than the 500mm eyes."""
        aggregator = SerdesSummary()
        outputs = aggregator.aggregate(processed_sessions, definition, tmp_path / "aggregated")

        df = pd.read_csv(outputs["serdes_metrics_table"])
        combo = df[(df["channel"] == "forward") & (df["rate_gbps"] == 3)]
        by_length = combo.set_index("cable_length_mm")["eye_area_ratio"]
        assert by_length[1000.0] < by_length[500.0]

    def test_skips_unprocessed(self, definition, measurements_fixtures_dir: Path, tmp_path: Path):
        session_dir = measurements_fixtures_dir / "test_cable" / "500mm" / "serdes" / "20250401_01"
        session = load_session(session_dir / "session.yaml")
        ctx = SessionContext(
            session_dir=session_dir,
            derived_dir=tmp_path / "nonexistent",
            record=session,
        )
        outputs = SerdesSummary().aggregate([ctx], definition, tmp_path / "aggregated")
        assert outputs == {}
