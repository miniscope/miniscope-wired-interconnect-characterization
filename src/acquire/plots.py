"""
Preview plot rendering for the acquisition app.

Pure matplotlib -> PNG bytes, so the same functions serve the GUI's live
previews and headless unit tests.
"""

from __future__ import annotations

import io

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.instruments.types import EyeDiagram, MarginSweep, VnaSweepResult
from src.processing.eye import eye_figure
from src.processing.vna import (
    characteristic_impedance,
    sparams_to_abcd,
    summarize_characteristic_impedance,
)


def _fig_to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=120)
    plt.close(fig)
    return buffer.getvalue()


def render_eye(eye: EyeDiagram) -> bytes:
    """Heatmap of the eye-monitor grid (error ratio, UI x mV)."""
    fig = eye_figure(
        eye.phase,
        eye.vth,
        eye.polarity,
        eye.errors,
        eye.hits,
        eye.lane.channel.value,
        eye.lane.lane_id,
    )
    return _fig_to_png(fig)


def render_margin(sweep: MarginSweep) -> bytes:
    """Link-margin curve: error count vs TX amplitude (lost-lock steps clamped)."""
    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    amps = [p.tx_amplitude_mv for p in sweep.points]
    errors = [p.errors if p.errors >= 0 else 256 for p in sweep.points]
    ax.plot(amps, errors, marker=".", ms=4)
    ax.set_xlabel("TX amplitude (mV)")
    ax.set_ylabel("Error count")
    ax.set_title(f"Link margin: {sweep.lane.channel.value} @ {sweep.lane.rate.label}")
    ax.grid(True, alpha=0.3)
    return _fig_to_png(fig)


def render_attenuation(result: VnaSweepResult, xscale: str = "log") -> bytes:
    """Attenuation (|S21| in dB, sign-flipped) vs frequency.

    ``xscale`` selects the frequency axis: "log" (default) or "linear".
    """
    fig, ax = plt.subplots(figsize=(6, 3.5))
    attenuation_db = -20 * np.log10(np.maximum(np.abs(result.s21), 1e-12))
    ax.plot(result.frequencies_hz / 1e6, attenuation_db)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Attenuation (dB)")
    ax.set_title("Cable attenuation (from S21)")
    ax.set_xscale(xscale)
    ax.grid(True, alpha=0.3, which="both")
    return _fig_to_png(fig)


def render_sparameters(result: VnaSweepResult, xscale: str = "log") -> bytes:
    """The four S-parameters as a 2x2 grid (S11 S21 / S12 S22), magnitude in dB.

    Layout mirrors the PicoVNA 5 software: S11 top-left, S21 top-right,
    S12 bottom-left, S22 bottom-right. ``xscale`` selects the frequency axis:
    "log" (default) or "linear".
    """
    f_mhz = result.frequencies_hz / 1e6
    fig, axs = plt.subplots(2, 2, figsize=(8, 6))
    panels = (
        (axs[0][0], result.s11, "S11"),
        (axs[0][1], result.s21, "S21"),
        (axs[1][0], result.s12, "S12"),
        (axs[1][1], result.s22, "S22"),
    )
    for ax, s, label in panels:
        ax.plot(f_mhz, 20 * np.log10(np.maximum(np.abs(s), 1e-12)), lw=1)
        ax.set_title(label)
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Magnitude (dB)")
        ax.set_xscale(xscale)
        ax.grid(True, alpha=0.3, which="both")
    return _fig_to_png(fig)


def summary_impedance(result: VnaSweepResult) -> float | None:
    """Single characteristic impedance (ohms): the mid-band median of Re(Z0).

    Z0 = sqrt(B/C) from the measured S-parameters (via the ABCD matrix), then
    the same robust mid-band median the offline metric uses
    (`summarize_characteristic_impedance`), so the capture readout and the
    processed `vna_metrics.csv` agree. None if no usable points exist.
    """
    abcd = sparams_to_abcd(
        result.s11, result.s21, result.s12, result.s22, z_ref=result.ref_impedance_ohm
    )
    return summarize_characteristic_impedance(np.real(characteristic_impedance(abcd)))
