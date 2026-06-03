"""
Simulated SerDes driver: deterministic, plausible data with no hardware.

The simulator exists so that (a) the acquisition app can be developed and
demoed anywhere, (b) CI never needs instruments, and (c) the end-to-end
data path (driver -> session writer -> pipeline) is exercised with
realistic shapes. Pass a seed for reproducible output.
"""

from __future__ import annotations

import numpy as np

from src.instruments.serdes.driver import SerdesConfig, SerdesDriver
from src.instruments.types import (
    EyeDiagram,
    MarginPoint,
    MarginSweep,
    SerdesChannel,
    SerdesRate,
)


class SimulatedSerdesDriver(SerdesDriver):
    """
    Generates an elliptical open eye and a monotone margin curve.

    Signal quality degrades with `cable_length_mm` (smaller eye, higher
    error onset) so sweeps across simulated lengths look like real data.
    """

    def __init__(self, cable_length_mm: float = 1000.0, seed: int = 0) -> None:
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

    def _combo_params(self, channel: SerdesChannel, rate: SerdesRate) -> tuple[float, float]:
        """(eye open fraction, margin error-onset mV) for one combo."""
        # Baseline quality degrades with length...
        length_m = self._cable_length_mm / 1000.0
        open_fraction = 0.85 - 0.15 * length_m
        onset_mv = 30.0 + 30.0 * length_m
        # ...and is worse at 6 Gbps and slightly worse on the back channel.
        if rate == SerdesRate.GBPS_6:
            open_fraction -= 0.1
            onset_mv += 15.0
        if channel == SerdesChannel.BACK:
            open_fraction -= 0.05
            onset_mv += 5.0
        return max(open_fraction, 0.05), onset_mv

    def capture_eye(
        self, channel: SerdesChannel, rate: SerdesRate, config: SerdesConfig
    ) -> EyeDiagram:
        open_fraction, _ = self._combo_params(channel, rate)
        rng = np.random.default_rng(self._seed + 100 * rate.value + len(channel.value))

        v_bins = config.eye_voltage_bins
        t_bins = config.eye_time_bins
        v = np.linspace(-1, 1, v_bins)[:, None]
        t = np.linspace(-1, 1, t_bins)[None, :]

        inside = (v / open_fraction) ** 2 + (t / open_fraction) ** 2 < 1.0
        error_counts = rng.integers(1, 200, size=(v_bins, t_bins))
        error_counts[inside] = 0

        unit_interval_ps = 1000.0 / rate.value  # 1 bit period at the line rate
        return EyeDiagram(
            channel=channel,
            rate=rate,
            error_counts=error_counts.astype(np.int64),
            voltage_range_mv=(-400.0, 400.0),
            time_range_ps=(0.0, round(unit_interval_ps, 3)),
            repeats=config.eye_repeats,
        )

    def sweep_margin(
        self, channel: SerdesChannel, rate: SerdesRate, config: SerdesConfig
    ) -> MarginSweep:
        _, onset_mv = self._combo_params(channel, rate)

        coarse = np.arange(
            config.margin_min_mv, config.margin_max_mv + 0.001, config.margin_coarse_step_mv
        )
        fine = np.arange(
            max(onset_mv - 15.0, config.margin_min_mv),
            min(onset_mv + 15.0, config.margin_max_mv),
            config.margin_fine_step_mv,
        )
        amps = np.unique(np.round(np.concatenate([coarse, fine]), 3))

        points: list[MarginPoint] = []
        for amp in amps:
            if amp > onset_mv:
                errors = 0
            else:
                errors = min(255, int((onset_mv - amp + 1) ** 2))
            points.append(
                MarginPoint(
                    tx_amplitude_mv=float(amp),
                    error_count=errors,
                    repeats=config.margin_repeats,
                )
            )

        return MarginSweep(channel=channel, rate=rate, points=points)

    def close(self) -> None:
        self._connected = False
