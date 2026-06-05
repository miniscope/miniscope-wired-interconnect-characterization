"""
Raspberry Pi Pico serial-bridge transport (the lab's real I2C adapter).

The Pico runs the generic `gmsl2-bridge` MicroPython firmware
(firmware/gmsl2-bridge/main.py), exposing an ASCII command set over USB-CDC
serial at 115200 baud:

    PING -> PONG | R <addr> <reg> -> OK <hex> | W <addr> <reg> <val> -> OK
    RM <addr> <reg> <n> -> OK <h1>,<h2>,... | WM <addr> <reg> <v1,v2,...> -> OK

This class adapts that protocol to the register-level `I2CTransport` Protocol
the SerDes driver consumes. `pyserial` is imported lazily so the simulator /
analysis install never needs it.
"""

from __future__ import annotations

import time


class PicoBridgeI2C:
    """`I2CTransport` over the gmsl2-bridge serial firmware."""

    def __init__(
        self,
        port: str = "/dev/pico",
        baud: int = 115200,
        timeout: float = 1.0,
        verbose: bool = False,
    ) -> None:
        try:
            import serial  # noqa: PLC0415  (lazy: hardware-only dependency)
        except ImportError as exc:  # pragma: no cover - exercised only on the bench
            raise RuntimeError(
                "pyserial is required for the Pico bridge. Install the acquire "
                "group: `poetry install --with acquire`."
            ) from exc

        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.verbose = verbose
        # MicroPython may take 1-2s to (re)bind stdin after the host opens the
        # port (DTR toggle re-enumerates USB). Settle, then drain the banner.
        self._ser = serial.Serial(port, baud, timeout=timeout)
        time.sleep(1.5)
        self._ser.reset_input_buffer()
        if not self._ping():
            raise RuntimeError(f"gmsl2-bridge not responding on {port} (no PONG)")

    # ---- Serial primitives --------------------------------------------------
    def _send(self, cmd: str) -> str:
        if self.verbose:
            print(f"  >> {cmd}")
        self._ser.write((cmd + "\n").encode("ascii"))
        self._ser.flush()
        while True:  # skip banner / comment lines (start with '#')
            raw = self._ser.readline().decode("ascii", errors="replace").strip()
            if not raw:
                raise OSError(f"No response to: {cmd}")
            if raw.startswith("#"):
                continue
            if self.verbose:
                print(f"  << {raw}")
            return raw

    def _ping(self, retries: int = 5) -> bool:
        for _ in range(retries):
            try:
                if self._send("PING") == "PONG":
                    return True
            except OSError:
                time.sleep(0.3)
        return False

    # ---- I2CTransport -------------------------------------------------------
    def read(self, dev_addr: int, reg_addr: int, length: int = 1) -> bytes:
        if length == 1:
            resp = self._send(f"R 0x{dev_addr:02X} 0x{reg_addr:04X}")
            if not resp.startswith("OK "):
                raise OSError(f"Read failed at 0x{dev_addr:02X}:0x{reg_addr:04X}: {resp}")
            return bytes([int(resp[3:], 16)])
        resp = self._send(f"RM 0x{dev_addr:02X} 0x{reg_addr:04X} {length}")
        if not resp.startswith("OK "):
            raise OSError(f"Read failed at 0x{dev_addr:02X}:0x{reg_addr:04X}: {resp}")
        return bytes(int(x, 16) for x in resp[3:].split(","))

    def write(self, dev_addr: int, reg_addr: int, data: bytes) -> None:
        if len(data) == 1:
            resp = self._send(f"W 0x{dev_addr:02X} 0x{reg_addr:04X} 0x{data[0]:02X}")
        else:
            payload = ",".join(f"0x{b:02X}" for b in data)
            resp = self._send(f"WM 0x{dev_addr:02X} 0x{reg_addr:04X} {payload}")
        if resp != "OK":
            raise OSError(f"Write failed at 0x{dev_addr:02X}:0x{reg_addr:04X}: {resp}")

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None
