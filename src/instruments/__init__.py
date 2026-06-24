"""
Instrument control layer.

Every instrument is abstracted behind a driver interface with a SIMULATED
implementation, so the acquisition app and the test suite run without any
hardware. Real drivers (built from the lab's existing instrument scripts)
slot in behind the same interfaces -- see serdes/real.py and vna/real.py.

Driver selection happens through src.instruments.registry; the default is
always the simulator.
"""

from src.instruments.types import (
    DEFAULT_LANES,
    FORWARD_3G,
    FORWARD_6G,
    REVERSE_3G,
    REVERSE_6G,
    REVERSE_187M,
    EyeDiagram,
    MarginPoint,
    MarginSweep,
    ProgressEvent,
    SerdesChannel,
    SerdesLane,
    SerdesRate,
    SerdesResult,
    VnaSweepResult,
)


class InstrumentError(Exception):
    """Base class for instrument-level failures."""


class InstrumentNotConnected(InstrumentError):
    """Raised when an operation requires connect() to have succeeded."""


__all__ = [
    "DEFAULT_LANES",
    "FORWARD_3G",
    "FORWARD_6G",
    "REVERSE_3G",
    "REVERSE_6G",
    "REVERSE_187M",
    "EyeDiagram",
    "InstrumentError",
    "InstrumentNotConnected",
    "MarginPoint",
    "MarginSweep",
    "ProgressEvent",
    "SerdesChannel",
    "SerdesLane",
    "SerdesRate",
    "SerdesResult",
    "VnaSweepResult",
]
