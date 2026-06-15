"""
Real GMSL2 SerDes driver (MAX96717 serializer + MAX96716A deserializer).

Ports the lab's working gmsl2-cable-tester logic into the SerdesDriver ABC:

- eye capture  : the deserializer's eye-on-monitor (EOM) phase x vth sweep
- link margin  : ADI app-note Algorithm #1 (3G fwd), #2 (6G fwd), #3 (reverse)

The four register sequences run over an injected `I2CTransport`:
- the bench uses `PicoBridgeI2C` (a Raspberry Pi Pico serial bridge)
- `RealSerdesDriver(demo=True)` runs against `DemoBridge` (no hardware), so the
  exact algorithm code is exercised in CI just like RealPicoVnaDriver(demo=True).

Data is returned close to the raw instrument output (the EOM grid and the raw
per-step margin records); physical conversion and metrics live in
src/processing. Per-lane orchestration is inherited from SerdesDriver.
"""

from __future__ import annotations

import time

import numpy as np

from src.instruments.serdes import registers as R
from src.instruments.serdes.driver import SerdesConfig, SerdesDriver
from src.instruments.serdes.i2c import I2CTransport
from src.instruments.types import (
    EyeDiagram,
    MarginPoint,
    MarginSweep,
    SerdesChannel,
    SerdesLane,
    SerdesRate,
)


