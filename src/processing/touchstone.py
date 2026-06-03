"""Lightweight Touchstone .s2p file parser for 2-port S-parameter data."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

FREQ_MULTIPLIERS = {
    "HZ": 1.0,
    "KHZ": 1e3,
    "MHZ": 1e6,
    "GHZ": 1e9,
}


@dataclass
class TouchstoneData:
    """Parsed 2-port Touchstone data.

    S-parameters are kept both as dB magnitude (the historical fields, used
    for attenuation/return-loss curves) and as complex linear values (used by
    analyses that need phase, e.g. characteristic-impedance extraction).
    """

    frequencies_hz: np.ndarray
    s11_db: np.ndarray
    s21_db: np.ndarray
    s12_db: np.ndarray
    s22_db: np.ndarray
    ref_impedance: float = 50.0
    format_type: str = "DB"
    freq_unit: str = "GHZ"
    num_points: int = 0
    frequency_start_hz: float = 0.0
    frequency_stop_hz: float = 0.0
    metadata: dict = field(default_factory=dict)
    # Complex linear S-parameters (magnitude AND phase preserved).
    s11: np.ndarray = field(default_factory=lambda: np.array([], dtype=complex))
    s21: np.ndarray = field(default_factory=lambda: np.array([], dtype=complex))
    s12: np.ndarray = field(default_factory=lambda: np.array([], dtype=complex))
    s22: np.ndarray = field(default_factory=lambda: np.array([], dtype=complex))


def _ma_to_db(magnitude: np.ndarray) -> np.ndarray:
    """Convert linear magnitude to dB. Handles zeros by clamping."""
    magnitude = np.maximum(magnitude, 1e-15)
    return 20.0 * np.log10(magnitude)


def _ri_to_db(real: np.ndarray, imag: np.ndarray) -> np.ndarray:
    """Convert real/imaginary to dB magnitude."""
    magnitude = np.sqrt(real**2 + imag**2)
    return _ma_to_db(magnitude)


def _to_complex(col_a: np.ndarray, col_b: np.ndarray, format_type: str) -> np.ndarray:
    """Convert a Touchstone S-parameter column pair to complex linear values."""
    if format_type == "RI":
        return col_a + 1j * col_b
    if format_type == "MA":
        return col_a * np.exp(1j * np.deg2rad(col_b))
    # DB: col_a is dB magnitude, col_b is phase in degrees.
    return 10.0 ** (col_a / 20.0) * np.exp(1j * np.deg2rad(col_b))


def parse_s2p(path: Path) -> TouchstoneData:
    """
    Parse a Touchstone .s2p file.

    Supports formats: DB (dB/angle), MA (magnitude/angle), RI (real/imaginary).
    Supports frequency units: HZ, KHZ, MHZ, GHZ.

    Returns a TouchstoneData with all S-parameters in dB magnitude.
    """
    freq_mult = 1e9  # default GHz
    format_type = "DB"
    freq_unit = "GHZ"
    ref_impedance = 50.0
    comments: list[str] = []

    data_lines: list[str] = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("!"):
                comments.append(line[1:].strip())
                continue
            if line.startswith("#"):
                parts = line[1:].split()
                parts_upper = [p.upper() for p in parts]
                for i, p in enumerate(parts_upper):
                    if p in FREQ_MULTIPLIERS:
                        freq_unit = p
                        freq_mult = FREQ_MULTIPLIERS[p]
                    elif p in ("DB", "MA", "RI"):
                        format_type = p
                    elif p == "R" and i + 1 < len(parts_upper):
                        try:
                            ref_impedance = float(parts[i + 1])
                        except ValueError:
                            pass
                continue
            data_lines.append(line)

    if not data_lines:
        raise ValueError(f"No data found in {path}")

    rows: list[list[float]] = []
    for line in data_lines:
        values = [float(v) for v in line.split()]
        rows.append(values)

    data = np.array(rows)
    if data.shape[1] < 9:
        raise ValueError(
            f"Expected at least 9 columns for 2-port S-parameters, got {data.shape[1]} in {path}"
        )

    freqs = data[:, 0] * freq_mult

    if format_type == "DB":
        s11_db = data[:, 1]
        s21_db = data[:, 3]
        s12_db = data[:, 5]
        s22_db = data[:, 7]
    elif format_type == "MA":
        s11_db = _ma_to_db(data[:, 1])
        s21_db = _ma_to_db(data[:, 3])
        s12_db = _ma_to_db(data[:, 5])
        s22_db = _ma_to_db(data[:, 7])
    elif format_type == "RI":
        s11_db = _ri_to_db(data[:, 1], data[:, 2])
        s21_db = _ri_to_db(data[:, 3], data[:, 4])
        s12_db = _ri_to_db(data[:, 5], data[:, 6])
        s22_db = _ri_to_db(data[:, 7], data[:, 8])
    else:
        raise ValueError(f"Unsupported format type: {format_type}")

    s11 = _to_complex(data[:, 1], data[:, 2], format_type)
    s21 = _to_complex(data[:, 3], data[:, 4], format_type)
    s12 = _to_complex(data[:, 5], data[:, 6], format_type)
    s22 = _to_complex(data[:, 7], data[:, 8], format_type)

    return TouchstoneData(
        frequencies_hz=freqs,
        s11_db=s11_db,
        s21_db=s21_db,
        s12_db=s12_db,
        s22_db=s22_db,
        ref_impedance=ref_impedance,
        format_type=format_type,
        freq_unit=freq_unit,
        num_points=len(freqs),
        frequency_start_hz=float(freqs[0]) if len(freqs) > 0 else 0.0,
        frequency_stop_hz=float(freqs[-1]) if len(freqs) > 0 else 0.0,
        metadata={"comments": comments},
        s11=s11,
        s21=s21,
        s12=s12,
        s22=s22,
    )
