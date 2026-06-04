"""
Project signal quality from VNA attenuation for link rates without eye
hardware (ADR 0001, build step 3).

GMSL2 Miniscopes get a measured eye/link-margin quality curve at their
rate. An FPD-Link III Miniscope (e.g. the V4) has no eye-capture hardware
on the bench, so its quality-vs-length guidance is PROJECTED from the
cable's measured VNA attenuation, evaluated at the link's Nyquist
fundamental (rate/2). Projected results are always tagged as such; they
become more credible once a VNA->eye correlation exists from the GMSL2
data.
"""

from __future__ import annotations

import numpy as np


def nyquist_hz(rate_gbps: float) -> float:
    """Nyquist fundamental of an NRZ link: half the bit rate."""
    return rate_gbps / 2.0 * 1e9


def attenuation_at_hz(
    attenuation_db_by_hz: dict[str, float] | dict[float, float],
    target_hz: float,
) -> float | None:
    """
    Interpolate a consolidated attenuation-by-frequency map (as produced by
    the VNA processing/consolidation stages; keys are Hz, possibly strings
    after JSON round-tripping) at a target frequency.

    Returns None when the map is empty or the target lies outside the
    measured span -- we never extrapolate beyond the sweep.
    """
    if not attenuation_db_by_hz:
        return None

    pairs = sorted((float(k), float(v)) for k, v in attenuation_db_by_hz.items())
    freqs = np.array([p[0] for p in pairs])
    values = np.array([p[1] for p in pairs])

    if target_hz < freqs[0] or target_hz > freqs[-1]:
        return None
    return float(np.interp(target_hz, freqs, values))
