"""
In-memory GMSL2 register model -- the no-hardware path for the real driver.

`DemoBridge` is an `I2CTransport` that emulates *just enough* MAX96717 /
MAX96716A behavior for the real driver's actual register sequences to run end
to end with no dev kit: device IDs, the LOCKED status bit, the deserializer's
eye-on-monitor (EOM) state machine, and the decode-error counter responding to
TX amplitude. This is what `RealSerdesDriver(demo=True)` runs against, so the
ported hardware algorithms stay exercised in CI (mirrors the VNA's demo mode).

It is a behavioral model, not a faithful silicon simulation: it produces a
plausible open eye and a monotone link-margin curve, nothing more.
"""

from __future__ import annotations

import math

from src.instruments.serdes import registers as R


def _normalize(addr: int) -> int:
    """8-bit datasheet address -> 7-bit (matches the Pico firmware)."""
    return addr >> 1 if addr > 0x77 else addr


SER7 = _normalize(R.SER_ADDR)
DES7 = _normalize(R.DES_ADDR)
_PHASE_REGS = {p for pair in R.REG_DES_PHASE.values() for p in pair}


class DemoBridge:
    """`I2CTransport` backed by an in-memory GMSL2 register model."""

    def __init__(
        self,
        forward_onset_3g_mv: float = 75.0,
        forward_onset_6g_mv: float = 95.0,
        reverse_onset_mv: float = 65.0,
    ) -> None:
        self._forward_onset_3g_mv = forward_onset_3g_mv
        self._forward_onset_6g_mv = forward_onset_6g_mv
        self._reverse_onset_mv = reverse_onset_mv
        # Whichever forward amplitude path the algorithm last drove (Algorithm
        # #1 via RLMS95 -> 3G, Algorithm #2 via RLMSC8 -> 6G) sets the onset.
        self._forward_onset_mv = forward_onset_3g_mv
        self._regs: dict[tuple[int, int], int] = {}

        # Device IDs + a clean, locked link (CTRL3: [3] LOCKED, [1] CMU_LOCKED).
        self._regs[(SER7, R.REG_DEV_ID)] = R.SER_DEV_ID_EXPECTED
        self._regs[(DES7, R.REG_DEV_ID)] = R.DES_DEV_ID_EXPECTED
        self._regs[(SER7, R.REG_CTRL3)] = 0x0A
        self._regs[(DES7, R.REG_CTRL3)] = 0x0A
        # Power-on forward rate (SER TX_RATE[3:2], DES RX_RATE[1:0]) -> 6 Gbps,
        # so a link-status read before any capture reports a real speed.
        self._regs[(SER7, R.REG_REG1)] = R.RATE_CODE_6G << 2
        self._regs[(DES7, R.REG_REG1)] = R.RATE_CODE_6G

        # TX amplitudes start high (well above any error onset) so the
        # algorithms' "link clean at start" pre-checks pass.
        self._ser_tx_mv = 500.0
        self._des_tx_mv = 500.0

        # Eye-monitor working state (deserializer side).
        self._phase = 64
        self._vval = 0
        self._polarity = 1

    # ---- I2CTransport -------------------------------------------------------
    def read(self, dev_addr: int, reg_addr: int, length: int = 1) -> bytes:
        addr = _normalize(dev_addr)
        if reg_addr == R.REG_CNT0:
            # Reading CNT0 returns (and clears) the decode-error count, modeled
            # from the amplitude driven onto the link this device receives.
            return bytes([self._decode_errors(addr)])
        return bytes(self._regs.get((addr, reg_addr + i), 0x00) for i in range(length))

    def write(self, dev_addr: int, reg_addr: int, data: bytes) -> None:
        addr = _normalize(dev_addr)
        for i, byte in enumerate(data):
            self._write_one(addr, reg_addr + i, byte)

    def close(self) -> None:
        pass

    # ---- Register write side effects ----------------------------------------
    def _write_one(self, addr: int, reg: int, val: int) -> None:
        self._regs[(addr, reg)] = val

        # A reset (CTRL0 RESET_ALL [7] / RESET_ONESHOT [5]) re-trains the link,
        # which re-runs amplitude adaptation -- model that as restoring the high,
        # clean auto amplitude, dropping any manual margin override. Without this
        # a margin sweep's leftover low amplitude would make a later reliability
        # probe see errors on a link that is actually fine.
        if reg == R.REG_CTRL0 and (val & 0x80 or val & 0x20):
            self._ser_tx_mv = 500.0
            self._des_tx_mv = 500.0
            # RESET_ALL [7] / RESET_ONESHOT [5] are self-clearing on real silicon;
            # clear them so a later set_bits actually re-issues the reset (else the
            # bit reads as still set and the masked write is skipped).
            self._regs[(addr, reg)] = val & ~0xA0

        # Manual TX amplitude codes -> modeled millivolts.
        if reg == R.REG_SER_RLMS95 and addr == SER7:  # Algorithm #1 (3G forward)
            self._ser_tx_mv = (val & 0x3F) * 10.0
            self._forward_onset_mv = self._forward_onset_3g_mv
        elif reg == R.REG_SER_RLMSC8 and addr == SER7:  # Algorithm #2 (6G forward)
            code = val & 0x7F
            raw = code if code >= 64 else code + 35  # undo the app-note -35 offset
            self._ser_tx_mv = raw * 5.35 - 174.5
            self._forward_onset_mv = self._forward_onset_6g_mv
        elif reg == R.REG_DES_RLMS95 and addr == DES7:  # Algorithm #3 (reverse)
            self._des_tx_mv = (val & 0x3F) * 10.0

        # Eye-monitor state (deserializer).
        if addr == DES7:
            if reg in _PHASE_REGS:
                self._phase = val & 0x7F
            elif reg == R.REG_DES_RLMS58:
                self._vval = val & 0x7F
            elif reg == R.REG_DES_RLMS37:
                self._handle_eom_ctrl(val)

    def _handle_eom_ctrl(self, val: int) -> None:
        """Emulate the auto-clearing EOM strobe bits in RLMS37."""
        self._polarity = val & 0x01
        cur = self._regs[(DES7, R.REG_DES_RLMS37)]
        if val & 0x08:  # clear strobe: zero hit counters, drop done, auto-clear
            self._regs[(DES7, R.REG_DES_RLMS3A)] = 0
            self._regs[(DES7, R.REG_DES_RLMS3B)] = 0
            self._regs[(DES7, R.REG_DES_RLMS37)] = cur & ~0x18  # clear [4] done, [3] clear
        elif val & 0x04:  # start strobe: run a measurement, set done, auto-clear
            errors, hits = self._eye_point()
            self._regs[(DES7, R.REG_DES_RLMS38)] = errors & 0xFF
            self._regs[(DES7, R.REG_DES_RLMS39)] = (errors >> 8) & 0xFF
            self._regs[(DES7, R.REG_DES_RLMS3A)] = hits & 0xFF
            self._regs[(DES7, R.REG_DES_RLMS3B)] = (hits >> 8) & 0xFF
            self._regs[(DES7, R.REG_DES_RLMS37)] = (val & ~0x04) | 0x10  # done set, start cleared

    # ---- Behavioral models --------------------------------------------------
    def _observations(self) -> int:
        hi = self._regs.get((DES7, R.REG_DES_RLMS35), 0x80)
        lo = self._regs.get((DES7, R.REG_DES_RLMS34), 0x00)
        return (hi << 8) | lo or 32768

    def _eye_point(self) -> tuple[int, int]:
        """Errors + hits for the current (phase, vth) -- an open elliptical eye."""
        obs = self._observations()
        vth = self._vval - 64 if self._polarity == 0 else self._vval
        vth = max(0, min(63, vth))
        x = (self._phase - 64) / 40.0  # ~eye half-width in phase codes
        y = vth / 32.0  # vertical, normalized to a half-open eye
        radius = math.hypot(x, y)
        if radius <= 1.0:
            return 0, obs
        ratio = min(1.0, (radius - 1.0) * 1.5)
        return int(ratio * obs), obs

    def _decode_errors(self, reading_device: int) -> int:
        """CNT0 model: SER reads reverse-link errors, DES reads forward-link errors."""
        if reading_device == DES7:  # forward link: driven by SER TX
            amp, onset = self._ser_tx_mv, self._forward_onset_mv
        else:  # reverse link: driven by DES TX
            amp, onset = self._des_tx_mv, self._reverse_onset_mv
        if amp > onset:
            return 0
        return min(255, (int((onset - amp) // 5) + 1) ** 2)
