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


def render_attenuation(result: VnaSweepResult) -> bytes:
    """Attenuation (|S21| in dB, sign-flipped) vs frequency."""
    fig, ax = plt.subplots(figsize=(6, 3.5))
    attenuation_db = -20 * np.log10(np.maximum(np.abs(result.s21), 1e-12))
    ax.plot(result.frequencies_hz / 1e6, attenuation_db)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Attenuation (dB)")
    ax.set_title("Cable attenuation (from S21)")
    ax.set_xscale("log")
    ax.grid(True, alpha=0.3, which="both")
    return _fig_to_png(fig)
