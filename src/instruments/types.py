"""
Shared in-memory data shapes returned by instrument drivers.

These are vendor- and transport-agnostic: drivers (real or simulated)
produce them, the acquisition app previews them, and the session writers
serialize them to the on-disk contracts defined by the measurement type
schemas (eye NPZ + margin CSV for serdes, .s2p for VNA).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class SerdesChannel(str, Enum):
    FORWARD = "forward"  # serializer -> deserializer (high-bandwidth data)
    BACK = "back"  # deserializer -> serializer (control back-channel)


class SerdesRate(int, Enum):
    GBPS_3 = 3
    GBPS_6 = 6


@dataclass
class EyeDiagram:
    """One captured eye diagram for a channel/rate combo."""

    channel: SerdesChannel
    rate: SerdesRate
    error_counts: np.ndarray  # 2D int, axis 0 = voltage bins, axis 1 = time bins
    voltage_range_mv: tuple[float, float]
    time_range_ps: tuple[float, float]
    repeats: int = 1  # internal repeats averaged by the capture script


@dataclass
class MarginPoint:
    """Final value for one TX amplitude step in a link-margin sweep."""

    tx_amplitude_mv: float
    error_count: int
    repeats: int = 1


@dataclass
class MarginSweep:
    """One link-margin sweep (coarse + fine points merged, sorted by amplitude)."""

    channel: SerdesChannel
    rate: SerdesRate
    points: list[MarginPoint]


@dataclass
class SerdesResult:
    """Complete SerDes characterization: all channel x rate combos."""

    eyes: list[EyeDiagram] = field(default_factory=list)
    margins: list[MarginSweep] = field(default_factory=list)


@dataclass
class VnaSweepResult:
    """One VNA frequency sweep as complex S-parameters."""

    frequencies_hz: np.ndarray
    s11: np.ndarray  # complex
    s21: np.ndarray
    s12: np.ndarray
    s22: np.ndarray
    ref_impedance_ohm: float = 50.0
    instrument_info: dict[str, str] = field(default_factory=dict)


@dataclass
class ProgressEvent:
    """
    Emitted by long-running captures to drive GUI progress + live previews.

    `partial` optionally carries the just-completed EyeDiagram/MarginSweep
    so the GUI can render it while the rest of the sequence runs.
    """

    fraction: float  # 0.0 - 1.0
    message: str
    stage: str  # e.g. "eye:forward:3", "margin:back:6"
    partial: object | None = None
