"""
Pure math for SerDes eye-monitor grids and link-margin sweeps.

The eye is stored as the deserializer's raw eye-on-monitor (EOM) grid: one row
per measured (phase, vth, polarity) point with hit + error counts. This module
turns that grid into physical eye openings and a quality scalar, and turns a
link-margin sweep (tx amplitude vs decode errors) into a link-margin floor.

Register codes map to physical axes with fixed deserializer constants:
  - phase 0..127 spans UI_FULL_SCALE unit intervals (horizontal)
  - vth   0..63  per polarity spans V_FULL_SCALE_MV millivolts (one half)

These functions are deliberately free of file I/O so they can be reused by the
processor, the acquisition app's live previews, and tests.
"""

from __future__ import annotations

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Deserializer eye-monitor full-scale extents (MAX96716A EOM).
V_FULL_SCALE_MV = 315.0  # one polarity half spans +/- this in mV
UI_FULL_SCALE = 2.0  # the 128 phase codes span ~2 unit intervals
MAX_VTH = 64
MAX_PHASE = 128

# Cells with an error ratio at/under this are treated as inside the open eye.
BER_THRESHOLD = 1e-3
_CLOSED = 2.0  # sentinel ratio for missing grid cells (always > threshold)


def _error_ratio(errors: np.ndarray, hits: np.ndarray) -> np.ndarray:
    """Per-point error ratio; timeouts (errors < 0) are fully closed (1.0)."""
    errors = np.asarray(errors, dtype=float)
    hits = np.asarray(hits, dtype=float)
    ratio = np.where(hits > 0, errors / np.maximum(hits, 1.0), 1.0)
    return np.where(errors < 0, 1.0, ratio)


