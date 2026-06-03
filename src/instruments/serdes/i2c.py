"""
Injectable I2C transport for the SerDes driver.

The GMSL2 serializer/deserializer pair is configured over I2C from the
bench PC. The exact adapter (FTDI, Aardvark, ...) depends on the lab's
hardware, so the transport is a narrow Protocol injected into the real
driver -- the simulator ignores it entirely.

TODO (deferred decision): add the concrete transport class (e.g.
FtdiI2C) once the lab's instrument scripts determine which adapter is
used. It only needs to satisfy this Protocol.
"""

from __future__ import annotations

from typing import Protocol


class I2CTransport(Protocol):
    """Minimal register-level I2C interface the real SerDes driver needs."""

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
