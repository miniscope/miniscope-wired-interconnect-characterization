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

    def test_link_locks_models_per_rate_failure(self):
        """Short cables lock at both rates; a long cable fails to lock at 6 Gbps."""
        short = SimulatedSerdesDriver(cable_length_mm=1000.0)
        assert short.link_locks(FORWARD_3G) is True
        assert short.link_locks(FORWARD_6G) is True

        long = SimulatedSerdesDriver(cable_length_mm=2500.0)
        assert long.link_locks(FORWARD_3G) is True  # 3G stays robust
        assert long.link_locks(REVERSE_187M) is True  # reverse control channel robust
        assert long.link_locks(FORWARD_6G) is False  # 6G too lossy to acquire

    def test_run_full_sequence_records_no_link_lane(self):
        """A lane that won't lock is recorded as no-link, with no eye/margin."""
        driver = SimulatedSerdesDriver(cable_length_mm=2500.0)
        events: list[ProgressEvent] = []
        result = driver.run_full_sequence(config=SerdesConfig(eye_bins=16), progress=events.append)

        assert result.no_link_lanes == [FORWARD_6G]
        assert {e.lane for e in result.eyes} == {FORWARD_3G, REVERSE_187M}
        assert all(m.lane is not FORWARD_6G for m in result.margins)
        # Progress still advances cleanly to 1.0, and the skipped lane is announced.
        assert events[-1].fraction == pytest.approx(1.0)
        assert any(e.stage == "nolink:fwd_6g" for e in events)

    def test_margin_iterations_repeat_only_the_sweep(self, driver):
        """N margin iterations -> 1 eye + N margins per lane; progress stays sane."""
        events: list[ProgressEvent] = []
        result = driver.run_full_sequence(
            config=SerdesConfig(eye_bins=16, margin_iterations=3), progress=events.append
        )

        # Eye captured once per lane, margin swept three times per lane.
        assert len(result.eyes) == 3
        assert len(result.margins) == 9
        for lane in DEFAULT_LANES:
            assert sum(m.lane == lane for m in result.margins) == 3

        # 3 lanes x (1 eye + 3 margins) = 12 events, monotone, ending at 1.0.
        assert len(events) == 12
        fractions = [e.fraction for e in events]
        assert fractions == sorted(fractions)
        assert fractions[-1] == pytest.approx(1.0)
        # Repeated sweeps carry a per-run stage tag for the live preview.
        margin_stages = [e.stage for e in events if e.stage.startswith("margin:")]
        assert f"margin:{FORWARD_6G.lane_id}#1" in margin_stages
        assert f"margin:{FORWARD_6G.lane_id}#3" in margin_stages


class TestSerdesDisplayLabels:
    def test_rate_label_gbps_and_mbps(self):
        from src.instruments.types import rate_label

        assert rate_label(3.0) == "3 Gbps"
        assert rate_label(6.0) == "6 Gbps"
        assert rate_label(0.1875) == "187.5 Mbps"

    def test_rate_display_matches_rate_label(self):
        assert SerdesRate.GBPS_6.display == "6 Gbps"
        assert SerdesRate.MBPS_187.display == "187.5 Mbps"

    def test_channel_and_lane_display(self):
        from src.instruments.types import SerdesChannel

        assert SerdesChannel.FORWARD.display == "Forward"
        assert SerdesChannel.REVERSE.display == "Reverse"
        assert FORWARD_3G.label == "Forward 3 Gbps"
        assert REVERSE_187M.label == "Reverse 187.5 Mbps"


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