def reconstruct_grids(
    phase: np.ndarray,
    vth: np.ndarray,
    polarity: np.ndarray,
    errors: np.ndarray,
    hits: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Rebuild (positive_half, negative_half, phase_codes) error-ratio grids of
    shape (n_vth, n_phase) from the flat EOM rows. Missing cells are _CLOSED.
    """
    phase = np.asarray(phase, dtype=int)
    vth = np.asarray(vth, dtype=int)
    polarity = np.asarray(polarity, dtype=int)
    ratio = _error_ratio(errors, hits)

    phase_codes = np.unique(phase)
    vth_codes = np.unique(vth)
    p_index = {c: i for i, c in enumerate(phase_codes)}
    v_index = {c: i for i, c in enumerate(vth_codes)}

    pos = np.full((len(vth_codes), len(phase_codes)), _CLOSED)
    neg = np.full((len(vth_codes), len(phase_codes)), _CLOSED)
    for ph, vt, pol, r in zip(phase, vth, polarity, ratio, strict=True):
        grid = pos if pol == 1 else neg
        grid[v_index[vt], p_index[ph]] = r
    return pos, neg, phase_codes


def _longest_open_run(row: np.ndarray, threshold: float) -> np.ndarray:
    """Indices of the longest contiguous open (<= threshold) run in a 1D row."""
    open_idx = np.where(row <= threshold)[0]
    if len(open_idx) == 0:
        return open_idx
    gaps = np.where(np.diff(open_idx) > 1)[0]
    runs = np.split(open_idx, gaps + 1) if len(gaps) else [open_idx]
    return max(runs, key=len)


def extract_eye_opening(
    phase: np.ndarray,
    vth: np.ndarray,
    polarity: np.ndarray,
    errors: np.ndarray,
    hits: np.ndarray,
    threshold: float = BER_THRESHOLD,
) -> dict[str, float]:
    """
    Eye-opening metrics from the raw EOM grid.

    Returns:
    - eye_area_ratio:      fraction of measured cells inside the open eye
    - zero_error_fraction: fraction of measured cells with exactly zero errors
    - eye_height_mv:       vertical opening at the eye center (pos + neg)
    - eye_width_ui:        horizontal opening at the center voltage row
    """
    errors_arr = np.asarray(errors)
    valid = errors_arr >= 0
    n_valid = int(valid.sum())
    ratio = _error_ratio(errors, hits)

    area_ratio = float((valid & (ratio <= threshold)).sum() / n_valid) if n_valid else 0.0
    zero_error = float((valid & (errors_arr == 0)).sum() / n_valid) if n_valid else 0.0

    pos, neg, phase_codes = reconstruct_grids(phase, vth, polarity, errors, hits)
    n_vth, n_phase = pos.shape

    eye_width_ui = 0.0
    eye_height_mv = 0.0
    if n_phase and n_vth:
        # Center voltage row is the smallest vth code (closest to the eye axis);
        # use whichever half resolves the wider opening there.
        center_pos = _longest_open_run(pos[0, :], threshold)
        center_neg = _longest_open_run(neg[0, :], threshold)
        center = center_pos if len(center_pos) >= len(center_neg) else center_neg
        if len(center):
            eye_width_ui = len(center) / n_phase * UI_FULL_SCALE
            col = int(np.median(center))
            vp = int(np.sum(pos[:, col] <= threshold)) * V_FULL_SCALE_MV / n_vth
            vn = int(np.sum(neg[:, col] <= threshold)) * V_FULL_SCALE_MV / n_vth
            eye_height_mv = vp + vn

    return {
        "eye_area_ratio": round(area_ratio, 6),
        "zero_error_fraction": round(zero_error, 6),
        "eye_height_mv": round(eye_height_mv, 3),
        "eye_width_ui": round(eye_width_ui, 6),
    }


def eye_figure(
    phase: np.ndarray,
    vth: np.ndarray,
    polarity: np.ndarray,
    errors: np.ndarray,
    hits: np.ndarray,
    channel: str,
    rate: str,
):
    """
    Heatmap figure of the eye (error ratio, ADI-style axes: UI x mV).

    Returns a matplotlib Figure (no file I/O): the pipeline saves it to a PNG,
    the live preview encodes it to bytes. Shared so the saved diagram and the
    in-app preview never drift apart.
    """
    pos, neg, _ = reconstruct_grids(phase, vth, polarity, errors, hits)
    # Positive half on top (flipped), negative half on the bottom.
    eye = np.vstack([np.flipud(pos), neg])
    eye = np.where(eye >= _CLOSED, np.nan, eye)

    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    im = ax.imshow(
        eye,
        origin="lower",
        aspect="auto",
        extent=(0.0, UI_FULL_SCALE, -V_FULL_SCALE_MV, V_FULL_SCALE_MV),
        cmap="inferno_r",
        vmin=0.0,
        vmax=1.0,
    )
    ax.set_xlabel("Phase (UI)")
    ax.set_ylabel("Voltage (mV)")
    ax.set_title(f"Eye: {channel} @ {rate}")
    fig.colorbar(im, ax=ax, label="Error ratio")
    return fig


def link_margin_metrics(
    tx_amplitude_mv: np.ndarray,
    error_count: np.ndarray,
) -> dict[str, float | None]:
    """
    Compute link-margin metrics from a sweep of (tx_amplitude_mv, error_count).

    The sweep decreases TX amplitude until bit errors appear. We report:
    - link_margin_mv: the smallest amplitude that is error-free AND above
      every amplitude that produced errors (i.e. the reliable floor).
    - error_onset_mv: the largest amplitude that produced errors
      (None if the link never errored in the swept range).

    A lost-lock / unreachable step (error_count < 0) is treated as erroring.
    """
    amps = np.asarray(tx_amplitude_mv, dtype=float)
    raw = np.asarray(error_count, dtype=float)
    errs = np.where(raw < 0, 1.0, raw)  # lock loss counts as an error

    order = np.argsort(amps)
    amps = amps[order]
    errs = errs[order]

    erroring = amps[errs > 0]
    error_onset = float(np.max(erroring)) if len(erroring) else None

    clean = amps[errs == 0]
    if error_onset is not None:
        clean = clean[clean > error_onset]

    link_margin = float(np.min(clean)) if len(clean) else None

    return {
        "link_margin_mv": link_margin,
        "error_onset_mv": error_onset,
    }
