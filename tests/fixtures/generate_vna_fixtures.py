"""
Generate synthetic .s2p Touchstone fixtures for testing.

Run this script to regenerate fixture files:
    python tests/fixtures/generate_vna_fixtures.py
"""

from pathlib import Path

import numpy as np

FIXTURES_DIR = Path(__file__).parent


def generate_s2p(
    output_path: Path,
    freq_start_hz: float = 1e6,
    freq_stop_hz: float = 1e9,
    num_points: int = 101,
    base_insertion_loss_db: float = -3.0,
    freq_slope_db_per_ghz: float = -5.0,
    return_loss_db: float = -15.0,
    freq_unit: str = "MHZ",
    format_type: str = "DB",
    ref_impedance: float = 50.0,
) -> None:
    """Generate a synthetic .s2p file with realistic-looking S-parameters."""
    freqs = np.linspace(freq_start_hz, freq_stop_hz, num_points)

    if freq_unit == "MHZ":
        freq_col = freqs / 1e6
    elif freq_unit == "GHZ":
        freq_col = freqs / 1e9
    elif freq_unit == "KHZ":
        freq_col = freqs / 1e3
    else:
        freq_col = freqs

    s21_db = base_insertion_loss_db + freq_slope_db_per_ghz * (freqs / 1e9)
    s21_phase = -45.0 - 90.0 * (freqs / freq_stop_hz)

    s11_db = return_loss_db * np.ones_like(freqs)
    s11_db += 3.0 * np.sin(2 * np.pi * freqs / freq_stop_hz)
    s11_phase = 30.0 + 60.0 * (freqs / freq_stop_hz)

    s12_db = s21_db.copy()
    s12_phase = s21_phase.copy()

    s22_db = s11_db.copy() - 2.0
    s22_phase = s11_phase.copy() + 10.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(f"! Synthetic S2P fixture: {output_path.name}\n")
        f.write("! Generated for testing purposes\n")
        f.write(f"# {freq_unit} S {format_type} R {ref_impedance:.0f}\n")
        for i in range(num_points):
            f.write(
                f"{freq_col[i]:.6f}  "
                f"{s11_db[i]:.4f} {s11_phase[i]:.4f}  "
                f"{s21_db[i]:.4f} {s21_phase[i]:.4f}  "
                f"{s12_db[i]:.4f} {s12_phase[i]:.4f}  "
                f"{s22_db[i]:.4f} {s22_phase[i]:.4f}\n"
            )


def generate_bad_s2p(output_path: Path) -> None:
    """Generate a malformed .s2p file with no data."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("! Bad S2P file\n")
        f.write("! No option line, no data\n")


def main() -> None:
    vna_sessions = FIXTURES_DIR / "measurements" / "test_cable" / "1000mm" / "vna"
    bad_vna_sessions = FIXTURES_DIR / "measurements_bad" / "test_cable" / "1000mm" / "vna"

    # --- Valid session with two repeat sweeps ---
    raw_dir = vna_sessions / "20250301_01" / "raw"
    generate_s2p(
        raw_dir / "sweep_01.s2p",
        base_insertion_loss_db=-1.5,
        freq_slope_db_per_ghz=-3.0,
    )
    generate_s2p(
        raw_dir / "sweep_02.s2p",
        base_insertion_loss_db=-1.6,
        freq_slope_db_per_ghz=-3.1,
    )

    # --- Minimal session with one sweep ---
    generate_s2p(
        vna_sessions / "20250302_01" / "raw" / "sweep_01.s2p",
        num_points=21,
    )

    # --- Bad s2p format ---
    generate_bad_s2p(bad_vna_sessions / "20250305_01" / "raw" / "bad_file.s2p")

    print("Generated all VNA fixtures successfully.")


if __name__ == "__main__":
    main()
