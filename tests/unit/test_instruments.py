"""Tests for the instrument layer: simulators, orchestration, registry, s2p."""

from pathlib import Path

import numpy as np
import pytest

from src.instruments import (
    DEFAULT_LANES,
    FORWARD_3G,
    FORWARD_6G,
    REVERSE_187M,
    ProgressEvent,
    SerdesRate,
)
from src.instruments.lcr.driver import validate_reading
from src.instruments.registry import (
    HARDWARE_ENV_VAR,
    get_serdes_driver,
    get_vna_driver,
    use_hardware,
)
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

    def test_capture_eye_grid(self, driver):
        config = SerdesConfig(eye_bins=16)
        eye = driver.capture_eye(FORWARD_3G, config)
        # One row per (phase, vth, polarity); parallel arrays of equal length.
        n = len(eye.phase)
        assert n > 0
        assert len(eye.vth) == len(eye.polarity) == len(eye.hits) == len(eye.errors) == n
        assert eye.phase.dtype == np.int64
        assert eye.phase.max() <= 127
        assert eye.vth.max() <= 63
        assert set(np.unique(eye.polarity)).issubset({0, 1})

    def test_eye_has_open_center(self, driver):
        eye = driver.capture_eye(FORWARD_3G, SerdesConfig(eye_bins=16))
        # The smallest vth at mid phase should be error-free (eye center).
        center = (np.abs(eye.phase - 64) < 8) & (eye.vth == eye.vth.min())
        assert (eye.errors[center] == 0).any()

    def test_deterministic_with_seed(self):
        cfg = SerdesConfig(eye_bins=16)
        a = SimulatedSerdesDriver(seed=7).capture_eye(FORWARD_3G, cfg)
        b = SimulatedSerdesDriver(seed=7).capture_eye(FORWARD_3G, cfg)
        np.testing.assert_array_equal(a.errors, b.errors)

    def test_six_gbps_worse_than_three(self, driver):
        cfg = SerdesConfig(eye_bins=16)
        eye3 = driver.capture_eye(FORWARD_3G, cfg)
        eye6 = driver.capture_eye(FORWARD_6G, cfg)
        # More zero-error (open) cells at 3 Gbps
        assert (eye3.errors == 0).sum() > (eye6.errors == 0).sum()

    def test_margin_sweep_structure(self, driver):
        sweep = driver.sweep_margin(FORWARD_3G, SerdesConfig())

        amps = [p.tx_amplitude_mv for p in sweep.points]
        # Sweep descends from the start amplitude.
        assert amps == sorted(amps, reverse=True)
        # Raw fields are present.
        assert all(
            p.status in {"ok", "errors", "lost_lock", "ser_unreachable"} for p in sweep.points
        )
        # Errors appear at the low-amplitude end, none at the high-amplitude start.
        assert sweep.points[0].errors == 0
        assert sweep.points[-1].errors > 0

    def test_run_full_sequence(self, driver):
        events: list[ProgressEvent] = []
        result = driver.run_full_sequence(config=SerdesConfig(eye_bins=16), progress=events.append)

        assert len(result.eyes) == 3
        assert len(result.margins) == 3
        assert {e.lane for e in result.eyes} == set(DEFAULT_LANES)
        assert REVERSE_187M.rate is SerdesRate.MBPS_187

        # Progress: 6 events (eye + margin per lane), monotone, ends at 1.0
        assert len(events) == 6
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


class TestRealPicoVnaDriverDemo:
    """
    Exercises the real PicoVNA 5 driver against the SDK's demo device.

    Skips when the `vna` package isn't installed (e.g. CI), so it runs only
    on a machine with the PicoVNA 5 SDK present -- no hardware required.
    """

    def test_demo_sweep(self):
        pytest.importorskip("vna")
        from src.instruments.vna.real import RealPicoVnaDriver

        driver = RealPicoVnaDriver(demo=True)
        driver.connect()
        try:
            assert driver.is_calibrated() is True
            result = driver.sweep(VnaConfig(num_points=51))
            assert len(result.frequencies_hz) == 51
            assert np.iscomplexobj(result.s21)
            assert result.instrument_info["demo"] == "true"
        finally:
            driver.close()

    def test_module_imports_without_sdk(self):
        """Importing/constructing the driver must not require the SDK."""
        from src.instruments.vna.real import RealPicoVnaDriver

        driver = RealPicoVnaDriver(demo=True)  # no connect() -> no vendor import
        assert driver.is_calibrated() is False  # not connected yet


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

    def test_real_serdes_connect_rejects_wrong_ids(self):
        # NullI2C returns 0x00 for every register, so connect() must fail the
        # device-ID handshake rather than silently proceed.
        from src.instruments.serdes.i2c import NullI2C
        from src.instruments.serdes.real import RealSerdesDriver

        driver = RealSerdesDriver(transport=NullI2C())
        with pytest.raises(RuntimeError):
            driver.connect()

    def test_use_hardware_precedence(self, monkeypatch):
        # explicit arg > env var > default(simulator)
        monkeypatch.delenv(HARDWARE_ENV_VAR, raising=False)
        assert use_hardware(None) is False  # default
        assert use_hardware(False) is True  # explicit "not simulated"
        assert use_hardware(True) is False

        monkeypatch.setenv(HARDWARE_ENV_VAR, "1")
        assert use_hardware(None) is True  # env opts in
        assert use_hardware(True) is False  # explicit arg still wins


