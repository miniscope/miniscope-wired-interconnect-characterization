"""Tests for ProcessSerdes processor."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.serdes import ProcessSerdes


@pytest.fixture
def serdes_session_dir(measurements_fixtures_dir: Path) -> Path:
    return measurements_fixtures_dir / "test_cable" / "500mm" / "serdes" / "20250401_01"


class TestProcessSerdes:
    @pytest.fixture
    def processor(self) -> ProcessSerdes:
        return ProcessSerdes()

    @pytest.fixture
    def definition(self):
        return load_definition(Path("measurement_types/serdes/v1/definition.yaml"))

    def test_name_property(self, processor: ProcessSerdes):
        assert processor.name == "process_serdes"

    def test_process_valid(self, processor, definition, serdes_session_dir: Path, tmp_path: Path):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        assert "serdes_metrics_csv" in outputs
        assert "serdes_summary_json" in outputs
        assert outputs["serdes_metrics_csv"].exists()
        assert outputs["serdes_summary_json"].exists()

    def test_metrics_csv_has_all_combos(
        self, processor, definition, serdes_session_dir: Path, tmp_path: Path
    ):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["serdes_metrics_csv"])
        assert len(df) == 4
        combos = set(zip(df["channel"], df["rate_gbps"], strict=False))
        assert combos == {("forward", 3), ("forward", 6), ("back", 3), ("back", 6)}

    def test_metrics_columns(self, processor, definition, serdes_session_dir: Path, tmp_path: Path):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["serdes_metrics_csv"])
        for col in [
            "eye_height_ratio",
            "eye_width_ratio",
            "eye_area_ratio",
            "eye_height_mv",
            "eye_width_ps",
            "link_margin_mv",
            "error_onset_mv",
            "num_margin_points",
        ]:
            assert col in df.columns

        # Synthetic fixtures have an open eye and a clear error onset
        assert (df["eye_area_ratio"] > 0).all()
        assert df["link_margin_mv"].notna().all()

    def test_higher_rate_has_smaller_eye(
        self, processor, definition, serdes_session_dir: Path, tmp_path: Path
    ):
        """Fixture generator makes 6 Gbps eyes smaller than 3 Gbps eyes."""
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["serdes_metrics_csv"]).set_index(["channel", "rate_gbps"])
        assert df.loc[("forward", 6), "eye_area_ratio"] < df.loc[("forward", 3), "eye_area_ratio"]

    def test_summary_json(self, processor, definition, serdes_session_dir: Path, tmp_path: Path):
        session = load_session(serdes_session_dir / "session.yaml")
        outputs = processor.process(serdes_session_dir, session, definition, tmp_path / "output")

        with open(outputs["serdes_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250401_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 500.0
        assert summary["num_combos"] == 4
        assert len(summary["combos"]) == 4
        assert "worst_eye_area_ratio" in summary
        assert "worst_link_margin_mv" in summary
        assert summary["serdes_device"] == "Test GMSL2 eval kit"