class _FakeScpi:
    """Canned PicoVNA SCPI server for driver tests (no socket, no hardware).

    Answers the handful of commands RealPicoVnaDriver issues for a sweep so the
    acquire -> VnaSweepResult path can be exercised without a real server.
    """

    def __init__(self, npoints: int = 51) -> None:
        self.n = npoints
        self.commands: list[str] = []
        self.closed = False

    def query(self, cmd: str) -> str:
        self.commands.append(cmd)
        c = cmd.strip().upper()
        return {
            "*IDN?": "PicoTech,PicoVNA 106,10080,5.3.1",
            "SENSE:FREQUENCY:START?": "0.3 MHz",
            "SENSE:FREQUENCY:STOP?": "6000 MHz",
            "SENSE:SWEEP:POINTS?": str(self.n),
        }.get(c, "OK")

    def query_ascii_values(self, cmd: str) -> list[float]:
        self.commands.append(cmd)
        # Real part 0.1, imag part 0.2 -> a non-trivial complex value.
        return [0.2 if cmd.strip().upper().endswith("IMAG") else 0.1] * self.n

    def close(self) -> None:
        self.closed = True


class TestRealPicoVnaDriverScpi:
    """Exercises the SCPI driver against a fake transport -- no hardware/server."""

    def test_sweep_via_scpi_transport(self):
        from src.instruments.vna.real import RealPicoVnaDriver

        fake = _FakeScpi(npoints=51)
        driver = RealPicoVnaDriver(transport=fake)
        driver.connect()
        try:
            assert driver.is_calibrated() is True
            result = driver.sweep(VnaConfig(num_points=51))

            assert len(result.frequencies_hz) == 51
            assert len(result.s21) == 51
            assert np.iscomplexobj(result.s21)
            # Complex value reconstructed from REAL (0.1) + IMAG (0.2j).
            assert result.s21[0] == pytest.approx(0.1 + 0.2j)
            # Axis reconstructed from START/STOP/POINTS, with MHz units honoured.
            assert result.frequencies_hz[0] == pytest.approx(0.3e6)
            assert result.frequencies_hz[-1] == pytest.approx(6e9)
            assert result.instrument_info["transport"] == "scpi"
            assert "PicoVNA 106" in result.instrument_info["instrument"]
        finally:
            driver.close()
        # Connecting set the ASCII format and triggered a sweep.
        assert "FORMAT ASCII" in fake.commands
        assert "INIT" in fake.commands
        # Released the transport: no longer reports ready.
        assert driver.is_calibrated() is False

    def test_construct_without_server(self):
        """Constructing the driver must not open a socket or launch a server."""
        from src.instruments.vna.real import RealPicoVnaDriver

        driver = RealPicoVnaDriver()  # no connect() -> no socket / no launch
        assert driver.is_calibrated() is False  # not connected yet

    def test_applies_calibration_file(self, tmp_path):
        """A .cal path is loaded over SCPI (MMEM:CD + MMEM:APPLY:CAL) on connect."""
        from src.instruments.vna.real import RealPicoVnaDriver

        cal = tmp_path / "myunit.cal"
        cal.write_text("dummy cal")
        fake = _FakeScpi()
        driver = RealPicoVnaDriver(transport=fake, calibration_file=str(cal))
        driver.connect()
        try:
            assert any(c.startswith("MMEM:CD") for c in fake.commands)
            assert any("MMEM:APPLY:CAL" in c and "myunit.cal" in c for c in fake.commands)
            result = driver.sweep(VnaConfig())
            assert result.instrument_info["calibration"] == "user"
            assert result.instrument_info["calibration_file"] == "myunit.cal"
        finally:
            driver.close()

    def test_missing_calibration_file_raises(self):
        """A wrong .cal path fails fast with a clear error (the common mistake)."""
        from src.instruments.vna.real import RealPicoVnaDriver

        driver = RealPicoVnaDriver(transport=_FakeScpi(), calibration_file=r"C:\nope\missing.cal")
        with pytest.raises(RuntimeError, match="not found"):
            driver.connect()


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

    def test_real_vna_tolerates_forwarded_kwargs(self, monkeypatch):
        # Regression: the acquisition controller forwards cable_length_mm (a
        # simulator-only knob) to get_vna_driver, so the real PicoVNA driver
        # must accept and ignore it rather than crashing on construction.
        from src.instruments.vna.real import RealPicoVnaDriver

        monkeypatch.setenv(HARDWARE_ENV_VAR, "1")
        driver = get_vna_driver(cable_length_mm=500.0)
        assert isinstance(driver, RealPicoVnaDriver)

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


