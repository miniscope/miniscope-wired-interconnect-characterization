"""
Real PicoVNA driver, built on the PicoVNA 5 SCPI interface.

Why SCPI and not the native `vna` Python binding: on Windows the PicoVNA 5
SDK does not ship a loadable Python extension. `pip install vna` provides only
the pure-Python SWIG wrapper (it does a bare `import _vna_python`), and the
compiled `_vna_python.pyd` is absent from the Windows SDK (the SDK carries the
import lib `vna_python.lib` but not the binary; only Linux/macOS ship prebuilt
`.so`/`.dylib`). It also only targets CPython 3.8-3.11, while the bench runs
3.12. Rather than chase a missing/unbuildable binary, this driver speaks the
SCPI protocol the PicoVNA 5 software already exposes -- proven on the bench:
`lsvna.exe` enumerates the unit and `vnaserver.exe` serves SCPI on TCP 5025.
The command set here follows Pico's own `scpi/python` examples
(https://github.com/picotech/picovna5-examples).

Transport boundary: this module never opens a socket at import time -- only
connect() does. The SCPI transport is injectable (see ``transport=`` on
RealPicoVnaDriver), mirroring RealSerdesDriver's i2c transport, so the
acquire -> .s2p -> pipeline path can be exercised against a fake server in
tests without hardware. For genuine offline development with no instrument
*and no PicoVNA 5 software running*, use SimulatedVnaDriver (the registry
picks it whenever ``simulate`` is true).

Bench bring-up checklist (the parts only verifiable against a live server):

1. Start the SCPI server: the PicoVNA 5 software exposes SCPI on TCP 5025, or
   run ``vnaserver.exe`` headless (this driver auto-launches it when no server
   is already reachable). The instrument must not be held by another opener.
2. Confirm the S-parameter accessor: this code reads complex data via
   ``CALC:DATA Sxx,REAL`` / ``,IMAG`` (per the SCPI video example) and falls
   back to ``LOGMAG`` + ``PHASE`` if a build rejects REAL/IMAG on the live
   trace. Verify the values match the PicoVNA 5 GUI trace for a known cable.
3. Confirm the frequency-axis unit: ``SENSE:FREQUENCY:START?`` etc. return a
   value with a unit suffix (e.g. "0.3 MHz"); _parse_freq_hz reads the suffix.
   Verify the reconstructed axis matches the GUI for a known sweep.
4. Confirm ``MMEM:CD`` / ``MMEM:APPLY:CAL`` path handling for a real .calx file
   (Program Files paths contain spaces -- quoting may need adjusting).
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

import numpy as np

from src.instruments.types import VnaSweepResult
from src.instruments.vna.driver import VnaConfig, VnaDeviceInfo, VnaDriver

DEMO_ENV_VAR = "MINISCOPE_ACQUIRE_VNA_DEMO"
HOST_ENV_VAR = "MINISCOPE_ACQUIRE_VNA_HOST"
PORT_ENV_VAR = "MINISCOPE_ACQUIRE_VNA_PORT"
SERVER_ENV_VAR = "MINISCOPE_ACQUIRE_VNA_SERVER"  # override path to vnaserver.exe

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SCPI_PORT = 5025  # PicoVNA 5 / Pico SCPI examples default

# Standard install location of the SCPI tools shipped with the PicoVNA 5
# software. vnaserver is auto-launched when no server is already serving SCPI;
# lsvna enumerates instruments (and the serial vnaserver's --instrument wants).
_DEFAULT_BIN = r"C:\Program Files\Pico Technology Ltd\PicoVNA 5\bin"
_DEFAULT_VNASERVER = os.path.join(_DEFAULT_BIN, "vnaserver.exe")
_DEFAULT_LSVNA = os.path.join(_DEFAULT_BIN, "lsvna.exe")

# The PicoVNA presents as an FTDI-bus USB device under Pico Technology's USB
# vendor ID (0x0CE9) with a custom PID (e.g. PID_1500), bound to Pico's FTDI
# driver -- so it never shows up as a COM port and the SerDes serial-port
# picker can't see it. Windows still enumerates it via PnP as a "PicoVNA Series
# Analyzer" though, which is how we detect presence below.
_PICO_VNA_PNP_QUERY = (
    "Get-PnpDevice -PresentOnly | "
    "Where-Object { $_.InstanceId -like 'USB\\VID_0CE9*' -and $_.FriendlyName -like 'PicoVNA*' } | "
    "ForEach-Object { $_.InstanceId + '|' + $_.FriendlyName }"
)


def list_vna_devices(demo: bool | None = None) -> list[VnaDeviceInfo]:
    """Detect attached PicoVNA hardware for the acquisition app's connection check.

    The PicoVNA is an FTDI USB device, not a COM port, so the SerDes serial-port
    picker can't find it. We enumerate it the way the OS already does -- via
    Windows PnP, by Pico's USB vendor ID -- which is a true "is it plugged in?"
    check that, unlike opening the instrument, needs neither the SCPI server nor
    exclusive access. Capture still needs a SCPI server (see
    vna_capture_available); keeping the two checks separate lets the GUI tell
    "no instrument connected" apart from "connected but no server to capture
    through".

    Returns an empty list when no instrument is present or detection isn't
    possible (e.g. non-Windows, or PowerShell unavailable), so the GUI treats
    "no VNA" as a normal, handled state -- like list_serial_ports() for the
    SerDes bridge. In demo mode (``demo=True`` or MINISCOPE_ACQUIRE_VNA_DEMO=1)
    a demo device is reported as present so the offline acquire path can be
    exercised end to end.
    """
    if demo is None:
        demo = os.environ.get(DEMO_ENV_VAR, "") == "1"
    if demo:
        return [VnaDeviceInfo(serial="demo", description="PicoVNA demo device")]

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PICO_VNA_PNP_QUERY],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        # No PowerShell (non-Windows bench) or it failed to launch -- not an
        # error, just "can't detect here". Capture surfaces a clear message if
        # the user tries anyway.
        return []

    devices: list[VnaDeviceInfo] = []
    for line in result.stdout.splitlines():
        instance_id, sep, friendly = line.strip().partition("|")
        if not sep:
            continue
        # Instance id looks like USB\VID_0CE9&PID_1500\PW10080A; the trailing
        # segment is the unit serial.
        serial = instance_id.rsplit("\\", 1)[-1]
        devices.append(VnaDeviceInfo(serial=serial, description=friendly.strip() or "PicoVNA"))
    return devices


def find_vnaserver_exe() -> str | None:
    """Locate the PicoVNA 5 SCPI server executable, or None if not found.

    Honours MINISCOPE_ACQUIRE_VNA_SERVER, then falls back to the standard
    install path. Capture can auto-launch this when no server is already
    serving SCPI -- see RealPicoVnaDriver.connect.
    """
    override = os.environ.get(SERVER_ENV_VAR, "").strip()
    candidates = [override, _DEFAULT_VNASERVER] if override else [_DEFAULT_VNASERVER]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def find_lsvna_exe() -> str | None:
    """Locate lsvna.exe (the instrument lister), or None if not found.

    Looked for next to vnaserver.exe first (so a SERVER override relocates both),
    then at the standard install path.
    """
    server = find_vnaserver_exe()
    if server:
        sibling = os.path.join(os.path.dirname(server), "lsvna.exe")
        if os.path.isfile(sibling):
            return sibling
    return _DEFAULT_LSVNA if os.path.isfile(_DEFAULT_LSVNA) else None


def list_scpi_instruments() -> list[str]:
    """Instrument serials as the SCPI server sees them, via lsvna.exe.

    These are the serials vnaserver's ``--instrument`` expects (e.g. "10080"),
    which differ from the USB/PnP serial list_vna_devices reports ("PW10080A") --
    vnaserver rejects the PnP form. Returns [] if lsvna isn't found or fails, so
    callers can surface a clear "no instrument" message.
    """
    exe = find_lsvna_exe()
    if not exe:
        return []
    try:
        result = subprocess.run([exe], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    serials: list[str] = []
    for line in result.stdout.splitlines():
        label, sep, value = line.partition(":")
        if sep and label.strip().lower() == "serial" and value.strip():
            serials.append(value.strip())
    return serials


def _server_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    """Whether something is accepting TCP connections at host:port (a SCPI server)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def vna_capture_available(host: str | None = None, port: int | None = None) -> bool:
    """Whether the PicoVNA capture path (a SCPI server) is available.

    Detection (list_vna_devices) only needs the OS to see the USB device; the
    actual sweep needs a SCPI server. This returns True when either a server is
    already reachable at host:port, or the bundled ``vnaserver.exe`` is present
    on disk (so connect() can auto-launch one). The GUI checks both this and
    detection so it can point the user at the missing piece.
    """
    host = host or os.environ.get(HOST_ENV_VAR) or DEFAULT_HOST
    port = port or int(os.environ.get(PORT_ENV_VAR, DEFAULT_SCPI_PORT))
    return _server_reachable(host, port) or find_vnaserver_exe() is not None


