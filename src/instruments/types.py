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

    @property
    def display(self) -> str:
        """Capitalized direction name, e.g. 'Forward' / 'Reverse'."""
        return "Forward" if self is SerdesChannel.FORWARD else "Reverse"


def rate_label(gbps: float) -> str:
    """Human-readable link rate, e.g. '6 Gbps' / '187.5 Mbps'."""
    return f"{gbps:g} Gbps" if gbps >= 1 else f"{gbps * 1000:g} Mbps"


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

    @property
    def display(self) -> str:
        """Human-readable rate, e.g. '6 Gbps' / '187.5 Mbps'."""
        return rate_label(self.gbps)


@dataclass(frozen=True)
class SerdesLane:
    """One lane the characterization sweeps.

    A lane is a (channel, rate) pair, plus -- for the reverse control channel --
    the forward-link rate it was measured under. The reverse channel is a fixed
    187.5 Mbps back-channel that rides on the forward link, so its signal
    integrity depends on the forward rate (crosstalk on the shared coax); it is
    therefore characterized once per forward rate. ``forward_rate`` records which
    forward context a reverse lane belongs to -- None for forward lanes and for
    the legacy single reverse lane.
    """

    channel: SerdesChannel
    rate: SerdesRate
    forward_rate: SerdesRate | None = None

    @property
    def lane_id(self) -> str:
        """Short, filename-safe id, e.g. ``fwd_6g`` / ``rev_187m_fwd3g``.

        A reverse lane keeps its true 187.5 Mbps rate in the id and is tagged
        with the forward-link context it was measured under (``rev_187m_fwd3g`` /
        ``rev_187m_fwd6g``); a context-less reverse lane is the legacy
        ``rev_187m``.
        """
        if self.channel is SerdesChannel.FORWARD:
            return f"fwd_{self.rate.label}"
        if self.forward_rate is not None:
            return f"rev_{self.rate.label}_fwd{self.forward_rate.label}"
        return f"rev_{self.rate.label}"

    @property
    def label(self) -> str:
        """Compact human label, e.g. 'Forward 6 Gbps' / 'Reverse 187.5 Mbps @ 6 Gbps'."""
        base = f"{self.channel.display} {self.rate.display}"
        if self.channel is SerdesChannel.REVERSE and self.forward_rate is not None:
            return f"{base} @ {self.forward_rate.display}"
        return base


# The lanes every SerDes session covers: the forward link at 3 and 6 Gbps, plus
# the reverse 187.5 Mbps control channel characterized once under each forward
# rate (it rides on the forward link, so a forward rate that won't lock takes
# its reverse measurement down with it).
FORWARD_3G = SerdesLane(SerdesChannel.FORWARD, SerdesRate.GBPS_3)
FORWARD_6G = SerdesLane(SerdesChannel.FORWARD, SerdesRate.GBPS_6)
REVERSE_3G = SerdesLane(SerdesChannel.REVERSE, SerdesRate.MBPS_187, forward_rate=SerdesRate.GBPS_3)
REVERSE_6G = SerdesLane(SerdesChannel.REVERSE, SerdesRate.MBPS_187, forward_rate=SerdesRate.GBPS_6)
# Legacy single reverse lane (no forward context) -- kept so older 3-lane
# sessions written before the per-forward-rate split still read back.
REVERSE_187M = SerdesLane(SerdesChannel.REVERSE, SerdesRate.MBPS_187)
DEFAULT_LANES: tuple[SerdesLane, ...] = (FORWARD_3G, FORWARD_6G, REVERSE_3G, REVERSE_6G)


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
    """Complete SerDes characterization: one eye per lane + one margin sweep
    per (lane, iteration). A repeated margin sweep appends several sweeps for
    the same lane to ``margins`` (see ``group_margins_by_lane``).

    ``no_link_lanes`` lists lanes the link could not establish at all (no lock),
    so they carry no eye or margin. Recording them keeps a non-linking cable
    visible -- it is scored 0 (not_recommended) downstream rather than silently
    missing from the results.
    """

    eyes: list[EyeDiagram] = field(default_factory=list)
    margins: list[MarginSweep] = field(default_factory=list)
    no_link_lanes: list[SerdesLane] = field(default_factory=list)


def group_margins_by_lane(
    margins: list[MarginSweep],
) -> list[tuple[SerdesLane, list[MarginSweep]]]:
    """Group margin sweeps by lane, preserving first-seen lane order.

    A full sequence with N margin iterations emits the sweeps lane-major
    (lane0 x N, lane1 x N, ...), so this keeps each lane's runs together in the
    order they were captured.
    """
    grouped: dict[str, list[MarginSweep]] = {}
    order: list[SerdesLane] = []
    for sweep in margins:
        if sweep.lane.lane_id not in grouped:
            grouped[sweep.lane.lane_id] = []
            order.append(sweep.lane)
        grouped[sweep.lane.lane_id].append(sweep)
    return [(lane, grouped[lane.lane_id]) for lane in order]


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