class TestListVnaDevices:
    """list_vna_devices() drives the VNA page's connection check.

    The PicoVNA is an FTDI USB device, not a COM port, so presence is detected
    via Windows PnP (by Pico's USB vendor ID), independent of the PicoVNA 5 SDK.
    These tests stub the PnP subprocess so they run on any OS.
    """

    @staticmethod
    def _stub_pnp(monkeypatch, stdout):
        """Make the PnP query return canned stdout, as `powershell` would."""
        from types import SimpleNamespace

        from src.instruments.vna import real

        def fake_run(*_a, **_k):
            return SimpleNamespace(stdout=stdout, returncode=0)

        monkeypatch.setattr(real.subprocess, "run", fake_run)

    def test_parses_present_device(self, monkeypatch):
        from src.instruments.vna.real import list_vna_devices

        self._stub_pnp(monkeypatch, "USB\\VID_0CE9&PID_1500\\PW10080A|PicoVNA Series Analyzer\r\n")
        devices = list_vna_devices(demo=False)
        assert len(devices) == 1
        assert devices[0].serial == "PW10080A"
        assert devices[0].description == "PicoVNA Series Analyzer"

    def test_empty_when_no_device(self, monkeypatch):
        from src.instruments.vna.real import list_vna_devices

        self._stub_pnp(monkeypatch, "")
        assert list_vna_devices(demo=False) == []

    def test_empty_when_powershell_missing(self, monkeypatch):
        from src.instruments.vna import real
        from src.instruments.vna.real import list_vna_devices

        def boom(*_a, **_k):
            raise FileNotFoundError("powershell")

        monkeypatch.setattr(real.subprocess, "run", boom)
        assert list_vna_devices(demo=False) == []

    def test_demo_reports_demo_device(self, monkeypatch):
        from src.instruments.vna.driver import VnaDeviceInfo
        from src.instruments.vna.real import list_vna_devices

        # Demo short-circuits before any PnP query, so no instrument is needed.
        self._stub_pnp(monkeypatch, "")
        assert list_vna_devices(demo=True) == [VnaDeviceInfo("demo", "PicoVNA demo device")]

    def test_env_var_enables_demo(self, monkeypatch):
        from src.instruments.vna.real import DEMO_ENV_VAR, list_vna_devices

        monkeypatch.setenv(DEMO_ENV_VAR, "1")
        assert list_vna_devices()[0].serial == "demo"


