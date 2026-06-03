"""
Real PicoVNA driver, built on the PicoVNA 5 Python API.

This targets the modern, cross-platform PicoVNA 5 SDK (Windows / macOS /
Linux / Raspberry Pi) rather than the legacy Windows-only PicoVNA 2/3 DLL.
The SDK ships a pip-installable `vna` package plus a set of platform native
libraries (`_vna_python.*`, `libvna.*`, `libftd2xx.*`) that must sit on the
library path -- see https://github.com/picotech/picovna5-examples.

Two reasons this is written demo-first:

1. **No hardware or licence needed to develop.** `vna.Device.openDemo()`
   opens a fully functional simulated instrument, so this driver -- and the
   whole acquire -> .s2p -> pipeline path -- can be exercised on any machine
   before the PicoVNA 106 is on the bench. Pass `demo=True` (or set
   MINISCOPE_ACQUIRE_VNA_DEMO=1) to use it.
2. **The vendor import stays inside connect().** Importing this module never
   requires the SDK; only connecting does. Everything downstream touches
   only VnaSweepResult, so this file is the single vendor-specific surface.

Bench bring-up checklist (the parts that can only be verified with the SDK
and, for #2/#3, the real 106 -- the demo device uses factory calibration
and rejects user-cal application):

1. `pip install vna` and confirm the native libs import (`from vna import
   vna`).
2. Confirm the complex S-parameter accessor: this code assumes each point's
   `.s11/.s21/.s12/.s22` expose `.real`/`.imag`. If not, it falls back to
   reconstructing from `vna.toLogMag` + `vna.toPhaseDeg`. Verify the values
   match the PicoVNA 5 GUI trace for a known cable (this is exactly the
   calibration step that bit users on the legacy DLL).
3. Confirm `applyCalibrationFromFile` against a real SOLT calibration file.
"""

from __future__ import annotations

import os

import numpy as np

from src.instruments.types import VnaSweepResult
from src.instruments.vna.driver import VnaConfig, VnaDriver

DEMO_ENV_VAR = "MINISCOPE_ACQUIRE_VNA_DEMO"


class RealPicoVnaDriver(VnaDriver):
    """
    PicoVNA 106/108 driver via the PicoVNA 5 Python API.

    Args:
        demo: open the SDK's simulated demonstration device instead of real
            hardware (no instrument, licence, or calibration required).
        calibration_file: optional path to a PicoVNA 5 user-calibration
            (.cal) file to apply on connect. Ignored in demo mode (the demo
            device only supports its built-in factory calibration).
        power_dbm: stimulus power level for the sweep.
        bandwidth_hz: IF/measurement bandwidth per point (lower = less noise,
            slower sweep).
    """

    def __init__(
        self,
        demo: bool | None = None,
        calibration_file: str | None = None,
        power_dbm: float = 0.0,
        bandwidth_hz: float = 1000.0,
    ) -> None:
        if demo is None:
            demo = os.environ.get(DEMO_ENV_VAR, "") == "1"
        self._demo = demo
        self._calibration_file = calibration_file
        self._power_dbm = power_dbm
        self._bandwidth_hz = bandwidth_hz

        self._vna = None  # the imported `vna` module (loaded in connect)
        self._instrument = None
        self._user_cal_applied = False

    def connect(self) -> None:
        # Vendor import lives here so importing this module never needs the SDK.
        try:
            from vna import vna
        except ImportError as e:  # pragma: no cover - depends on SDK install
            raise RuntimeError(
                "PicoVNA 5 SDK not available: `pip install vna` and place the "
                "platform native libraries (_vna_python.*, libvna.*, "
                "libftd2xx.*) on the library path. See "
                "https://github.com/picotech/picovna5-examples."
            ) from e

        self._vna = vna

        if self._demo:
            self._instrument = vna.Device.openDemo()
        else:
            try:
                self._instrument = vna.Device.openAny()
            except vna.DeviceNotFoundException as e:  # pragma: no cover - needs hw
                raise RuntimeError(
                    "No PicoVNA instrument found. Connect a PicoVNA 106/108 (and "
                    "ensure its firmware is compatible with PicoVNA 5), or "
                    "construct RealPicoVnaDriver(demo=True) for offline use."
                ) from e

            if self._calibration_file is not None:
                self._instrument.applyCalibrationFromFile(self._calibration_file)
                self._user_cal_applied = True

    def is_calibrated(self) -> bool:
        """
        Whether the instrument is ready to produce trustworthy S-parameters.

        The demo device is internally consistent (factory calibration), so it
        always reports calibrated. Real hardware reports calibrated only once
        a user SOLT calibration has been applied -- this gates the GUI capture
        step behind the calibration the protocol requires.
        """
        if self._instrument is None:
            return False
        return self._demo or self._user_cal_applied

    def sweep(self, config: VnaConfig) -> VnaSweepResult:
        if self._instrument is None or self._vna is None:
            raise RuntimeError("connect() must be called before sweep()")

        vna = self._vna
        info = self._instrument.getInfo()

        # Clamp the requested range to what the instrument supports.
        start_hz = max(float(config.start_hz), float(info.minSweepFrequencyHz))
        stop_hz = min(float(config.stop_hz), float(info.maxSweepFrequencyHz))

        mc = vna.MeasurementConfiguration()
        mc.addUniformFrequencySweep(
            config.num_points,
            start_hz,
            stop_hz,
            self._power_dbm,
            self._bandwidth_hz,
        )

        points = self._instrument.performMeasurement(mc)

        freqs = np.array([p.measurementFrequencyHz for p in points], dtype=float)
        s11 = np.array([self._to_complex(p.s11) for p in points], dtype=complex)
        s21 = np.array([self._to_complex(p.s21) for p in points], dtype=complex)
        s12 = np.array([self._to_complex(p.s12) for p in points], dtype=complex)
        s22 = np.array([self._to_complex(p.s22) for p in points], dtype=complex)

        return VnaSweepResult(
            frequencies_hz=freqs,
            s11=s11,
            s21=s21,
            s12=s12,
            s22=s22,
            ref_impedance_ohm=config.ref_impedance_ohm,
            instrument_info={
                "instrument": "PicoVNA (demo)" if self._demo else f"PicoVNA {info.serial}",
                "demo": str(self._demo).lower(),
                "power_dbm": str(self._power_dbm),
                "bandwidth_hz": str(self._bandwidth_hz),
                "calibration": "user" if self._user_cal_applied else "factory",
            },
        )

    def _to_complex(self, s: object) -> complex:
        """
        Convert a PicoVNA 5 S-parameter sample to a Python complex.

        Prefers the direct real/imaginary accessors; falls back to
        reconstructing from the documented log-magnitude (dB) and phase
        (deg) helpers if the sample type doesn't expose .real/.imag. The
        fall-back path uses only API functions verified in the examples, so
        it is the safe default until #2 in the bring-up checklist confirms
        which accessor the installed SDK provides.
        """
        real = getattr(s, "real", None)
        imag = getattr(s, "imag", None)
        if real is not None and imag is not None:
            return complex(real, imag)

        mag_db = self._vna.toLogMag(s)
        phase_deg = self._vna.toPhaseDeg(s)
        mag = 10.0 ** (mag_db / 20.0)
        return complex(mag * np.cos(np.deg2rad(phase_deg)), mag * np.sin(np.deg2rad(phase_deg)))

    def close(self) -> None:
        if self._instrument is not None:
            close = getattr(self._instrument, "close", None)
            if callable(close):
                close()
        self._instrument = None
