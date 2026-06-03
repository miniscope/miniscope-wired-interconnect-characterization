"""
Real GMSL2 SerDes driver -- PLACEHOLDER.

TODO (deferred until the lab's instrument scripts are provided):
Federico already has working Python that drives the GMSL2 pair over I2C
(characterization mode, eye capture, link-margin sweep). Adapt that code
into this class:

- accept an I2CTransport (src/instruments/serdes/i2c.py) in __init__ so
  the adapter (FTDI, Aardvark, ...) stays injectable/testable
- implement connect / link_status / capture_eye / sweep_margin
- do NOT reimplement the channel x rate orchestration: SerdesDriver
  provides run_full_sequence() for free

Whether the coarse->fine margin refinement lives here or stays inside the
existing sweep code is an open decision; the MarginSweep contract supports
both (just return final per-point values).
"""

from __future__ import annotations

from src.instruments.serdes.driver import SerdesConfig, SerdesDriver
from src.instruments.serdes.i2c import I2CTransport
from src.instruments.types import EyeDiagram, MarginSweep, SerdesChannel, SerdesRate


class RealSerdesDriver(SerdesDriver):
    """GMSL2 hardware driver. Not yet implemented -- see module docstring."""

    def __init__(self, transport: I2CTransport) -> None:
        self._transport = transport

    def connect(self) -> None:
        raise NotImplementedError("Real SerDes driver pending lab instrument scripts")

    def link_status(self) -> dict[str, object]:
        raise NotImplementedError("Real SerDes driver pending lab instrument scripts")

    def capture_eye(
        self, channel: SerdesChannel, rate: SerdesRate, config: SerdesConfig
    ) -> EyeDiagram:
        raise NotImplementedError("Real SerDes driver pending lab instrument scripts")

    def sweep_margin(
        self, channel: SerdesChannel, rate: SerdesRate, config: SerdesConfig
    ) -> MarginSweep:
        raise NotImplementedError("Real SerDes driver pending lab instrument scripts")

    def close(self) -> None:
        self._transport.close()
