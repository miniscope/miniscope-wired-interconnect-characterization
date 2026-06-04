"""
Generate synthetic SerDes eye-diagram (.npz) and link-margin (.csv) fixtures.

Run this script to regenerate fixture files:
    python tests/fixtures/generate_serdes_fixtures.py
"""

from pathlib import Path

import numpy as np

FIXTURES_DIR = Path(__file__).parent

CHANNELS = ["forward", "back"]
RATES_GBPS = [3, 6]


def generate_eye_npz(
    output_path: Path,
    v_bins: int = 64,
    t_bins: int = 64,
    open_fraction: float = 0.6,
    seed: int = 0,
) -> None:
    """
    Generate a synthetic eye diagram: a 2D error-count histogram with a
    clean elliptical opening in the middle and noisy errors elsewhere.
    """
    rng = np.random.default_rng(seed)

    v = np.linspace(-1, 1, v_bins)[:, None]
    t = np.linspace(-1, 1, t_bins)[None, :]

    # Elliptical eye opening: cells inside the ellipse are error-free.
    inside = (v / open_fraction) ** 2 + (t / open_fraction) ** 2 < 1.0

    error_counts = rng.integers(1, 200, size=(v_bins, t_bins))
    error_counts[inside] = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        output_path,
        error_counts=error_counts.astype(np.int64),
        voltage_range_mv=np.array([-400.0, 400.0]),
        time_range_ps=np.array([0.0, 333.0]),
    )


def generate_margin_csv(
    output_path: Path,
    onset_mv: float = 60.0,
    max_mv: float = 200.0,
) -> None:
    """
    Generate a synthetic link-margin sweep: coarse 10 mV steps across the
    full range plus fine 1 mV steps around the error onset. Zero errors
    above the onset, rapidly growing errors below it (capped at 255).
    """
    coarse = np.arange(10.0, max_mv + 1, 10.0)
    fine = np.arange(max(onset_mv - 15.0, 1.0), onset_mv + 15.0, 1.0)
    amps = np.unique(np.concatenate([coarse, fine]))

    rows = []
    for amp in amps:
        if amp > onset_mv:
            errors = 0
        else:
            errors = min(255, int((onset_mv - amp + 1) ** 2))
        rows.append((amp, errors))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("tx_amplitude_mv,error_count\n")
        for amp, errors in rows:
            f.write(f"{amp:.1f},{errors}\n")


def generate_session(session_dir: Path, base_open: float, base_onset: float) -> None:
    """Generate all 4 channel/rate combos for one session."""
    for i, channel in enumerate(CHANNELS):
        for j, rate in enumerate(RATES_GBPS):
            # Higher rate and back channel get slightly worse signal quality
            open_fraction = base_open - 0.1 * j - 0.05 * i
            onset = base_onset + 15.0 * j + 5.0 * i
            seed = 10 * i + j

            generate_eye_npz(
                session_dir / f"eye_{channel}_{rate}g.npz",
                open_fraction=open_fraction,
                seed=seed,
            )
            generate_margin_csv(
                session_dir / f"margin_{channel}_{rate}g.csv",
                onset_mv=onset,
            )


def generate_bad_npz_session(session_dir: Path) -> None:
    """Session whose npz files are missing required keys."""
    for channel in CHANNELS:
        for rate in RATES_GBPS:
            path = session_dir / f"eye_{channel}_{rate}g.npz"
            path.parent.mkdir(parents=True, exist_ok=True)
            # Missing voltage_range_mv / time_range_ps
            np.savez(path, error_counts=np.zeros((8, 8), dtype=np.int64))
            generate_margin_csv(session_dir / f"margin_{channel}_{rate}g.csv")


def generate_bad_margin_session(session_dir: Path) -> None:
    """Session whose margin CSVs have the wrong columns."""
    for channel in CHANNELS:
        for rate in RATES_GBPS:
            generate_eye_npz(session_dir / f"eye_{channel}_{rate}g.npz")
            csv_path = session_dir / f"margin_{channel}_{rate}g.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text("amplitude,errors\n100,0\n50,12\n")


def main() -> None:
    serdes_500 = FIXTURES_DIR / "measurements" / "test_cable" / "500mm" / "serdes"
    serdes_1000 = FIXTURES_DIR / "measurements" / "test_cable" / "1000mm" / "serdes"
    serdes_comm = FIXTURES_DIR / "measurements" / "test_commutator" / "static" / "serdes"
    bad_serdes = FIXTURES_DIR / "measurements_bad" / "test_cable" / "500mm" / "serdes"

    # Valid sessions: longer cable -> smaller eye, higher error onset
    generate_session(serdes_500 / "20250401_01", base_open=0.7, base_onset=50.0)
    generate_session(serdes_1000 / "20250402_01", base_open=0.55, base_onset=80.0)

    # Commutator measured through short jumpers: nearly-clean eye
    generate_session(serdes_comm / "20250503_01", base_open=0.75, base_onset=40.0)

    # Bad session: manifest missing a combo (files exist for listed combos)
    missing_combo_dir = bad_serdes / "20250403_01"
    for channel, rate in [("forward", 3), ("forward", 6), ("back", 3)]:
        generate_eye_npz(missing_combo_dir / f"eye_{channel}_{rate}g.npz")
        generate_margin_csv(missing_combo_dir / f"margin_{channel}_{rate}g.csv")

    # Bad session: npz missing keys
    generate_bad_npz_session(bad_serdes / "20250404_01")

    # Bad session: margin CSV wrong columns
    generate_bad_margin_session(bad_serdes / "20250405_01")

    print("Generated all SerDes fixtures successfully.")


if __name__ == "__main__":
    main()
