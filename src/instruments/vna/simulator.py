"""Simulated VNA driver: smooth, plausible S-parameters with no hardware."""

from __future__ import annotations

import numpy as np

from src.instruments.types import VnaSweepResult
from src.instruments.vna.driver import VnaConfig, VnaDriver


class SimulatedVnaDriver(VnaDriver):
    """
    Generates attenuation that grows with frequency and cable length
    (a reasonable coax model) and a small, wiggly return loss.
    """

    def __init__(self, cable_length_mm: float = 1000.0, seed: int = 0) -> None:
        self._cable_length_mm = cable_length_mm
        self._seed = seed
        self._connected = False

    def connect(self) -> None:
        self._connected = True

    def is_calibrated(self) -> bool:
        return True  # the simulator is always "calibrated"

    def sweep(self, config: VnaConfig) -> VnaSweepResult:
        freqs = np.linspace(config.start_hz, config.stop_hz, config.num_points)
        length_m = self._cable_length_mm / 1000.0

        # Insertion loss: ~sqrt(f) skin-effect-like term scaled by length
        loss_db = 0.5 * length_m + 2.0 * length_m * np.sqrt(freqs / 1e9)
        s21_mag = 10 ** (-loss_db / 20.0)
        s21_phase = -2 * np.pi * freqs * length_m * 5e-9  # ~5 ns/m delay
        s21 = s21_mag * np.exp(1j * s21_phase)

        # Return loss around -20 dB with a gentle ripple
        rng = np.random.default_rng(self._seed)
        ripple = 0.02 * np.sin(2 * np.pi * freqs / config.stop_hz * 3 + rng.uniform(0, np.pi))
        s11_mag = 0.1 + ripple
        s11 = s11_mag * np.exp(1j * (0.5 + freqs / config.stop_hz))

        return VnaSweepResult(
            frequencies_hz=freqs,
            s11=s11,
            s21=s21,
            s12=s21.copy(),
            s22=(s11 * 0.9).copy(),
            ref_impedance_ohm=config.ref_impedance_ohm,
            instrument_info={"instrument": "SimulatedVNA", "simulated": "true"},
        )

    def close(self) -> None:
        self._connected = False