class ScpiError(RuntimeError):
    """A SCPI transport or protocol error (connection lost, bad response)."""


class _SocketScpi:
    """Minimal newline-delimited SCPI-over-TCP client (stdlib sockets only).

    The PicoVNA SCPI server speaks line-oriented SCPI: send ``CMD\\n``, read one
    ``\\n``-terminated response line back (every command, including ones that
    "do" something like INIT, returns a line -- Pico's examples ``query`` them
    all). This avoids a pyvisa/pyvisa-py/zeroconf dependency on the bench.
    """

    def __init__(self, host: str, port: int, timeout: float, connect_timeout: float = 5.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=connect_timeout)
        self._sock.settimeout(timeout)
        self._buf = bytearray()

    def query(self, cmd: str) -> str:
        self._sock.sendall((cmd + "\n").encode("ascii"))
        return self._read_line()

    def query_ascii_values(self, cmd: str) -> list[float]:
        resp = self.query(cmd)
        return [float(tok) for tok in resp.split(",") if tok.strip()]

    def _read_line(self) -> str:
        while b"\n" not in self._buf:
            try:
                chunk = self._sock.recv(65536)
            except TimeoutError as e:  # socket read timeout (socket.timeout aliases this)
                raise ScpiError("timed out waiting for SCPI response") from e
            if not chunk:
                raise ScpiError("SCPI connection closed by server")
            self._buf.extend(chunk)
        line, _, rest = bytes(self._buf).partition(b"\n")
        self._buf = bytearray(rest)
        return line.decode("ascii", "replace").rstrip("\r")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def _parse_scalar(resp: str) -> float:
    """First whitespace-separated token of a SCPI scalar reply, as a float."""
    return float(resp.strip().split()[0])