# ---------------------------------------------------------------------------
# Amplitude (mV) -> register code conversions, from the ADI app note.
# ---------------------------------------------------------------------------
def _fwd_code_algo1(tx_mv: int) -> int:
    """Algorithm #1 (3G): code = tx_mV / 10  (RLMS95[5:0])."""
    return (tx_mv // 10) & 0x3F


def _fwd_code_algo2(tx_mv: int) -> int:
    """Algorithm #2 (6G): code = round((tx_mV + 174.5) / 5.35), -35 if < 64."""
    code = round((tx_mv + 174.5) / 5.35)
    if code < 64:
        code -= 35
    return code & 0x7F


def _fwd_replica_algo2(tx_mv: int) -> int:
    """Algorithm #2 replica amplitude code."""
    if tx_mv > 185:
        return int(0.568 * (tx_mv - 194.6) + 14.8)
    return 6


def _rev_code(tx_mv: int) -> int:
    """Algorithm #3 (reverse): code = tx_mV / 10  (DES RLMS95[5:0])."""
    return (tx_mv // 10) & 0x3F


class _Bus:
    """Byte/bit-level register access on top of the register `I2CTransport`."""

    def __init__(self, transport: I2CTransport) -> None:
        self._t = transport

    def read(self, dev: int, reg: int) -> int:
        return self._t.read(dev, reg, 1)[0]

    def write(self, dev: int, reg: int, val: int) -> None:
        self._t.write(dev, reg, bytes([val & 0xFF]))

    def set_bits(self, dev: int, reg: int, mask: int, value: int) -> None:
        cur = self.read(dev, reg)
        new = (cur & ~mask) | (value & mask)
        if new != cur:
            self.write(dev, reg, new)

    def get_bit(self, dev: int, reg: int, bit: int) -> int:
        return (self.read(dev, reg) >> bit) & 1


class RealSerdesDriver(SerdesDriver):
    """GMSL2 hardware driver. Bench transport is the Pico serial bridge."""

    def __init__(
        self,
        port: str = "/dev/pico",
        transport: I2CTransport | None = None,
        demo: bool = False,
        verbose: bool = False,
        poll_timeout_s: float = 5.0,
        **_: object,
    ) -> None:
        if transport is None:
            if demo:
                from src.instruments.serdes.demo_bridge import DemoBridge

                transport = DemoBridge()
            else:
                from src.instruments.serdes.pico_bridge import PicoBridgeI2C

                transport = PicoBridgeI2C(port=port, verbose=verbose)
        self._transport = transport
        self._bus = _Bus(transport)
        self._demo = demo
        self._poll_timeout_s = poll_timeout_s
        # Real captures dwell for seconds per point; the demo model is
        # instantaneous, so collapse all waits to keep CI fast.
        self._sleep = (lambda _s: None) if demo else time.sleep

    # ---- Lifecycle ----------------------------------------------------------
    def connect(self) -> None:
        ser_id = self._bus.read(R.SER_ADDR, R.REG_DEV_ID)
        des_id = self._bus.read(R.DES_ADDR, R.REG_DEV_ID)
        if ser_id != R.SER_DEV_ID_EXPECTED:
            raise RuntimeError(f"Serializer ID 0x{ser_id:02X} != 0x{R.SER_DEV_ID_EXPECTED:02X}")
        if des_id != R.DES_DEV_ID_EXPECTED:
            raise RuntimeError(f"Deserializer ID 0x{des_id:02X} != 0x{R.DES_DEV_ID_EXPECTED:02X}")
        if not self._ensure_clean_state():
            raise RuntimeError("Link did not reach a clean, locked state")

    def _read_settle(self, dev: int, reg: int, attempts: int = 3) -> int:
        """Read a register, retrying through transient I2C NAKs.

        A freshly-connected link can still be settling, so a status read may NAK
        once or twice before it answers. Every other register path in this
        driver tolerates NAKs, so the read-only status check should too rather
        than aborting the whole "Check link" on the first stutter.
        """
        for attempt in range(1, attempts + 1):
            try:
                return self._bus.read(dev, reg)
            except OSError:
                if attempt == attempts:
                    raise
                self._sleep(0.05)

    def link_status(self) -> dict[str, object]:
        def decode(dev: int) -> dict[str, object]:
            ctrl3 = self._read_settle(dev, R.REG_CTRL3)
            dev_id = self._read_settle(dev, R.REG_DEV_ID)
            return {
                "part": R.PART_BY_DEV_ID.get(dev_id, f"unknown (0x{dev_id:02X})"),
                "device_id": dev_id,
                "locked": bool(ctrl3 & 0x08),
                "error": bool(ctrl3 & 0x04),
                "cmu": bool(ctrl3 & 0x02),
            }

        # Forward-link rate: the deserializer's RX_RATE[1:0] in REG1 (the SER
        # TX_RATE[3:2] mirrors it). The reverse link is always 187.5 Mbps.
        rate_code = self._read_settle(R.DES_ADDR, R.REG_REG1) & 0x03
        return {
            "connected": True,
            "demo": self._demo,
            "forward_rate": R.RATE_NAME.get(rate_code, f"unknown (code 0x{rate_code:02X})"),
            "ser": decode(R.SER_ADDR),
            "des": decode(R.DES_ADDR),
        }

    def close(self) -> None:
        for dev in (R.SER_ADDR, R.DES_ADDR):
            try:
                self._bus.write(dev, R.REG_CTRL0, 0x80)  # RESET_ALL
            except OSError:
                pass
        self._transport.close()

    # ---- Link health (ported from gmsl2_link_margin.ensure_clean_state) -----
    def _is_locked(self, dev: int = R.DES_ADDR) -> bool:
        return bool(self._bus.read(dev, R.REG_CTRL3) & 0x08)

    def _has_error(self, dev: int) -> bool:
        return bool(self._bus.read(dev, R.REG_CTRL3) & 0x04)

    def _reset_all(self, dev: int) -> None:
        try:
            self._bus.write(dev, R.REG_CTRL0, 0x80)
        except OSError:
            pass  # NAK during reset is expected

    def _wait_relock(self, timeout_s: float = 15.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                if self._is_locked():
                    self._sleep(0.5)
                    for dev in (R.SER_ADDR, R.DES_ADDR):
                        try:
                            self._bus.read(dev, R.REG_CNT0)
                        except OSError:
                            pass
                    return True
            except OSError:
                pass
            self._sleep(0.25)
            if self._demo:  # no real clock advances; avoid a busy spin
                break
        return self._is_locked()

    def _ensure_clean_state(self, max_retries: int = 3) -> bool:
        for _ in range(max_retries):
            try:
                des_locked = self._is_locked(R.DES_ADDR)
                ser_err = self._has_error(R.SER_ADDR)
                des_err = self._has_error(R.DES_ADDR)
            except OSError:
                self._reset_all(R.SER_ADDR)
                self._reset_all(R.DES_ADDR)
                self._sleep(1.0)
                continue
            if des_locked and not ser_err and not des_err:
                self._bus.read(R.SER_ADDR, R.REG_CNT0)  # clear counters
                self._bus.read(R.DES_ADDR, R.REG_CNT0)
                return True
            self._reset_all(R.SER_ADDR)
            self._reset_all(R.DES_ADDR)
            self._sleep(0.5)
            self._wait_relock()
        return False

    def _set_forward_rate(self, rate: SerdesRate) -> None:
        """Switch the forward link to 3G/6G and wait for re-lock."""
        rate_code = R.RATE_CODE_3G if rate is SerdesRate.GBPS_3 else R.RATE_CODE_6G
        self._bus.set_bits(R.SER_ADDR, R.REG_REG1, 0x0C, rate_code << 2)
        self._bus.set_bits(R.DES_ADDR, R.REG_REG1, 0x03, rate_code)
        try:
            self._bus.set_bits(R.DES_ADDR, R.REG_CTRL0, 0x20, 0x20)  # RESET_ONESHOT
        except OSError:
            pass
        self._sleep(0.3)
        self._wait_relock()

    # ---- Eye capture (ported from gmsl2_eye_mapper.EyeMapper) ----------------
    def capture_eye(self, lane: SerdesLane, config: SerdesConfig) -> EyeDiagram:
        if lane.channel is SerdesChannel.FORWARD:
            self._set_forward_rate(lane.rate)
        phase1_reg, phase0_reg = R.REG_DES_PHASE[lane.lane_id]

        bins = config.eye_bins
        phase_inc = max(1, R.MAX_PHASE // bins)
        vth_inc = max(1, (R.MAX_VTH * 2) // bins)
        obs = config.eye_observations

        saved = {
            reg: self._bus.read(R.DES_ADDR, reg)
            for reg in (
                R.REG_DES_RLMS4,
                R.REG_DES_RLMS58,
                R.REG_DES_RLMS59,
                R.REG_DES_RLMS37,
                R.REG_DES_RLMS49,
                phase0_reg,
                phase1_reg,
            )
        }
        try:
            self._eom_initialize(obs)
            if config.eye_source == "prbs":
                self._setup_prbs()
            rows = self._eom_sweep(phase0_reg, phase1_reg, phase_inc, vth_inc)
        finally:
            if config.eye_source == "prbs":
                self._teardown_prbs()
            for reg, val in saved.items():
                try:
                    self._bus.write(R.DES_ADDR, reg, val)
                except OSError:
                    pass
            self._reset_all(R.SER_ADDR)
            self._reset_all(R.DES_ADDR)

        cols = np.array(rows, dtype=np.int64).reshape(-1, 5) if rows else np.zeros((0, 5), np.int64)
        return EyeDiagram(
            lane=lane,
            phase=cols[:, 0],
            vth=cols[:, 1],
            polarity=cols[:, 2],
            hits=cols[:, 3],
            errors=cols[:, 4],
            bins=bins,
            observations=obs,
        )

    def _eom_initialize(self, observations: int) -> None:
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMSA4, 0x3F, 0x00)  # periodic adapt off
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS3, 0x80, 0x00)  # global adapt off
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS4, 0x02, 0x00)  # EOM periodic off
        for bit in (0x00, 0x01, 0x00):  # toggle EOM enable 0->1->0
            self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS4, 0x01, bit)
        self._bus.write(R.DES_ADDR, R.REG_DES_RLMS35, (observations >> 8) & 0xFF)
        self._bus.write(R.DES_ADDR, R.REG_DES_RLMS34, observations & 0xFF)
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS49, 0x04, 0x04)  # error channel on

    def _setup_prbs(self) -> None:
        self._bus.write(R.SER_ADDR, R.REG_SER_VTX1, 0x0D)
        self._bus.write(R.SER_ADDR, R.REG_SER_VTX29, 0x01)
        self._sleep(0.003)
        self._bus.write(R.SER_ADDR, R.REG_SER_VTX29, 0x81)
        self._sleep(0.050)

    def _teardown_prbs(self) -> None:
        try:
            self._bus.write(R.SER_ADDR, R.REG_SER_VTX29, 0x00)
            self._bus.write(R.SER_ADDR, R.REG_SER_VTX1, 0x00)
        except OSError:
            pass

    def _eom_sweep(
        self, phase0_reg: int, phase1_reg: int, phase_inc: int, vth_inc: int
    ) -> list[list[int]]:
        rows: list[list[int]] = []
        for ph in range(0, R.MAX_PHASE, phase_inc):
            for vt in range(0, R.MAX_VTH, vth_inc):
                for pol in (0, 1):
                    try:
                        errs, hits = self._eom_point(phase0_reg, phase1_reg, ph, vt, pol)
                        rows.append([ph, vt, pol, hits, errs])
                    except TimeoutError:
                        rows.append([ph, vt, pol, 0, -1])
        return rows

    def _eom_point(
        self, phase0_reg: int, phase1_reg: int, phase: int, vth: int, polarity: int
    ) -> tuple[int, int]:
        self._bus.set_bits(R.DES_ADDR, phase0_reg, 0x7F, phase & 0x7F)
        self._bus.set_bits(R.DES_ADDR, phase1_reg, 0x7F, phase & 0x7F)
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS37, 0x01, polarity & 1)
        vval = ((vth + 64) if polarity == 0 else vth) & 0x7F
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS58, 0x7F, vval)
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS59, 0x7F, vval)
        # Two measurements (EMP=0/TA=0 and EMP=1/TA=1); keep the lower errors.
        e0, h0 = self._eom_measure(phase0_reg, phase1_reg, 0, 0)
        e1, h1 = self._eom_measure(phase0_reg, phase1_reg, 1, 1)
        return (e0, h0) if e0 <= e1 else (e1, h1)

    def _eom_measure(self, phase0_reg: int, phase1_reg: int, emp: int, ta: int) -> tuple[int, int]:
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS37, 0x02, (emp & 1) << 1)
        self._bus.set_bits(R.DES_ADDR, phase0_reg, 0x80, (ta & 1) << 7)
        self._bus.set_bits(R.DES_ADDR, phase1_reg, 0x80, (ta & 1) << 7)
        self._eom_clear_counters()
        self._eom_start_monitor()
        self._eom_wait_done()
        err = self._bus.read(R.DES_ADDR, R.REG_DES_RLMS38) + (
            self._bus.read(R.DES_ADDR, R.REG_DES_RLMS39) << 8
        )
        hit = self._bus.read(R.DES_ADDR, R.REG_DES_RLMS3A) + (
            self._bus.read(R.DES_ADDR, R.REG_DES_RLMS3B) << 8
        )
        return err, hit

    def _eom_clear_counters(self) -> None:
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS37, 0x08, 0x08)
        t0 = time.time()
        while time.time() - t0 < self._poll_timeout_s:
            if self._bus.read(R.DES_ADDR, R.REG_DES_RLMS3A) == 0 and (
                self._bus.read(R.DES_ADDR, R.REG_DES_RLMS3B) == 0
            ):
                return
            self._sleep(0.001)
            if self._demo:
                break
        raise TimeoutError("EOM counters did not clear")

    def _eom_start_monitor(self) -> None:
        t0 = time.time()
        while time.time() - t0 < self._poll_timeout_s:
            self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS37, 0x04, 0x04)
            if self._bus.read(R.DES_ADDR, R.REG_DES_RLMS3A) != 0 or (
                self._bus.read(R.DES_ADDR, R.REG_DES_RLMS3B) != 0
            ):
                return
            self._sleep(0.001)
            if self._demo:
                break
        raise TimeoutError("EOM monitor did not start")

    def _eom_wait_done(self) -> None:
        t0 = time.time()
        while time.time() - t0 < self._poll_timeout_s:
            if self._bus.get_bit(R.DES_ADDR, R.REG_DES_RLMS37, 4):
                return
            self._sleep(0.001)
            if self._demo:
                break
        raise TimeoutError("EOM monitor not done")

    # ---- Link margin (ported from gmsl2_link_margin Algorithms #1/#2/#3) -----
    def sweep_margin(self, lane: SerdesLane, config: SerdesConfig) -> MarginSweep:
        # capture_eye() leaves both chips mid-RESET_ALL, so the very first
        # register access here can NAK while they re-lock. Recover first (this
        # tolerates and retries transient I2C errors) before touching REG1.
        self._ensure_clean_state()
        if lane.channel is SerdesChannel.FORWARD:
            self._set_forward_rate(lane.rate)
        self._ensure_clean_state()

        if lane.channel is SerdesChannel.REVERSE:
            points = self._margin_reverse(config)
        elif lane.rate is SerdesRate.GBPS_3:
            points = self._margin_forward_algo1(config)
        else:
            points = self._margin_forward_algo2(config)
        return MarginSweep(lane=lane, points=points)

    def _adapt_cycle(self, dev: int) -> None:
        """Enable global adapt, settle, disable (RLMS3[7])."""
        self._bus.set_bits(dev, R.REG_DES_RLMS3, 0x80, 0x80)
        self._sleep(0.1)
        self._bus.set_bits(dev, R.REG_DES_RLMS3, 0x80, 0x00)

    def _sweep_amps(self, config: SerdesConfig, start_mv: int) -> list[int]:
        step = int(config.margin_coarse_step_mv)
        stop = int(config.margin_stop_mv)
        return list(range(start_mv, stop - 1, -step))

    def _margin_forward_algo1(self, config: SerdesConfig) -> list[MarginPoint]:
        """Algorithm #1 -- 3G forward: SER RLMS95 amplitude, DES decode errors."""
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMSA4, 0x3F, 0x00)
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS4, 0x01, 0x00)
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS3, 0x80, 0x00)
        self._bus.set_bits(R.SER_ADDR, R.REG_SER_RLMS95, 0x80, 0x80)  # manual TX enable
        self._bus.read(R.DES_ADDR, R.REG_CNT0)

        points: list[MarginPoint] = []
        for tx_mv in self._sweep_amps(config, R.SER_TX_START_MV):
            code = _fwd_code_algo1(tx_mv)
            cur = self._bus.read(R.SER_ADDR, R.REG_SER_RLMS95)
            self._bus.write(R.SER_ADDR, R.REG_SER_RLMS95, (cur & 0xC0) | (code & 0x3F))
            self._adapt_cycle(R.DES_ADDR)
            if not self._is_locked(R.DES_ADDR):
                points.append(MarginPoint(tx_mv, code, 0, False, -1, "lost_lock"))
                break
            self._bus.read(R.DES_ADDR, R.REG_CNT0)  # clear
            self._sleep(config.margin_dwell_s)
            errs = self._bus.read(R.DES_ADDR, R.REG_CNT0)
            status = "ok" if errs == 0 else "errors"
            points.append(MarginPoint(tx_mv, code, 0, True, errs, status))
            if errs > 0 and not config.margin_continue_on_error:
                break
        return points

    def _margin_forward_algo2(self, config: SerdesConfig) -> list[MarginPoint]:
        """Algorithm #2 -- 6G forward: SER RLMSC8 amplitude + replica regs."""
        self._bus.write(R.SER_ADDR, R.REG_SER_RLMSC9, 0x00)  # main FFE off
        self._bus.write(R.SER_ADDR, R.REG_SER_RLMSCA, 0x00)  # replica FFE off
        self._bus.write(R.SER_ADDR, R.REG_SER_RLMSCE, 0x3E)  # TX ctrl
        self._bus.write(R.SER_ADDR, R.REG_SER_RLMSBA, 0x08)  # min tune amp
        self._bus.read(R.DES_ADDR, R.REG_CNT0)

        points: list[MarginPoint] = []
        for tx_mv in self._sweep_amps(config, R.SER_TX_START_MV):
            code = _fwd_code_algo2(tx_mv)
            rep = _fwd_replica_algo2(tx_mv)
            cur_c8 = self._bus.read(R.SER_ADDR, R.REG_SER_RLMSC8)
            self._bus.write(R.SER_ADDR, R.REG_SER_RLMSC8, (cur_c8 & 0x80) | (code & 0x7F))
            self._bus.write(R.SER_ADDR, R.REG_SER_RLMS85, (rep // 2) + 128)
            cur_84 = self._bus.read(R.SER_ADDR, R.REG_SER_RLMS84)
            self._bus.write(
                R.SER_ADDR, R.REG_SER_RLMS84, (cur_84 & 0x7F) | (0x80 if rep & 1 else 0)
            )
            self._adapt_cycle(R.DES_ADDR)
            if not self._is_locked(R.DES_ADDR):
                points.append(MarginPoint(tx_mv, code, rep, False, -1, "lost_lock"))
                break
            self._bus.read(R.DES_ADDR, R.REG_CNT0)  # clear
            self._sleep(config.margin_dwell_s)
            errs = self._bus.read(R.DES_ADDR, R.REG_CNT0)
            status = "ok" if errs == 0 else "errors"
            points.append(MarginPoint(tx_mv, code, rep, True, errs, status))
            if errs > 0 and not config.margin_continue_on_error:
                break
        return points

    def _margin_reverse(self, config: SerdesConfig) -> list[MarginPoint]:
        """Algorithm #3 -- reverse: DES RLMS95 amplitude, SER decode errors."""
        self._bus.set_bits(R.SER_ADDR, R.REG_SER_RLMSA4, 0x3F, 0x00)
        self._bus.set_bits(R.SER_ADDR, R.REG_SER_RLMS4, 0x01, 0x00)
        self._bus.set_bits(R.SER_ADDR, R.REG_SER_RLMS3, 0x80, 0x00)
        self._bus.set_bits(R.DES_ADDR, R.REG_DES_RLMS95, 0x80, 0x80)  # manual TX enable
        self._bus.read(R.SER_ADDR, R.REG_CNT0)

        points: list[MarginPoint] = []
        for tx_mv in self._sweep_amps(config, R.DES_TX_START_MV):
            code = _rev_code(tx_mv)
            cur = self._bus.read(R.DES_ADDR, R.REG_DES_RLMS95)
            self._bus.write(R.DES_ADDR, R.REG_DES_RLMS95, (cur & 0xC0) | (code & 0x3F))
            try:
                self._bus.set_bits(R.SER_ADDR, R.REG_SER_RLMS3, 0x80, 0x80)
                self._sleep(0.1)
                self._bus.set_bits(R.SER_ADDR, R.REG_SER_RLMS3, 0x80, 0x00)
                if not self._is_locked(R.DES_ADDR):
                    points.append(MarginPoint(tx_mv, code, 0, False, -1, "lost_lock"))
                    break
                self._bus.read(R.SER_ADDR, R.REG_CNT0)  # clear
                self._sleep(config.margin_dwell_s)
                errs = self._bus.read(R.SER_ADDR, R.REG_CNT0)
            except OSError:
                # Reverse link collapsed -> SER unreachable. Restore DES TX.
                try:
                    self._bus.write(R.DES_ADDR, R.REG_DES_RLMS95, R.DES_TX_DEFAULT_CODE)
                    self._sleep(1.0)
                except OSError:
                    pass
                points.append(MarginPoint(tx_mv, code, 0, False, -1, "ser_unreachable"))
                break
            status = "ok" if errs == 0 else "errors"
            points.append(MarginPoint(tx_mv, code, 0, True, errs, status))
            if errs > 0 and not config.margin_continue_on_error:
                break
        # Always leave the reverse link at its default amplitude.
        try:
            self._bus.write(R.DES_ADDR, R.REG_DES_RLMS95, R.DES_TX_DEFAULT_CODE)
        except OSError:
            pass
        return points
