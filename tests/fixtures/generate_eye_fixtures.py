"""
Generate synthetic .npz eye diagram fixtures for testing.

Each .npz contains an 'eye' array of shape (voltage_bins, time_bins, 2)
representing a 2D histogram of waveform transitions with a known eye opening.

Run this script to regenerate fixture files:
    python tests/fixtures/generate_eye_fixtures.py
"""

from pathlib import Path

import numpy as np

FIXTURES_DIR = Path(__file__).parent


def make_eye_histogram(
    v_bins: int = 64,
    t_bins: int = 64,
    eye_height_frac: float = 0.5,
    eye_width_frac: float = 0.5,
    noise_density: int = 5,
) -> np.ndarray:
    """
    Create a synthetic 2D eye histogram with a known rectangular opening.

    The histogram is filled with `noise_density` everywhere except the
    center rectangular region which is left as zeros.

    Args:
        v_bins: Number of voltage bins
        t_bins: Number of time bins
        eye_height_frac: Fraction of voltage range that is open (0 to 1)
        eye_width_frac: Fraction of time range that is open (0 to 1)
        noise_density: Fill value for non-zero bins

    Returns:
        2D array of shape (v_bins, t_bins) with int32 dtype
    """
    hist = np.full((v_bins, t_bins), noise_density, dtype=np.int32)

    h_bins = int(v_bins * eye_height_frac)
    w_bins = int(t_bins * eye_width_frac)
    v_start = (v_bins - h_bins) // 2
    t_start = (t_bins - w_bins) // 2

    hist[v_start : v_start + h_bins, t_start : t_start + w_bins] = 0

    return hist


def generate_fixture_npz(
    output_path: Path,
    v_bins: int = 64,
    t_bins: int = 64,
    rising_height_frac: float = 0.5,
    rising_width_frac: float = 0.5,
    falling_height_frac: float = 0.4,
    falling_width_frac: float = 0.4,
    voltage_range: tuple[float, float] | None = None,
    time_range: tuple[float, float] | None = None,
) -> None:
    """Generate a .npz fixture file with known eye openings."""
    rising = make_eye_histogram(v_bins, t_bins, rising_height_frac, rising_width_frac)
    falling = make_eye_histogram(v_bins, t_bins, falling_height_frac, falling_width_frac)
    eye = np.stack([rising, falling], axis=2)

    save_dict: dict = {"eye": eye}
    if voltage_range is not None:
        save_dict["voltage_range"] = np.array(voltage_range, dtype=np.float64)
    if time_range is not None:
        save_dict["time_range"] = np.array(time_range, dtype=np.float64)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(output_path, **save_dict)


def generate_bad_shape_npz(output_path: Path) -> None:
    """Generate a .npz with wrong array shape (2D instead of 3D)."""
    eye = np.zeros((64, 64), dtype=np.int32)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(output_path, eye=eye)


def main() -> None:
    # --- Valid experiment fixture ---
    valid_dir = FIXTURES_DIR / "experiments" / "eye_diagram" / "valid_experiment" / "raw"
    generate_fixture_npz(
        valid_dir / "eye_1000mm_10mbps.npz",
        rising_height_frac=0.5,
        rising_width_frac=0.5,
        falling_height_frac=0.4,
        falling_width_frac=0.4,
        voltage_range=(-500.0, 500.0),
        time_range=(0.0, 200000.0),
    )
    generate_fixture_npz(
        valid_dir / "eye_500mm_10mbps.npz",
        rising_height_frac=0.6,
        rising_width_frac=0.6,
        falling_height_frac=0.5,
        falling_width_frac=0.5,
        voltage_range=(-500.0, 500.0),
        time_range=(0.0, 200000.0),
    )

    # --- Valid minimal fixture ---
    minimal_dir = FIXTURES_DIR / "experiments" / "eye_diagram" / "valid_minimal" / "raw"
    generate_fixture_npz(
        minimal_dir / "eye_test.npz",
        rising_height_frac=0.5,
        rising_width_frac=0.5,
        falling_height_frac=0.5,
        falling_width_frac=0.5,
    )

    # --- Bad npz shape fixture ---
    bad_dir = FIXTURES_DIR / "experiments" / "eye_diagram" / "bad_npz_shape" / "raw"
    generate_bad_shape_npz(bad_dir / "bad_eye.npz")

    # --- Example experiment ---
    example_dir = (
        FIXTURES_DIR.parent.parent / "experiments" / "EXP_2025_02_01_eye_diagram_coax_40awg" / "raw"
    )
    for length, h_frac, w_frac in [
        (500, 0.6, 0.6),
        (1000, 0.5, 0.5),
        (1500, 0.4, 0.4),
        (2000, 0.3, 0.3),
    ]:
        generate_fixture_npz(
            example_dir / f"eye_{length}mm_10mbps.npz",
            rising_height_frac=h_frac,
            rising_width_frac=w_frac,
            falling_height_frac=h_frac - 0.05,
            falling_width_frac=w_frac - 0.05,
            voltage_range=(-500.0, 500.0),
            time_range=(0.0, 200000.0),
        )

    print("Generated all eye diagram fixtures successfully.")


if __name__ == "__main__":
    main()