class TestSerialPorts:
    """list_serial_ports() drives the acquisition app's port picker."""

    def test_maps_and_sorts_by_device(self, monkeypatch):
        pytest.importorskip("serial")
        from types import SimpleNamespace

        from serial.tools import list_ports

        from src.instruments.serdes.pico_bridge import SerialPortInfo, list_serial_ports

        fake = [
            SimpleNamespace(device="COM5", description="USB Serial Device (COM5)"),
            SimpleNamespace(device="COM3", description="Pico"),
        ]
        monkeypatch.setattr(list_ports, "comports", lambda: fake)
        assert list_serial_ports() == [
            SerialPortInfo("COM3", "Pico"),
            SerialPortInfo("COM5", "USB Serial Device (COM5)"),
        ]

    def test_empty_when_no_ports(self, monkeypatch):
        pytest.importorskip("serial")
        from serial.tools import list_ports

        from src.instruments.serdes.pico_bridge import list_serial_ports

        monkeypatch.setattr(list_ports, "comports", lambda: [])
        assert list_serial_ports() == []

    def test_description_falls_back_to_device(self, monkeypatch):
        pytest.importorskip("serial")
        from types import SimpleNamespace

        from serial.tools import list_ports

        from src.instruments.serdes.pico_bridge import list_serial_ports

        monkeypatch.setattr(
            list_ports, "comports", lambda: [SimpleNamespace(device="COM9", description="")]
        )
        assert list_serial_ports()[0].description == "COM9"


class TestRealSerdesDemo:
    """The real driver's ported algorithms run end to end against DemoBridge."""

    def test_demo_link_status_decodes_parts_and_rate(self):
        from src.instruments.serdes.real import RealSerdesDriver

        driver = RealSerdesDriver(demo=True)
        driver.connect()
        status = driver.link_status()
        driver.close()

        assert status["forward_rate"] == "6 Gbps"
        assert status["ser"]["part"] == "MAX96717"
        assert status["ser"]["device_id"] == 0xBF
        assert status["des"]["part"] == "MAX96716A"
        assert status["des"]["device_id"] == 0xBE
        assert status["ser"]["locked"] and status["des"]["locked"]
        assert not status["ser"]["error"] and not status["des"]["error"]

    def test_demo_roundtrip(self):
        from src.instruments.serdes.real import RealSerdesDriver

        driver = RealSerdesDriver(demo=True)
        driver.connect()
        assert driver.link_status()["demo"] is True

        result = driver.run_full_sequence(config=SerdesConfig(eye_bins=8))
        driver.close()

        assert {e.lane for e in result.eyes} == set(DEFAULT_LANES)
        for eye in result.eyes:
            # A real, open eye: some zero-error cells and some closed ones.
            assert (eye.errors == 0).any()
            assert (eye.errors > 0).any()
        for sweep in result.margins:
            assert sweep.points  # the sweep produced points
            assert sweep.points[0].errors == 0  # clean at the high-amplitude start

    def test_full_sequence_recovers_from_post_reset_nak(self):
        """capture_eye() leaves both chips mid-RESET_ALL, so the margin phase's
        first register access can NAK while they re-lock. The sequence must
        recover instead of aborting (regression for the real-hardware i2c error
        seen between the eye and margin steps)."""
        from src.instruments.serdes import registers as R
        from src.instruments.serdes.demo_bridge import DemoBridge
        from src.instruments.serdes.real import RealSerdesDriver

        class FlakyAfterReset:
            """DemoBridge that NAKs the first serializer read after the first
            RESET_ALL -- mimics real silicon briefly going unresponsive."""

            def __init__(self) -> None:
                self._inner = DemoBridge()
                self._armed = False
                self._fired = False

            def read(self, dev: int, reg: int, length: int = 1) -> bytes:
                if self._armed and not self._fired and dev == R.SER_ADDR:
                    self._armed = False
                    self._fired = True
                    raise OSError("simulated post-reset NAK (ERR i2c_5)")
                return self._inner.read(dev, reg, length)

            def write(self, dev: int, reg: int, data: bytes) -> None:
                if (
                    not self._fired
                    and dev == R.SER_ADDR
                    and reg == R.REG_CTRL0
                    and data
                    and (data[0] & 0x80)  # RESET_ALL
                ):
                    self._armed = True
                self._inner.write(dev, reg, data)

            def close(self) -> None:
                self._inner.close()

        driver = RealSerdesDriver(transport=FlakyAfterReset(), demo=True)
        driver.connect()
        result = driver.run_full_sequence(config=SerdesConfig(eye_bins=8))
        driver.close()

        assert len(result.eyes) == 3
        assert len(result.margins) == 3


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
