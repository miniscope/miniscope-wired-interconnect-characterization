"""
Simulated SerDes driver: deterministic, plausible data with no hardware.

The simulator exists so that (a) the acquisition app can be developed and
demoed anywhere, (b) CI never needs instruments, and (c) the end-to-end data
path (driver -> session writer -> pipeline) is exercised with realistic shapes.

It emits the SAME raw contracts as the real driver -- the deserializer's
eye-on-monitor (EOM) phase/vth/polarity grid and the raw per-step link-margin
records -- so the on-disk session format is exercised identically. Signal
quality degrades with `cable_length_mm` (smaller eye, higher error onset) and
is worse at 6 Gbps and on the reverse channel. Pass a seed for reproducibility.
"""

from __future__ import annotations

import numpy as np

from src.instruments.serdes import registers as R
from src.instruments.serdes.driver import SerdesConfig, SerdesDriver
from src.instruments.types import (
    EyeDiagram,
    MarginPoint,
    MarginSweep,
    SerdesChannel,
    SerdesLane,
    SerdesRate,
)


class SimulatedSerdesDriver(SerdesDriver):
    """Generates an open elliptical eye grid and a monotone margin curve."""

    def __init__(self, cable_length_mm: float = 1000.0, seed: int = 0, **_: object) -> None:
        self._cable_length_mm = cable_length_mm
        self._seed = seed
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def link_status(self) -> dict[str, object]:
        return {
            "connected": self._connected,
            "locked": True,
            "simulated": True,
            "cable_length_mm": self._cable_length_mm,
        }

    def link_locks(self, lane: SerdesLane) -> bool:
        """Model whether the link establishes for this lane.

        The forward 6 Gbps link fails to lock on long cables (beyond ~2 m, where
        the channel is too lossy to acquire); the 3 Gbps forward link and the
        low-rate reverse control channel stay robust. This lets the no-link path
        (recorded + scored 0) be exercised against the simulator without hardware.
        """
        length_m = self._cable_length_mm / 1000.0
        if lane.rate is SerdesRate.GBPS_6 and length_m > 2.0:
            return False
        return True

    def _quality(self, lane: SerdesLane) -> tuple[float, float]:
        """(eye open fraction, margin error-onset mV) for one lane."""
        length_m = self._cable_length_mm / 1000.0
        open_fraction = 0.85 - 0.15 * length_m
        onset_mv = 30.0 + 30.0 * length_m
        if lane.rate is SerdesRate.GBPS_6:
            open_fraction -= 0.1
            onset_mv += 15.0
        if lane.channel is SerdesChannel.REVERSE:
            open_fraction -= 0.05
            onset_mv += 5.0
        return max(open_fraction, 0.05), onset_mv

    def capture_eye(self, lane: SerdesLane, config: SerdesConfig) -> EyeDiagram:
        open_fraction, _ = self._quality(lane)
        rng = np.random.default_rng(self._seed + 100 * int(lane.rate.gbps * 10) + len(lane.lane_id))
        obs = config.eye_observations

        phase_inc = max(1, R.MAX_PHASE // config.eye_bins)
        vth_inc = max(1, (R.MAX_VTH * 2) // config.eye_bins)

        phases, vths, pols, hits, errors = [], [], [], [], []
        for ph in range(0, R.MAX_PHASE, phase_inc):
            x = (ph - 64) / (64.0 * open_fraction)
            for vt in range(0, R.MAX_VTH, vth_inc):
                y = (vt / 32.0) / open_fraction
                radius = float(np.hypot(x, y))
                if radius <= 1.0:
                    err = 0
                else:
                    ratio = min(1.0, (radius - 1.0) * 1.2)
                    # A little noise so repeated sessions vary like real data.
                    ratio = float(np.clip(ratio + rng.normal(0, 0.02), 0.0, 1.0))
                    err = int(ratio * obs)
                for pol in (0, 1):
                    phases.append(ph)
                    vths.append(vt)
                    pols.append(pol)
                    hits.append(obs)
                    errors.append(err)

        return EyeDiagram(
            lane=lane,
            phase=np.array(phases, dtype=np.int64),
            vth=np.array(vths, dtype=np.int64),
            polarity=np.array(pols, dtype=np.int64),
            hits=np.array(hits, dtype=np.int64),
            errors=np.array(errors, dtype=np.int64),
            bins=config.eye_bins,
            observations=obs,
        )

    def sweep_margin(self, lane: SerdesLane, config: SerdesConfig) -> MarginSweep:
        _, onset_mv = self._quality(lane)
        start_mv = R.DES_TX_START_MV if lane.channel is SerdesChannel.REVERSE else R.SER_TX_START_MV
        step = int(config.margin_coarse_step_mv)
        stop = int(config.margin_stop_mv)

        points: list[MarginPoint] = []
        for tx_mv in range(start_mv, stop - 1, -step):
            code = (tx_mv // 10) & 0x3F
            if tx_mv > onset_mv:
                errors = 0
            else:
                errors = min(255, int((onset_mv - tx_mv + 1) ** 2))
            status = "ok" if errors == 0 else "errors"
            points.append(MarginPoint(float(tx_mv), code, 0, True, errors, status))
            if errors > 0 and not config.margin_continue_on_error:
                break

        return MarginSweep(lane=lane, points=points)

    def close(self) -> None:
        self._connected = False
