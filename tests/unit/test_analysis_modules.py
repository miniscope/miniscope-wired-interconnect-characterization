"""Tests for analysis config, resistivity fit, supply voltage, and quality score."""

from pathlib import Path

import pytest

from src.analysis.config import load_analysis_config
from src.analysis.quality_score import QualityInputs, score, zone
from src.analysis.resistivity import fit_resistivity
from src.analysis.supply_voltage import required_supply_v, supply_voltage_rows
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
    def test_required_supply_v(self):
        # 3.3 V min + 300 mA * 2 ohm/m * 1 m = 3.9 V; round-trip rho, no x2
        v = required_supply_v(3.3, 300.0, 2.0, 1.0)
        assert v == pytest.approx(3.9)

    def test_rows(self):
        scope = MiniscopeModel(
            schema_version="1.0",
            model_id="test_scope",
            min_operating_voltage_v=3.3,
            baseline_current_ma=150.0,
            max_current_ma=300.0,
        )
        rows = supply_voltage_rows(scope, "test_cable", 2.0, [1000.0, 500.0])
        assert len(rows) == 2
        assert rows[0]["cable_length_mm"] == 500.0  # sorted
        row_1m = rows[1]
        assert row_1m["min_supply_v_baseline"] == pytest.approx(3.6)
        assert row_1m["min_supply_v_max_load"] == pytest.approx(3.9)
        assert row_1m["min_supply_v_max_load"] > row_1m["min_supply_v_baseline"]

    def test_missing_power_fields_returns_empty(self):
        scope = MiniscopeModel(schema_version="1.0", model_id="no_power")
        assert supply_voltage_rows(scope, "test_cable", 2.0, [500.0]) == []


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
        """With only eye area available, score == eye area sub-score."""
        inputs = QualityInputs(eye_area_ratio=0.5)
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
