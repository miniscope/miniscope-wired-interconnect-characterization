"""
Shared in-memory data shapes returned by instrument drivers.

These are vendor- and transport-agnostic: drivers (real or simulated)
produce them, the acquisition app previews them, and the session writers
serialize them to the on-disk contracts defined by the measurement type
schemas (raw EOM eye grid CSV + raw link-margin CSV for serdes, .s2p for VNA).

Design principle: drivers return data *close to what the instrument emits*.
For the GMSL2 deserializer's eye monitor that is the raw phase/vth/polarity
grid of hit + error counts -- physical conversion (codes -> mV / UI),
eye-opening, and link-margin math all live downstream in src/processing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class SerdesChannel(str, Enum):
    FORWARD = "forward"  # serializer -> deserializer (high-bandwidth video/data)
    REVERSE = "reverse"  # deserializer -> serializer (fixed low-rate control back-channel)


class SerdesRate(Enum):
    """
    A GMSL2 link rate. The member value is ``(gbps, short_label)``.

    The forward link runs at 3 or 6 Gbps; the reverse control channel is a
    fixed ~187.5 Mbps. Rates are NOT interchangeable across channels, so the
    valid combinations are enumerated as lanes (see ``DEFAULT_LANES``) rather
    than taken as a cartesian product.
    """

    GBPS_3 = (3.0, "3g")
    GBPS_6 = (6.0, "6g")
    MBPS_187 = (0.1875, "187m")

    @property
    def gbps(self) -> float:
        return self.value[0]

    @property
    def label(self) -> str:
        return self.value[1]


@dataclass(frozen=True)
class SerdesLane:
    """One physically valid (channel, rate) the characterization sweeps."""

    channel: SerdesChannel
    rate: SerdesRate

    @property
    def lane_id(self) -> str:
        """Short, filename-safe id, e.g. ``fwd_6g`` / ``rev_187m``."""
        prefix = "fwd" if self.channel is SerdesChannel.FORWARD else "rev"
        return f"{prefix}_{self.rate.label}"


# The three lanes every SerDes session covers (the back channel is the fixed
# low-rate control link, so it has exactly one rate, not two).
FORWARD_3G = SerdesLane(SerdesChannel.FORWARD, SerdesRate.GBPS_3)
FORWARD_6G = SerdesLane(SerdesChannel.FORWARD, SerdesRate.GBPS_6)
REVERSE_187M = SerdesLane(SerdesChannel.REVERSE, SerdesRate.MBPS_187)
DEFAULT_LANES: tuple[SerdesLane, ...] = (FORWARD_3G, FORWARD_6G, REVERSE_187M)


@dataclass
class EyeDiagram:
    """
    One eye diagram for a lane, stored as the deserializer's raw eye-on-monitor
    (EOM) grid: one row per measured (phase, vth, polarity) point.

    Axes are register codes, not physical units:
      - phase: 0..127 (horizontal, spans ~2 unit intervals)
      - vth:   0..63  voltage-threshold code within one polarity half
      - polarity: 0 (negative half) / 1 (positive half)
    Each point carries the observed ``hits`` (bits sampled) and ``errors``
    (mismatches); ``errors == -1`` flags a measurement timeout. Conversion to
    mV / UI and eye-opening extraction happens in src/processing/eye.py.
    """

    lane: SerdesLane
    phase: np.ndarray  # int, register code 0..127
    vth: np.ndarray  # int, register code 0..63
    polarity: np.ndarray  # int, 0/1
    hits: np.ndarray  # int
    errors: np.ndarray  # int, -1 on timeout
    bins: int = 64  # grid resolution requested (N x N)
    observations: int = 32768  # bits sampled per point


@dataclass
class MarginPoint:
    """
    One TX-amplitude step in a link-margin sweep, stored close to the raw ADI
    algorithm output.
    """

    tx_amplitude_mv: float
    code: int  # raw amplitude register value written
    rep: int  # replica-amplitude code (Algorithm #2 only; 0 otherwise)
    locked: bool  # link LOCKED at this step
    errors: int  # decode error count; -1 if lock was lost
    status: str  # ok | errors | lost_lock | ser_unreachable


@dataclass
class MarginSweep:
    """One link-margin sweep for a lane (coarse + fine points, by amplitude)."""

    lane: SerdesLane
    points: list[MarginPoint]


@dataclass
class SerdesResult:
    """Complete SerDes characterization: one eye + one margin sweep per lane."""

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
    stage: str  # e.g. "eye:fwd_6g", "margin:rev_187m"
    partial: object | None = None