_FREQ_UNIT_HZ = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}


def _parse_freq_hz(resp: str) -> float:
    """Parse a SCPI frequency reply ("0.3 MHz", "6e9 Hz", "3000000") to Hz.

    PicoVNA replies carry a unit suffix; honour it. A bare number (no unit) is
    taken as Hz -- see bring-up checklist #3 to confirm against a live server.
    """
    parts = resp.strip().split()
    value = float(parts[0])
    unit = parts[1].upper() if len(parts) > 1 else "HZ"
    return value * _FREQ_UNIT_HZ.get(unit, 1.0)


class RealPicoVnaDriver(VnaDriver):
    """
    PicoVNA 106/108 driver via the PicoVNA 5 SCPI server.

    Args:
        host/port: where the SCPI server listens (default 127.0.0.1:5025; also
            MINISCOPE_ACQUIRE_VNA_HOST / _PORT).
        server_exe: path to vnaserver.exe to auto-launch if no server is
            already reachable (default: located via find_vnaserver_exe).
        instrument_serial: which unit the auto-launched server connects to
            (``--instrument``); None lets the server pick the attached one.
        launch_server: True forces auto-launch, False forbids it (connect fails
            if nothing is reachable). None (default) auto-launches only when no
            server answers at host:port.
        calibration_file: optional PicoVNA 5 user-calibration (.calx) to apply on
            connect via MMEM:APPLY:CAL.
        transport: an injected SCPI transport (for tests); when given, no socket
            is opened and no server is launched.
        sweep_timeout_s: socket read timeout, sized for a full sweep to finish
            (the first CALC:DATA blocks until the measurement completes).

    Note on sweep parameters: the PicoVNA 5 software / loaded calibration
    governs frequency limits, point count, power and bandwidth (a SOLT cal is
    only valid at its own points). VnaConfig is therefore advisory here -- the
    driver reads back the *actual* axis from the instrument. ref_impedance_ohm
    is still honoured (it tags the result / .s2p reference).
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        server_exe: str | None = None,
        instrument_serial: str | None = None,
        launch_server: bool | None = None,
        calibration_file: str | None = None,
        demo: bool | None = None,
        transport: object | None = None,
        sweep_timeout_s: float = 120.0,
        **_: object,  # tolerate forwarded kwargs (e.g. cable_length_mm) the real
        # instrument doesn't use, mirroring RealSerdesDriver. The acquisition
        # controller forwards cable_length_mm for the simulator's length model.
    ) -> None:
        if demo is None:
            demo = os.environ.get(DEMO_ENV_VAR, "") == "1"
        self._demo = demo
        self._host = host or os.environ.get(HOST_ENV_VAR) or DEFAULT_HOST
        self._port = int(port or os.environ.get(PORT_ENV_VAR, DEFAULT_SCPI_PORT))
        self._server_exe = server_exe
        self._instrument_serial = instrument_serial
        self._launch_server = launch_server
        self._calibration_file = calibration_file
        self._sweep_timeout_s = sweep_timeout_s

        self._transport = transport  # injected SCPI client, or None until connect()
        self._owns_transport = transport is None
        self._server_proc: subprocess.Popen | None = None
        self._idn: str | None = None
        self._user_cal_applied = False
        self._calibration_name: str | None = None

    def connect(self) -> None:
        if self._transport is None:
            if not _server_reachable(self._host, self._port):
                self._launch_local_server()  # cleans up its own process on failure
            try:
                self._transport = _SocketScpi(self._host, self._port, timeout=self._sweep_timeout_s)
            except OSError as e:
                self._terminate_server()
                raise RuntimeError(
                    f"could not open SCPI socket to {self._host}:{self._port}: {e}"
                ) from e

        # Any failure past this point must not leak the launched server/socket.
        try:
            # The server pads *IDN? with a trailing ';' and NUL bytes; strip them
            # so the clean identity lands in instrument_info / the .s2p header.
            self._idn = self._query("*IDN?").replace("\x00", "").strip().rstrip(";").strip()
            # Return data as ASCII (the default is a binary block format).
            self._query("FORMAT ASCII")
            if self._calibration_file is not None:
                self._apply_calibration(self._calibration_file)
                self._user_cal_applied = True
        except Exception:
            self.close()
            raise

    def _launch_local_server(self) -> None:
        """Start vnaserver.exe locally when no server is already reachable.

        vnaserver only binds the SCPI port once it has an instrument, so we
        discover the unit's serial (via lsvna) and pass ``--instrument``; without
        it the server starts but never serves SCPI. On any failure the launched
        process is terminated rather than left orphaned holding the device.
        """
        if self._launch_server is False:
            raise RuntimeError(
                f"No PicoVNA SCPI server reachable at {self._host}:{self._port} and "
                "auto-launch is disabled. Start the PicoVNA 5 software (it serves "
                "SCPI), or pass launch_server=True."
            )
        if self._host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(
                f"No SCPI server at {self._host}:{self._port}; cannot auto-launch a "
                "remote server. Start a vnaserver/PicoVNA 5 there, or point host at it."
            )
        exe = self._server_exe or find_vnaserver_exe()
        if not exe:
            raise RuntimeError(
                "PicoVNA 5 SCPI server not found: nothing is listening at "
                f"{self._host}:{self._port} and vnaserver.exe was not located. Install "
                "the PicoVNA 5 software, or set MINISCOPE_ACQUIRE_VNA_SERVER to its path."
            )

        serial = self._instrument_serial
        if serial is None:
            found = list_scpi_instruments()
            if not found:
                raise RuntimeError(
                    "No PicoVNA instrument found by lsvna. Connect the unit and ensure "
                    "the PicoVNA 5 GUI isn't holding it (the instrument is single-access)."
                )
            serial = found[0]

        args = [exe, "--scpi_port", str(self._port), "--instrument", serial]
        self._server_proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Wait for the server to start accepting SCPI connections (it binds the
        # port only after opening the instrument -- a few seconds on the bench).
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            if self._server_proc.poll() is not None:
                code = self._server_proc.returncode
                self._server_proc = None
                raise RuntimeError(
                    f"vnaserver.exe exited (code {code}) before serving SCPI. Is the "
                    "instrument connected and not held by the GUI?"
                )
            if _server_reachable(self._host, self._port):
                return
            time.sleep(0.25)

        self._terminate_server()
        raise RuntimeError(
            f"vnaserver.exe did not start serving SCPI at {self._host}:{self._port} "
            "within 25s (instrument serial '" + serial + "')."
        )

    def is_calibrated(self) -> bool:
        """
        Whether the instrument is ready to produce trustworthy S-parameters.

        Calibration on the SCPI path lives in the PicoVNA 5 software: the
        operator performs/loads a SOLT (or other) calibration there as the
        guided manual step the protocol requires, or this driver applies a .calx
        file on connect. We can't second-guess the software's current cal over
        SCPI without a confirmed query, so once connected we treat the
        instrument as the operator's calibrated source. Not connected -> not
        ready (gates the GUI capture button until connect() succeeds).
        """
        return self._transport is not None

    def sweep(self, config: VnaConfig) -> VnaSweepResult:
        if self._transport is None:
            raise RuntimeError("connect() must be called before sweep()")

        # Trigger a sweep. INIT returns promptly; the first CALC:DATA below
        # blocks until the measurement actually completes.
        self._query("INIT")

        freqs = self._read_frequency_axis()
        s11 = self._read_sparam("S11")
        s21 = self._read_sparam("S21")
        s12 = self._read_sparam("S12")
        s22 = self._read_sparam("S22")

        # Guard against any off-by-one between the queried point count and the
        # returned arrays by trimming to the common length.
        n = min(len(freqs), len(s11), len(s21), len(s12), len(s22))
        freqs, s11, s21, s12, s22 = (a[:n] for a in (freqs, s11, s21, s12, s22))

        instrument_info = {
            "instrument": self._idn or ("PicoVNA (demo)" if self._demo else "PicoVNA (SCPI)"),
            "transport": "scpi",
            "endpoint": f"{self._host}:{self._port}",
            "demo": str(self._demo).lower(),
            "calibration": "user" if self._user_cal_applied else "software",
        }
        if self._calibration_name:
            instrument_info["calibration_file"] = self._calibration_name

        return VnaSweepResult(
            frequencies_hz=freqs,
            s11=s11,
            s21=s21,
            s12=s12,
            s22=s22,
            ref_impedance_ohm=config.ref_impedance_ohm,
            instrument_info=instrument_info,
        )

    def _read_frequency_axis(self) -> np.ndarray:
        """Reconstruct the swept frequency axis from the instrument's settings."""
        start_hz = _parse_freq_hz(self._query("SENSE:FREQUENCY:START?"))
        stop_hz = _parse_freq_hz(self._query("SENSE:FREQUENCY:STOP?"))
        num_points = int(round(_parse_scalar(self._query("SENSE:SWEEP:POINTS?"))))
        return np.linspace(start_hz, stop_hz, num_points)

    def _read_sparam(self, name: str) -> np.ndarray:
        """Read one S-parameter as complex, preferring REAL/IMAG over LOGMAG/PHASE.

        REAL/IMAG (used by the SCPI video example) gives the complex value
        directly. If a server build rejects it on the live trace, fall back to
        the documented LOGMAG (dB) + PHASE (deg) accessors -- the same defensive
        path the legacy DLL driver needed.
        """
        try:
            real = np.asarray(self._query_ascii(f"CALC:DATA {name},REAL"), dtype=float)
            imag = np.asarray(self._query_ascii(f"CALC:DATA {name},IMAG"), dtype=float)
            if real.size and imag.size:
                return real + 1j * imag
        except (ScpiError, ValueError):
            pass
        mag_db = np.asarray(self._query_ascii(f"CALC:DATA {name},LOGMAG"), dtype=float)
        phase_deg = np.asarray(self._query_ascii(f"CALC:DATA {name},PHASE"), dtype=float)
        mag = 10.0 ** (mag_db / 20.0)
        return mag * np.exp(1j * np.deg2rad(phase_deg))

    def _apply_calibration(self, calibration_file: str) -> None:
        """Apply a PicoVNA 5 user calibration (.calx) via MMEM:CD + MMEM:APPLY:CAL.

        The server reads the file from its own (local) filesystem, so the path
        is validated locally first to give a clear error on the common
        wrong-path mistake. Directory and name are double-quoted (standard SCPI
        string args) so paths with spaces -- e.g. under Documents -- survive.
        """
        path = Path(calibration_file).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Calibration file not found: {path}")
        self._calibration_name = path.name
        # Pico's example uses forward-slash paths; quote to tolerate spaces.
        self._query(f'MMEM:CD "{path.parent.as_posix()}"')
        self._query(f'MMEM:APPLY:CAL "{path.name}"')

    def _query(self, cmd: str) -> str:
        return self._transport.query(cmd)  # type: ignore[union-attr]

    def _query_ascii(self, cmd: str) -> list[float]:
        return self._transport.query_ascii_values(cmd)  # type: ignore[union-attr]

    def close(self) -> None:
        if self._transport is not None and self._owns_transport:
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()
        self._transport = None
        self._terminate_server()

    def _terminate_server(self) -> None:
        """Stop the vnaserver we launched (no-op if we connected to an existing one)."""
        if self._server_proc is None:
            return
        self._server_proc.terminate()
        try:
            self._server_proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._server_proc.kill()
        self._server_proc = None
