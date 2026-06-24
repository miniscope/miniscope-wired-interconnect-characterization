"""Tests for analysis config, resistivity fit, supply voltage, and quality score."""

from pathlib import Path

import pytest

from src.analysis.config import load_analysis_config
from src.analysis.projection import attenuation_at_hz, nyquist_hz
from src.analysis.quality_score import QualityInputs, score, zone
from src.analysis.resistivity import fit_resistivity
from src.analysis.supply_voltage import (
    max_length_at_supply_v,
    required_supply_v,
    supply_voltage_rows,
    supply_window,
)
from src.core.model_schemas import MiniscopeModel

REPO_CONFIG = Path("config/analysis.yaml")


@pytest.fixture
def config():
    return load_analysis_config(REPO_CONFIG)


class TestAnalysisConfig:
    def test_loads_repo_config(self, config):
        assert config.zones.works > config.zones.marginal
        assert set(config.serdes_rates_gbps) == {3, 6}
        assert config.quality_score.weights.eye_area > 0
        # Supply is a user/DAQ-side choice: the reporting reference lives
        # here, not on any miniscope model
        assert config.reference_supply_v == 5.0


class TestFitResistivity:
    def test_no_data(self):
        assert fit_resistivity([], []) is None

    def test_single_length(self):
        fit = fit_resistivity([500.0], [2.4])
        assert fit is not None
        assert fit.method == "single_length_ratio"
        assert fit.roundtrip_resistivity_ohm_per_m == pytest.approx(2.4)
        assert fit.intercept_ohm is None
        assert fit.n_lengths == 1

    def test_linear_fit_recovers_slope_and_intercept(self):
        """R(L) = 2.0 * L + 0.1 -> per-meter values include the intercept."""
        rho, r0 = 2.0, 0.1
        lengths_mm = [500.0, 1000.0, 2000.0]
        per_m = [(rho * (length / 1000.0) + r0) / (length / 1000.0) for length in lengths_mm]

        fit = fit_resistivity(lengths_mm, per_m)
        assert fit.method == "linear_fit"
        assert fit.roundtrip_resistivity_ohm_per_m == pytest.approx(rho, abs=1e-6)
        assert fit.intercept_ohm == pytest.approx(r0, abs=1e-6)
        assert fit.r_squared == pytest.approx(1.0)
        assert fit.n_lengths == 3

    def test_none_values_filtered(self):
        fit = fit_resistivity([500.0, 1000.0], [2.4, None])
        assert fit.method == "single_length_ratio"


class TestSupplyVoltage:
    REFERENCE_V = 5.0  # the USB rail; an analysis convention, not a model field

    def _scope(self, **overrides) -> MiniscopeModel:
        params = dict(
            schema_version="1.0",
            model_id="test_scope",
            min_operating_voltage_v=3.3,
            max_operating_voltage_v=5.5,
            min_current_ma=20.0,
            baseline_current_ma=150.0,
            max_current_ma=300.0,
            poc_dcr_supply_ohm=0.05,
            poc_dcr_receive_ohm=0.05,
        )
        params.update(overrides)
        return MiniscopeModel(**params)

    def test_required_supply_v(self):
        # 3.3 V min + 300 mA * 2 ohm/m * 1 m = 3.9 V; round-trip rho, no x2
        v = required_supply_v(3.3, 300.0, 2.0, 1.0)
        assert v == pytest.approx(3.9)

    def test_window_floor_and_ceiling(self):
        # R_chain = 0.05 + 2.0*1.0 + 0.05 = 2.1 ohm
        # floor   = 3.3 + 0.300*2.1 = 3.93 V ; ceiling = 5.5 + 0.020*2.1 = 5.542 V
        w = supply_window(self._scope(), 2.0, 1.0, self.REFERENCE_V)
        assert w is not None
        assert w.r_chain_ohm == pytest.approx(2.1)
        assert w.v_supply_min == pytest.approx(3.93)
        assert w.v_supply_max == pytest.approx(5.542)
        assert w.feasible is True
        assert w.reference_supply_ok is True  # 3.93 <= 5.0 <= 5.542

    def test_window_infeasible_when_floor_exceeds_ceiling(self):
        # Huge current + tiny Vmax headroom -> empty window
        scope = self._scope(max_operating_voltage_v=3.4, max_current_ma=2000.0)
        w = supply_window(scope, 5.0, 2.0, self.REFERENCE_V)
        assert w.feasible is False
        assert w.reference_supply_ok is False

    def test_window_no_ceiling_when_vmax_missing(self):
        scope = self._scope(max_operating_voltage_v=None)
        w = supply_window(scope, 2.0, 1.0, self.REFERENCE_V)
        assert w.v_supply_max is None
        assert w.feasible is True  # floor-only

    def test_rows_columns_and_growth(self):
        rows = supply_voltage_rows(
            self._scope(), "test_cable", 2.0, [1000.0, 500.0], self.REFERENCE_V
        )
        assert len(rows) == 2
        assert rows[0]["cable_length_mm"] == 500.0  # sorted
        assert rows[1]["v_supply_min"] > rows[0]["v_supply_min"]  # longer -> more droop
        row = rows[1]
        assert row["r_chain_ohm"] == pytest.approx(2.1)
        assert row["v_supply_min"] == pytest.approx(3.93)
        assert row["feasible"] is True
        assert row["reference_supply_v"] == self.REFERENCE_V
        assert row["reference_supply_ok"] is True

    def test_max_length_at_reference(self):
        # headroom = 5.0 - 3.3 = 1.7 V ; R_chain budget = 1.7/0.3 = 5.6667 ohm
        # cable budget = 5.6667 - 0.1 = 5.5667 ohm ; length = 5.5667/2.0 m = 2.7833 m
        length_mm = max_length_at_supply_v(self._scope(), 2.0, self.REFERENCE_V)
        assert length_mm == pytest.approx(2783.3, abs=0.5)

    def test_max_length_zero_when_supply_below_dropout(self):
        assert max_length_at_supply_v(self._scope(), 2.0, 3.0) == 0.0  # < 3.3 V dropout

    def test_missing_power_fields_returns_empty(self):
        scope = MiniscopeModel(schema_version="1.0", model_id="no_power")
        assert supply_voltage_rows(scope, "test_cable", 2.0, [500.0], self.REFERENCE_V) == []
        assert supply_window(scope, 2.0, 1.0, self.REFERENCE_V) is None
        assert max_length_at_supply_v(scope, 2.0, self.REFERENCE_V) is None