class TestVnaCaptureAvailable:
    """vna_capture_available() gates the VNA page's Capture button.

    Capture needs a SCPI server: available if one is already reachable, or if
    vnaserver.exe is on disk (connect() can launch it).
    """

    def test_true_when_server_reachable(self, monkeypatch):
        from src.instruments.vna import real

        monkeypatch.setattr(real, "_server_reachable", lambda *a, **k: True)
        monkeypatch.setattr(real, "find_vnaserver_exe", lambda: None)
        assert real.vna_capture_available() is True

    def test_true_when_server_exe_found(self, monkeypatch):
        from src.instruments.vna import real

        monkeypatch.setattr(real, "_server_reachable", lambda *a, **k: False)
        monkeypatch.setattr(real, "find_vnaserver_exe", lambda: r"C:\Pico\vnaserver.exe")
        assert real.vna_capture_available() is True

    def test_false_when_neither(self, monkeypatch):
        from src.instruments.vna import real

        monkeypatch.setattr(real, "_server_reachable", lambda *a, **k: False)
        monkeypatch.setattr(real, "find_vnaserver_exe", lambda: None)
        assert real.vna_capture_available() is False


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

    def test_link_locks_stability_dwell_passes_for_stable_link(self):
        """A 6 Gbps stability dwell passes when the link holds lock.

        The demo bridge holds lock and collapses sleeps, so this returns True
        immediately rather than actually waiting the dwell.
        """
        from src.instruments.serdes.real import RealSerdesDriver

        driver = RealSerdesDriver(demo=True)
        driver.connect()
        assert driver.link_locks(FORWARD_6G, settle_s=5.0) is True
        driver.close()

    def test_link_locks_fails_when_link_drops_during_dwell(self):
        """A link that locks but drops during the stability dwell reads no-link."""
        from src.instruments.serdes import registers as R
        from src.instruments.serdes.real import RealSerdesDriver

        class DropsDuringDwell(RealSerdesDriver):
            DWELL_S = 5.0  # distinct from every internal sleep duration

            def __init__(self) -> None:
                super().__init__(demo=True)
                self._dropped = False

                def drop_on_dwell(seconds: float) -> None:
                    if seconds == self.DWELL_S:
                        self._dropped = True

                self._sleep = drop_on_dwell

            def _is_locked(self, dev: int = R.DES_ADDR) -> bool:
                return not self._dropped

        driver = DropsDuringDwell()
        driver.connect()  # locks fine initially (not yet dropped)
        assert driver.link_locks(FORWARD_6G, settle_s=DropsDuringDwell.DWELL_S) is False
        driver.close()

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

    def test_link_status_retries_through_transient_nak(self):
        """A freshly-connected link can NAK a status read once; link_status must
        retry rather than abort the whole Check-link."""
        from src.instruments.serdes.demo_bridge import DemoBridge
        from src.instruments.serdes.real import RealSerdesDriver

        class NakOnceOnRead:
            def __init__(self) -> None:
                self._inner = DemoBridge()
                self.arm = False
                self._fired = False

            def read(self, dev: int, reg: int, length: int = 1) -> bytes:
                if self.arm and not self._fired:
                    self._fired = True
                    raise OSError("transient NAK")
                return self._inner.read(dev, reg, length)

            def write(self, dev: int, reg: int, data: bytes) -> None:
                self._inner.write(dev, reg, data)

            def close(self) -> None:
                self._inner.close()

        transport = NakOnceOnRead()
        driver = RealSerdesDriver(transport=transport, demo=True)
        driver.connect()
        transport.arm = True  # NAK the first read inside link_status
        status = driver.link_status()
        driver.close()

        assert transport._fired  # the NAK actually fired and was absorbed
        assert status["ser"]["locked"] and status["des"]["locked"]

    def test_link_status_decodes_error_bit(self):
        """The 'link not clean' path: a set CTRL3 ERROR bit surfaces as error=True."""
        from src.instruments.serdes import registers as R
        from src.instruments.serdes.demo_bridge import DemoBridge
        from src.instruments.serdes.real import RealSerdesDriver

        class DesErrorBit:
            def __init__(self) -> None:
                self._inner = DemoBridge()
                self.arm = False

            def read(self, dev: int, reg: int, length: int = 1) -> bytes:
                data = self._inner.read(dev, reg, length)
                if self.arm and dev == R.DES_ADDR and reg == R.REG_CTRL3:
                    return bytes([data[0] | 0x04, *data[1:]])  # force ERROR bit
                return data

            def write(self, dev: int, reg: int, data: bytes) -> None:
                self._inner.write(dev, reg, data)

            def close(self) -> None:
                self._inner.close()

        transport = DesErrorBit()
        driver = RealSerdesDriver(transport=transport, demo=True)
        driver.connect()  # clean state required to connect
        transport.arm = True  # only now report the error bit
        status = driver.link_status()
        driver.close()

        assert status["des"]["error"] is True


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
