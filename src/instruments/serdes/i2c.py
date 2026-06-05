"""
Injectable I2C transport for the SerDes driver.

The GMSL2 serializer/deserializer pair is configured over I2C from the
bench PC. The lab drives the bus through a Raspberry Pi Pico running the
`gmsl2-bridge` firmware (see firmware/gmsl2-bridge/), but the driver only
depends on this narrow register-level Protocol, so the concrete adapter
stays injectable and testable:

- PicoBridgeI2C (src/instruments/serdes/pico_bridge.py) -- the real serial bridge
- DemoBridge    (src/instruments/serdes/demo_bridge.py) -- in-memory GMSL2 model
- NullI2C       (here)                                  -- no-op for the simulator

Addresses are the 8-bit datasheet form (e.g. 0x80 SER, 0x98 DES); register
addresses are 16-bit. Reads/writes raise OSError/IOError on bus failure so the
ported algorithms can catch a dropped reverse link.
"""

from __future__ import annotations

from typing import Protocol


class I2CTransport(Protocol):
    """Minimal register-level I2C interface the SerDes driver needs."""

    def write(self, dev_addr: int, reg_addr: int, data: bytes) -> None: ...

    def read(self, dev_addr: int, reg_addr: int, length: int) -> bytes: ...

    def close(self) -> None: ...


class NullI2C:
    """No-op transport for the simulator and tests."""

    def write(self, dev_addr: int, reg_addr: int, data: bytes) -> None:
        pass

    def read(self, dev_addr: int, reg_addr: int, length: int) -> bytes:
        return b"\x00" * length

    def close(self) -> None:
        pass