class TestProjection:
    def test_nyquist(self):
        assert nyquist_hz(1.5) == pytest.approx(750e6)
        assert nyquist_hz(6.0) == pytest.approx(3e9)

    def test_interpolates_between_points(self):
        att = {"100000000": 1.0, "1000000000": 4.0}  # 1 dB @ 100 MHz, 4 dB @ 1 GHz
        # Linear midpoint at 550 MHz
        assert attenuation_at_hz(att, 550e6) == pytest.approx(2.5)

    def test_exact_point(self):
        att = {"750000000": 3.2, "1000000000": 4.0}
        assert attenuation_at_hz(att, 750e6) == pytest.approx(3.2)

    def test_never_extrapolates(self):
        att = {"100000000": 1.0, "1000000000": 4.0}
        assert attenuation_at_hz(att, 3e9) is None  # above the sweep
        assert attenuation_at_hz(att, 1e6) is None  # below the sweep

    def test_empty_map(self):
        assert attenuation_at_hz({}, 750e6) is None

    def test_numeric_keys_accepted(self):
        assert attenuation_at_hz({1e8: 1.0, 1e9: 4.0}, 1e9) == pytest.approx(4.0)


class TestQualityScore:
    def test_perfect_inputs(self, config):
        inputs = QualityInputs(eye_area_ratio=1.0, link_margin_mv=0.0, attenuation_db=0.0)
        assert score(inputs, config) == pytest.approx(1.0)

    def test_terrible_inputs(self, config):
        refs = config.quality_score.references
        inputs = QualityInputs(
            eye_area_ratio=0.0,
            link_margin_mv=refs.link_margin_full_scale_mv,
            attenuation_db=refs.attenuation_full_scale_db,
        )
        assert score(inputs, config) == pytest.approx(0.0)

    def test_missing_metrics_renormalized(self, config):
        """With only eye area available, score == eye area sub-score.

        The eye sub-score normalizes by eye_area_full_scale, so an eye filling
        half the full-scale ratio yields a sub-score (and thus a score) of 0.5.
        """
        half_open = 0.5 * config.quality_score.references.eye_area_full_scale
        inputs = QualityInputs(eye_area_ratio=half_open)
        assert score(inputs, config) == pytest.approx(0.5)

    def test_no_metrics_returns_none(self, config):
        assert score(QualityInputs(), config) is None

    def test_out_of_range_clamped(self, config):
        inputs = QualityInputs(
            eye_area_ratio=2.0,
            link_margin_mv=10 * config.quality_score.references.link_margin_full_scale_mv,
        )
        value = score(inputs, config)
        assert 0.0 <= value <= 1.0

    def test_zones(self, config):
        assert zone(config.zones.works, config) == "works"
        assert zone(config.zones.marginal, config) == "marginal"
        assert zone(config.zones.marginal - 0.01, config) == "not_recommended"


class TestQualityTableLinkStates:
    """How _quality_table treats no-link vs linked-but-uncharacterized lanes."""

    def _serdes_row(self, rate, *, linked, eye=None, margin=None):
        return {
            "cable_length_mm": 1000.0,
            "channel": "forward",
            "rate_gbps": rate,
            "linked": linked,
            "mean_eye_area_ratio": eye,
            "mean_link_margin_mv": margin,
        }

    def test_no_link_rate_scored_zero(self, config):
        from src.analysis.cross import _quality_table

        consolidated = {
            "c": {"serdes_by_length": [self._serdes_row(6.0, linked=False)], "vna_by_length": []}
        }
        df = _quality_table(consolidated, config)
        row = df[(df["cable_length_mm"] == 1000.0) & (df["rate_gbps"] == 6.0)].iloc[0]
        assert row["quality_score"] == 0.0
        assert row["zone"] == "not_recommended"

    def test_linked_but_uncharacterized_dropped_even_with_vna(self, config):
        """A linked lane with no eye/margin is not scored from attenuation alone."""
        from src.analysis.cross import _quality_table

        consolidated = {
            "c": {
                "serdes_by_length": [self._serdes_row(3.0, linked=True)],  # null eye + margin
                "vna_by_length": [
                    {
                        "cable_length_mm": 1000.0,
                        # spans the 3 Gbps Nyquist (1.5 GHz)
                        "attenuation_db_by_hz": {"1000000000": 1.0, "2000000000": 2.0},
                    }
                ],
            }
        }
        df = _quality_table(consolidated, config)
        # The only lane is dropped (no eye/margin), so no measured row at all.
        assert df.empty
