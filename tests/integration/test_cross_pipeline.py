"""Integration tests: cross-cutting analysis over the fixture tree."""

from pathlib import Path

import pandas as pd
import pytest

from src.analysis.consolidate import consolidate_profiles
from src.analysis.cross import run_cross_analysis
from src.pipeline import process_all


class TestCrossAnalysis:
    @pytest.fixture
    def analyzed_repo(self, test_repo: Path) -> Path:
        results = process_all(test_repo / "measurements", test_repo)
        assert all(r.error is None for r in results)
        consolidate_profiles(test_repo)
        return test_repo

    def test_outputs(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)

        assert "resistivity_summary" in outputs
        assert "supply_voltage_table" in outputs
        assert "supply_voltage_plot_test_miniscope" in outputs
        assert "supply_voltage_plot_test_miniscope_fpd" in outputs
        assert "max_length_summary" in outputs
        assert "quality_scores" in outputs
        assert "quality_vs_length_plot_3g" in outputs
        assert "quality_vs_length_plot_6g" in outputs
        assert "miniscope_quality" in outputs
        assert "miniscope_quality_plot_test_miniscope" in outputs
        assert "miniscope_quality_plot_test_miniscope_fpd" in outputs
        for path in outputs.values():
            assert path.exists()
            assert path.stat().st_size > 0

    def test_resistivity_summary(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        df = pd.read_csv(outputs["resistivity_summary"])

        assert len(df) == 1
        row = df.iloc[0]
        assert row["profile_id"] == "test_cable"
        # Fixture: ~1.2 ohm at 500mm -> ~2.4 ohm/m; single length -> ratio method
        assert 2.0 < row["roundtrip_resistivity_ohm_per_m"] < 3.0
        assert row["method"] == "single_length_ratio"

    def test_supply_voltage_table(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        df = pd.read_csv(outputs["supply_voltage_table"])

        # 2 miniscopes x 1 profile x 2 lengths (500, 1000)
        assert len(df) == 4
        assert set(df["miniscope_model"]) == {"test_miniscope", "test_miniscope_fpd"}
        assert set(df["cable_length_mm"]) == {500.0, 1000.0}
        # Floor below ceiling -> feasible window; fixture sits in the 5 V window
        assert (df["v_supply_min"] < df["v_supply_max"]).all()
        assert df["feasible"].all()
        # Worst-case droop floor grows with length
        scope_df = df[df["miniscope_model"] == "test_miniscope"]
        by_length = scope_df.set_index("cable_length_mm")["v_supply_min"]
        assert by_length[1000.0] > by_length[500.0]

    def test_max_length_summary(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        df = pd.read_csv(outputs["max_length_summary"])

        # 2 miniscopes x 1 profile
        assert len(df) == 2
        assert set(df["miniscope_model"]) == {"test_miniscope", "test_miniscope_fpd"}
        assert (df["profile_id"] == "test_cable").all()
        assert (df["voltage_limited_max_length_mm"] > 0).all()

    def test_miniscope_quality(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        df = pd.read_csv(outputs["miniscope_quality"])

        # GMSL2 fixture scope (6 Gbps is a measured rate) -> measured rows
        gmsl = df[df["miniscope_model"] == "test_miniscope"]
        assert not gmsl.empty
        assert set(gmsl["source"]) == {"measured"}
        assert set(gmsl["rate_gbps"]) == {6.0}
        assert set(gmsl["cable_length_mm"]) == {500.0, 1000.0}

        # FPD-Link III fixture scope (1.5 Gbps unmeasured) -> projected from
        # VNA attenuation at 750 MHz; fixtures only have VNA data at 1000mm
        fpd = df[df["miniscope_model"] == "test_miniscope_fpd"]
        assert not fpd.empty
        assert set(fpd["source"]) == {"projected_from_vna"}
        assert set(fpd["cable_length_mm"]) == {1000.0}
        assert (fpd["attenuation_db"] > 0).all()

        assert (df["quality_score"] >= 0).all()
        assert (df["quality_score"] <= 1).all()
        assert set(df["zone"]).issubset({"works", "marginal", "not_recommended"})

    def test_quality_scores(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        df = pd.read_csv(outputs["quality_scores"])

        # 1 profile x 2 lengths x 2 scored forward rates (3G/6G). The 187.5 Mbps
        # reverse channel is excluded from the quality score (it is low-rate,
        # robust, and never the link bottleneck).
        assert len(df) == 4
        assert set(df["rate_gbps"]) == {3.0, 6.0}
        assert (df["quality_score"] >= 0).all()
        assert (df["quality_score"] <= 1).all()
        assert set(df["zone"]).issubset({"works", "marginal", "not_recommended"})

        # Fixtures degrade with rate: 6 Gbps never scores above 3 Gbps
        pivot = df.pivot_table(index="cable_length_mm", columns="rate_gbps", values="quality_score")
        assert (pivot[6.0] <= pivot[3.0]).all()

    def test_no_link_lane_scores_zero(self, analyzed_repo: Path):
        """A cable that never establishes a link at a rate is scored 0."""
        from datetime import date

        from src.core.session_writer import SessionMeta, write_serdes_session
        from src.instruments.types import FORWARD_6G, SerdesResult
        from src.pipeline import process_session

        # Record a no-link session at a new length: the 6 Gbps forward link never
        # locks. Process it, then re-consolidate and re-run the cross analysis.
        ref = write_serdes_session(
            analyzed_repo,
            "test_cable",
            2000.0,
            SerdesResult(no_link_lanes=[FORWARD_6G]),
            SessionMeta(
                operator="t", date=date.today(), notes="", type_fields={"serdes_device": "x"}
            ),
        )
        assert process_session(ref.path, analyzed_repo).error is None
        consolidate_profiles(analyzed_repo)
        outputs = run_cross_analysis(analyzed_repo)

        df = pd.read_csv(outputs["quality_scores"])
        no_link = df[(df["cable_length_mm"] == 2000.0) & (df["rate_gbps"] == 6.0)]
        assert len(no_link) == 1
        assert no_link.iloc[0]["quality_score"] == 0.0
        assert no_link.iloc[0]["zone"] == "not_recommended"

    def test_commutator_impact(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        assert "commutator_impact" in outputs
        df = pd.read_csv(outputs["commutator_impact"])

        # 1 commutator x 2 miniscopes
        assert set(df["commutator_id"]) == {"test_commutator"}
        assert set(df["miniscope_model"]) == {"test_miniscope", "test_miniscope_fpd"}

        # Fixture series resistance ~0.35 ohm; floor increase = I_max * R
        row = df[df["miniscope_model"] == "test_miniscope"].iloc[0]
        assert row["added_resistance_ohm"] == pytest.approx(0.35, abs=0.01)
        assert row["supply_floor_increase_v"] == pytest.approx(0.3 * 0.35, abs=0.005)

        # FPD scope (750 MHz Nyquist, inside the 1 MHz - 1 GHz sweep) gets a
        # measured added attenuation; the 6 Gbps scope (3 GHz) is outside.
        fpd = df[df["miniscope_model"] == "test_miniscope_fpd"].iloc[0]
        assert fpd["added_attenuation_db"] > 0
        gmsl = df[df["miniscope_model"] == "test_miniscope"].iloc[0]
        assert pd.isna(gmsl["added_attenuation_db"])

    def test_commutator_length_impact(self, analyzed_repo: Path):
        outputs = run_cross_analysis(analyzed_repo)
        assert "commutator_length_impact" in outputs
        df = pd.read_csv(outputs["commutator_length_impact"])

        # 1 commutator x 1 cable; reduction = R_comm / rho
        assert len(df) == 1
        row = df.iloc[0]
        assert row["profile_id"] == "test_cable"
        # rho ~2.4 ohm/m, R ~0.35 ohm -> ~146 mm of cable budget
        assert 100 < row["max_length_reduction_mm"] < 200

    def test_commutator_excluded_from_cable_outputs(self, analyzed_repo: Path):
        """Commutators must not leak into the cable-centric tables."""
        outputs = run_cross_analysis(analyzed_repo)
        for key in ["resistivity_summary", "supply_voltage_table", "quality_scores"]:
            df = pd.read_csv(outputs[key])
            assert "test_commutator" not in set(df["profile_id"])

    def test_no_consolidated_data(self, test_repo: Path):
        """Without processing/consolidation there is nothing to analyze."""
        assert run_cross_analysis(test_repo) == {}
