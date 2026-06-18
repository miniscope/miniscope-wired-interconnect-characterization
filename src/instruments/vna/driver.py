"""
VNA driver interface plus Touchstone serialization.

The driver returns complex S-parameters in memory (VnaSweepResult);
`write_s2p` serializes them to a standard Touchstone .s2p file that the
existing parser (src/processing/touchstone.py) reads back, so VNA sessions
written by the acquisition app feed the pipeline unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np

from src.instruments.types import VnaSweepResult


@dataclass
class VnaConfig:
    """Sweep parameters for a VNA capture."""

    start_hz: float = 1e6
    stop_hz: float = 6e9
    num_points: int = 1001
    ref_impedance_ohm: float = 50.0
    calibration: str = "SOLT"  # informational; calibration is a guided manual step


class VnaDeviceInfo(NamedTuple):
    """A VNA the host can see, for the acquisition app's connection check.

    The PicoVNA analogue of SerDes's SerialPortInfo: it enumerates as an FTDI
    USB device (not a COM port), so detection goes through the PicoVNA 5 SDK
    rather than the serial-port list -- see vna/real.py:list_vna_devices.
    """

    serial: str  # instrument serial number, or "demo" for the SDK demo device
    description: str  # human label for the picker, e.g. "PicoVNA 0123ABC"


class VnaDriver(ABC):
    """Abstract VNA driver (PicoVNA or equivalent)."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def is_calibrated(self) -> bool:
        """Whether a valid calibration is loaded (guides the GUI setup checklist)."""
        ...

    @abstractmethod
    def sweep(self, config: VnaConfig) -> VnaSweepResult:
        """Run one frequency sweep and return complex S-parameters."""
        ...

    @abstractmethod
    def close(self) -> None: ...


def write_s2p(result: VnaSweepResult, path: Path) -> None:
    """
    Serialize a sweep to Touchstone v1 .s2p (HZ / RI format).

    Round-trips through src.processing.touchstone.parse_s2p.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    def columns(s: np.ndarray, i: int) -> str:
        return f"{s[i].real:.9g} {s[i].imag:.9g}"

    with open(path, "w") as f:
        f.write("! 2-port S-parameters written by miniscope-char acquisition\n")
        for key, value in result.instrument_info.items():
            f.write(f"! {key}: {value}\n")
        f.write(f"# HZ S RI R {result.ref_impedance_ohm:.0f}\n")
        for i, freq in enumerate(result.frequencies_hz):
            f.write(
                f"{float(freq):.6f}  "
                f"{columns(result.s11, i)}  "
                f"{columns(result.s21, i)}  "
                f"{columns(result.s12, i)}  "
                f"{columns(result.s22, i)}\n"
            )
