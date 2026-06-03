"""Tests for the instrument layer: simulators, orchestration, registry, s2p."""

from pathlib import Path

import numpy as np
import pytest

from src.instruments import ProgressEvent, SerdesChannel, SerdesRate
from src.instruments.lcr.driver import validate_reading
from src.instruments.registry import HARDWARE_ENV_VAR, get_serdes_driver, get_vna_driver
from src.instruments.serdes.driver import SerdesConfig
from src.instruments.serdes.simulator import SimulatedSerdesDriver
from src.instruments.vna.driver import VnaConfig, write_s2p
from src.instruments.vna.simulator import SimulatedVnaDriver
from src.processing.touchstone import parse_s2p


class TestSimulatedSerdesDriver:
    @pytest.fixture
    def driver(self) -> SimulatedSerdesDriver:
        driver = SimulatedSerdesDriver(cable_length_mm=1000.0, seed=42)
        driver.connect()
        return driver

    def test_link_status(self, driver):
        status = driver.link_status()
        assert status["connected"] is True
        assert status["simulated"] is True

    def test_capture_eye_shape(self, driver):
        config = SerdesConfig(eye_voltage_bins=32, eye_time_bins=48)
        eye = driver.capture_eye(SerdesChannel.FORWARD, SerdesRate.GBPS_3, config)
        assert eye.error_counts.shape == (32, 48)
        assert eye.error_counts.dtype == np.int64
        assert eye.voltage_range_mv[1] > eye.voltage_range_mv[0]

    def test_eye_has_open_center(self, driver):
        eye = driver.capture_eye(SerdesChannel.FORWARD, SerdesRate.GBPS_3, SerdesConfig())
        v, t = eye.error_counts.shape
        assert eye.error_counts[v // 2, t // 2] == 0

    def test_deterministic_with_seed(self):
        a = SimulatedSerdesDriver(seed=7).capture_eye(
            SerdesChannel.FORWARD, SerdesRate.GBPS_3, SerdesConfig()
        )
        b = SimulatedSerdesDriver(seed=7).capture_eye(
            SerdesChannel.FORWARD, SerdesRate.GBPS_3, SerdesConfig()
        )
        np.testing.assert_array_equal(a.error_counts, b.error_counts)

    def test_six_gbps_worse_than_three(self, driver):
        config = SerdesConfig()
        eye3 = driver.capture_eye(SerdesChannel.FORWARD, SerdesRate.GBPS_3, config)
        eye6 = driver.capture_eye(SerdesChannel.FORWARD, SerdesRate.GBPS_6, config)
        # More zero (open) cells at 3 Gbps
        assert (eye3.error_counts == 0).sum() > (eye6.error_counts == 0).sum()

    def test_margin_sweep_structure(self, driver):
        config = SerdesConfig()
        sweep = driver.sweep_margin(SerdesChannel.FORWARD, SerdesRate.GBPS_3, config)

        amps = [p.tx_amplitude_mv for p in sweep.points]
        assert amps == sorted(amps)
        assert min(amps) >= config.margin_min_mv
        assert max(amps) <= config.margin_max_mv

        # Coarse + fine: some adjacent points 1 mV apart, the sweep spans the range
        diffs = np.diff(amps)
        assert (np.abs(diffs - config.margin_fine_step_mv) < 1e-9).any()

        # Errors at low amplitude, none at high amplitude
        assert sweep.points[0].error_count > 0
        assert sweep.points[-1].error_count == 0

    def test_run_full_sequence(self, driver):
        events: list[ProgressEvent] = []
        result = driver.run_full_sequence(progress=events.append)

        assert len(result.eyes) == 4
        assert len(result.margins) == 4
        combos = {(e.channel, e.rate) for e in result.eyes}
        assert combos == {
            (SerdesChannel.FORWARD, SerdesRate.GBPS_3),
            (SerdesChannel.FORWARD, SerdesRate.GBPS_6),
            (SerdesChannel.BACK, SerdesRate.GBPS_3),
            (SerdesChannel.BACK, SerdesRate.GBPS_6),
        }

        # Progress: 8 events (eye + margin per combo), monotone, ends at 1.0
        assert len(events) == 8
        fractions = [e.fraction for e in events]
        assert fractions == sorted(fractions)
        assert fractions[-1] == pytest.approx(1.0)
        # Live-preview partials attached
        assert all(e.partial is not None for e in events)


class TestSimulatedVnaDriver:
    def test_sweep_shape(self):
        driver = SimulatedVnaDriver(cable_length_mm=1000.0)
        driver.connect()
        config = VnaConfig(num_points=101)
        result = driver.sweep(config)

        assert len(result.frequencies_hz) == 101
        assert len(result.s21) == 101
        assert np.iscomplexobj(result.s21)

    def test_is_calibrated(self):
        assert SimulatedVnaDriver().is_calibrated() is True

    def test_attenuation_grows_with_frequency(self):
        result = SimulatedVnaDriver(cable_length_mm=1000.0).sweep(VnaConfig(num_points=51))
        mags = np.abs(result.s21)
        assert mags[-1] < mags[0]

    def test_longer_cable_more_loss(self):
        config = VnaConfig(num_points=11)
        short = SimulatedVnaDriver(cable_length_mm=500.0).sweep(config)
        long = SimulatedVnaDriver(cable_length_mm=2000.0).sweep(config)
        assert np.abs(long.s21).mean() < np.abs(short.s21).mean()


class TestWriteS2p:
    def test_roundtrip_through_parser(self, tmp_path: Path):
        driver = SimulatedVnaDriver(cable_length_mm=1000.0)
        result = driver.sweep(VnaConfig(num_points=21))

        s2p_path = tmp_path / "sweep.s2p"
        write_s2p(result, s2p_path)

        ts = parse_s2p(s2p_path)
        assert ts.num_points == 21
        assert ts.format_type == "RI"
        assert ts.ref_impedance == 50.0
        np.testing.assert_allclose(ts.frequencies_hz, result.frequencies_hz, rtol=1e-9)

        expected_s21_db = 20 * np.log10(np.abs(result.s21))
        np.testing.assert_allclose(ts.s21_db, expected_s21_db, atol=1e-6)


class TestRegistry:
    def test_default_is_simulator(self, monkeypatch):
        monkeypatch.delenv(HARDWARE_ENV_VAR, raising=False)
        assert isinstance(get_serdes_driver(), SimulatedSerdesDriver)
        assert isinstance(get_vna_driver(), SimulatedVnaDriver)

    def test_explicit_simulate_true(self, monkeypatch):
        monkeypatch.setenv(HARDWARE_ENV_VAR, "1")
        # Explicit argument wins over the environment
        assert isinstance(get_serdes_driver(simulate=True), SimulatedSerdesDriver)

    def test_env_selects_real(self, monkeypatch):
        from src.instruments.serdes.i2c import NullI2C
        from src.instruments.serdes.real import RealSerdesDriver
        from src.instruments.vna.real import RealPicoVnaDriver

        monkeypatch.setenv(HARDWARE_ENV_VAR, "1")
        assert isinstance(get_serdes_driver(transport=NullI2C()), RealSerdesDriver)
        assert isinstance(get_vna_driver(), RealPicoVnaDriver)

    def test_real_drivers_not_implemented_yet(self):
        from src.instruments.serdes.i2c import NullI2C

        driver = get_serdes_driver(simulate=False, transport=NullI2C())
        with pytest.raises(NotImplementedError):
            driver.connect()


class TestValidateReading:
    def test_valid(self):
        validate_reading(1.2)  # no exception

    def test_negative(self):
        with pytest.raises(ValueError, match="positive"):
            validate_reading(-1.0)

    def test_zero(self):
        with pytest.raises(ValueError, match="positive"):
            validate_reading(0)

    def test_nan(self):
        with pytest.raises(ValueError, match="NaN"):
            validate_reading(float("nan"))

    def test_implausibly_large(self):
        with pytest.raises(ValueError, match="implausibly large"):
            validate_reading(1e6)
