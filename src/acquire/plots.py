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


def _fig_to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=120)
    plt.close(fig)
    return buffer.getvalue()


def render_eye(eye: EyeDiagram) -> bytes:
    """Heatmap of the eye diagram's error counts (log scale)."""
    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    counts = eye.error_counts.astype(float)
    im = ax.imshow(
        np.log1p(counts),
        origin="lower",
        aspect="auto",
        extent=(
            eye.time_range_ps[0],
            eye.time_range_ps[1],
            eye.voltage_range_mv[0],
            eye.voltage_range_mv[1],
        ),
        cmap="inferno",
    )
    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Voltage (mV)")
    ax.set_title(f"Eye: {eye.channel.value} @ {eye.rate.value} Gbps")
    fig.colorbar(im, ax=ax, label="log(1 + errors)")
    return _fig_to_png(fig)


def render_margin(sweep: MarginSweep) -> bytes:
    """Link-margin curve: error count vs TX amplitude."""
    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    amps = [p.tx_amplitude_mv for p in sweep.points]
    errors = [p.error_count for p in sweep.points]
    ax.plot(amps, errors, marker=".", ms=4)
    ax.set_xlabel("TX amplitude (mV)")
    ax.set_ylabel("Error count")
    ax.set_title(f"Link margin: {sweep.channel.value} @ {sweep.rate.value} Gbps")
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
