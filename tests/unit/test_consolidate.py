"""Tests for per-profile consolidation across sessions."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.analysis.consolidate import (
    _mean_std_n,
    consolidate_profile,
    consolidate_profiles,
)
from src.pipeline import process_all


class TestMeanStdN:
    def test_empty(self):
        assert _mean_std_n([]) == {"mean": None, "std": None, "n_sessions": 0}

    def test_none_filtered(self):
        stats = _mean_std_n([1.0, None, 3.0])
        assert stats["mean"] == 2.0
        assert stats["n_sessions"] == 2

    def test_single_value_no_std(self):
        stats = _mean_std_n([2.5])
        assert stats["mean"] == 2.5
        assert stats["std"] is None
        assert stats["n_sessions"] == 1


class TestConsolidateProfile:
    @pytest.fixture
    def processed_repo(self, test_repo: Path) -> Path:
        results = process_all(test_repo / "measurements", test_repo)
        assert all(r.error is None for r in results)
        return test_repo

    def test_outputs_written(self, processed_repo: Path):
        outputs = consolidate_profile(processed_repo, "test_cable")

        assert "test_cable_consolidated_json" in outputs
        assert "test_cable_resistance_by_length" in outputs
        assert "test_cable_serdes_by_length" in outputs
        assert "test_cable_vna_by_length" in outputs
        for path in outputs.values():
            assert path.exists()

    def test_resistance_pooled_across_sessions(self, processed_repo: Path):
        outputs = consolidate_profile(processed_repo, "test_cable")

        df = pd.read_csv(outputs["test_cable_resistance_by_length"])
        # Both resistance sessions are at 500mm -> one pooled row
        assert len(df) == 1
        row = df.iloc[0]
        assert row["cable_length_mm"] == 500.0
        assert row["n_sessions"] == 2
        assert row["total_measurements"] == 7  # 4 + 3
        assert row["mean_roundtrip_resistance_ohm_per_m"] > 0
        assert row["std_roundtrip_resistance_ohm_per_m"] >= 0

    def test_serdes_by_length_and_combo(self, processed_repo: Path):
        outputs = consolidate_profile(processed_repo, "test_cable")

        df = pd.read_csv(outputs["test_cable_serdes_by_length"])
        # 2 lengths x 4 combos
        assert len(df) == 8
        assert set(df["cable_length_mm"]) == {500.0, 1000.0}
        assert (df["n_sessions"] == 1).all()
        assert df["mean_eye_area_ratio"].notna().all()
        assert df["mean_link_margin_mv"].notna().all()

    def test_vna_by_length(self, processed_repo: Path):
        outputs = consolidate_profile(processed_repo, "test_cable")

        df = pd.read_csv(outputs["test_cable_vna_by_length"])
        # Both VNA sessions are at 1000mm -> one pooled row
        assert len(df) == 1
        assert df.iloc[0]["n_sessions"] == 2
        # Nested attenuation map stays out of the flat CSV
        assert "attenuation_db_by_hz" not in df.columns

    def test_vna_attenuation_map_pooled(self, processed_repo: Path):
        outputs = consolidate_profile(processed_repo, "test_cable")

        with open(outputs["test_cable_consolidated_json"]) as f:
            consolidated = json.load(f)

        att = consolidated["vna_by_length"][0]["attenuation_db_by_hz"]
        # Pooled across both 1000mm sessions; 750 MHz (FPD-Link III Nyquist)
        # is inside the fixtures' 1 MHz - 1 GHz sweep
        assert "750000000" in att
        assert all(v > 0 for v in att.values())

    def test_consolidated_json_structure(self, processed_repo: Path):
        outputs = consolidate_profile(processed_repo, "test_cable")

        with open(outputs["test_cable_consolidated_json"]) as f:
            consolidated = json.load(f)

        assert consolidated["profile_id"] == "test_cable"
        assert len(consolidated["resistance_by_length"]) == 1
        assert len(consolidated["serdes_by_length"]) == 8
        assert len(consolidated["vna_by_length"]) == 1

    def test_unprocessed_profile_empty(self, test_repo: Path):
        """Without processing, there are no summaries to consolidate."""
        outputs = consolidate_profile(test_repo, "test_cable")
        assert outputs == {}

    def test_unknown_profile_empty(self, test_repo: Path):
        assert consolidate_profile(test_repo, "nonexistent") == {}


class TestConsolidateProfiles:
    def test_all_profiles(self, test_repo: Path):
        process_all(test_repo / "measurements", test_repo)
        outputs = consolidate_profiles(test_repo)
        assert "test_cable_consolidated_json" in outputs

    def test_missing_measurements_dir(self, tmp_path: Path):
        assert consolidate_profiles(tmp_path) == {}
