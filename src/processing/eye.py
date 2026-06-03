"""
Pure math for SerDes eye diagrams and link-margin sweeps.

An eye diagram here is a 2D histogram of error counts over
(voltage bins x time bins): zero-error cells form the open "eye" in the
middle. A link-margin sweep is a 1D series of (tx_amplitude_mv,
error_count) points: the link margin is the smallest TX amplitude that
still transmits without errors.

These functions are deliberately free of file I/O so they can be reused
by the processor, the acquisition app's live previews, and tests.
"""

from __future__ import annotations

import numpy as np


def _longest_zero_run(arr: np.ndarray) -> tuple[int, int]:
    """
    Find the longest contiguous run of zeros in a 1D array.

    Returns (start_index, length). If no zeros found, returns (0, 0).
    """
    if len(arr) == 0:
        return (0, 0)

    is_zero = arr == 0
    best_start = 0
    best_len = 0
    current_start = 0
    current_len = 0

    for i, z in enumerate(is_zero):
        if z:
            if current_len == 0:
                current_start = i
            current_len += 1
            if current_len > best_len:
                best_start = current_start
                best_len = current_len
        else:
            current_len = 0

    return (best_start, best_len)


def extract_eye_opening(eye_2d: np.ndarray) -> dict[str, float]:
    """
    Extract eye opening metrics from a 2D error-count histogram
    (axis 0 = voltage bins, axis 1 = time bins).

    Uses center-scan: scan the center time-column for eye height and the
    center voltage-row for eye width.

    Returns dict with: eye_height_bins, eye_width_bins,
    eye_height_ratio, eye_width_ratio, eye_area_ratio.

    TODO (deferred decision): additional eye metrics under consideration --
    timing jitter from the time-marginal distribution, Q-factor, and a
    BER-contour-based opening. Add here once the real SerDes data shows
    which are informative.
    """
    v_bins, t_bins = eye_2d.shape

    center_col = eye_2d[:, t_bins // 2]
    _, height_bins = _longest_zero_run(center_col)

    center_row = eye_2d[v_bins // 2, :]
    _, width_bins = _longest_zero_run(center_row)

    height_ratio = height_bins / v_bins if v_bins > 0 else 0.0
    width_ratio = width_bins / t_bins if t_bins > 0 else 0.0

    return {
        "eye_height_bins": int(height_bins),
        "eye_width_bins": int(width_bins),
        "eye_height_ratio": round(float(height_ratio), 6),
        "eye_width_ratio": round(float(width_ratio), 6),
        "eye_area_ratio": round(float(height_ratio * width_ratio), 6),
    }


def eye_opening_physical(
    metrics: dict[str, float],
    voltage_range_mv: np.ndarray,
    time_range_ps: np.ndarray,
) -> dict[str, float]:
    """
    Convert bin-based eye metrics to physical units using the axis ranges
    stored alongside the histogram.
    """
    v_span = float(voltage_range_mv[1] - voltage_range_mv[0])
    t_span = float(time_range_ps[1] - time_range_ps[0])
    return {
        "eye_height_mv": round(metrics["eye_height_ratio"] * v_span, 3),
        "eye_width_ps": round(metrics["eye_width_ratio"] * t_span, 3),
    }


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
    """
    order = np.argsort(tx_amplitude_mv)
    amps = np.asarray(tx_amplitude_mv, dtype=float)[order]
    errs = np.asarray(error_count, dtype=float)[order]

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
