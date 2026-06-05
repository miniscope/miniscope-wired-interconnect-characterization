"""
Generate synthetic SerDes fixtures: raw eye-monitor grid CSVs + raw
link-margin CSVs for the three lanes (fwd_3g, fwd_6g, rev_187m).

Uses the SimulatedSerdesDriver so the fixture format always matches what the
acquisition app would actually write. Run to regenerate fixture files:

    python tests/fixtures/generate_serdes_fixtures.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.instruments.serdes.driver import SerdesConfig
from src.instruments.serdes.simulator import SimulatedSerdesDriver
from src.instruments.types import FORWARD_3G, FORWARD_6G, SerdesLane, SerdesResult

FIXTURES_DIR = Path(__file__).parent
EYE_BINS = 16  # small grid keeps fixtures compact but structurally valid


def _clean(session_dir: Path) -> None:
    for pattern in ("eye_*.npz", "eye_*.csv", "margin_*.csv", "session_manifest.csv"):
        for path in session_dir.glob(pattern):
            path.unlink()


def _write_result(session_dir: Path, result: SerdesResult) -> list[dict[str, str]]:
    margins = {m.lane: m for m in result.margins}
    rows: list[dict[str, str]] = []
    for eye in result.eyes:
        lane = eye.lane
        eye_csv = f"eye_{lane.lane_id}.csv"
        with open(session_dir / eye_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["phase", "vth", "polarity", "hits", "errors"])
            for ph, vt, pol, hit, err in zip(
                eye.phase, eye.vth, eye.polarity, eye.hits, eye.errors, strict=True
            ):
                w.writerow([int(ph), int(vt), int(pol), int(hit), int(err)])

        margin_csv = f"margin_{lane.lane_id}.csv"
        with open(session_dir / margin_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["tx_amp_mv", "code", "rep", "locked", "errors", "status"])
            for p in margins[lane].points:
                w.writerow([p.tx_amplitude_mv, p.code, p.rep, int(p.locked), p.errors, p.status])

        rows.append(
            {
                "lane_id": lane.lane_id,
                "channel": lane.channel.value,
                "rate_gbps": f"{lane.rate.gbps:g}",
                "eye_csv": eye_csv,
                "margin_csv": margin_csv,
            }
        )
    return rows


def _write_manifest(session_dir: Path, rows: list[dict[str, str]]) -> None:
    with open(session_dir / "session_manifest.csv", "w", newline="") as f:
        fieldnames = ["lane_id", "channel", "rate_gbps", "eye_csv", "margin_csv"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def generate_session(
    session_dir: Path,
    cable_length_mm: float,
    seed: int = 0,
    lanes: tuple[SerdesLane, ...] | None = None,
) -> list[dict[str, str]]:
    """Write all configured lanes for one session; returns the manifest rows."""
    session_dir.mkdir(parents=True, exist_ok=True)
    _clean(session_dir)
    driver = SimulatedSerdesDriver(cable_length_mm=cable_length_mm, seed=seed)
    config = (
        SerdesConfig(eye_bins=EYE_BINS)
        if lanes is None
        else SerdesConfig(eye_bins=EYE_BINS, lanes=lanes)
    )
    result = driver.run_full_sequence(config=config)
    rows = _write_result(session_dir, result)
    _write_manifest(session_dir, rows)
    return rows


def main() -> None:
    serdes_500 = FIXTURES_DIR / "measurements" / "test_cable" / "500mm" / "serdes"
    serdes_1000 = FIXTURES_DIR / "measurements" / "test_cable" / "1000mm" / "serdes"
    serdes_comm = FIXTURES_DIR / "measurements" / "test_commutator" / "static" / "serdes"
    bad_serdes = FIXTURES_DIR / "measurements_bad" / "test_cable" / "500mm" / "serdes"

    # Valid sessions: longer cable -> smaller eye, higher error onset.
    generate_session(serdes_500 / "20250401_01", cable_length_mm=500.0, seed=1)
    generate_session(serdes_1000 / "20250402_01", cable_length_mm=1000.0, seed=2)
    # Commutator measured through short jumpers: nearly-clean eye.
    generate_session(serdes_comm / "20250503_01", cable_length_mm=100.0, seed=3)

    # Bad session: manifest missing the reverse lane.
    generate_session(
        bad_serdes / "20250403_01", cable_length_mm=500.0, seed=4, lanes=(FORWARD_3G, FORWARD_6G)
    )

    # Bad session: one eye CSV is missing the required 'errors' column.
    rows = generate_session(bad_serdes / "20250404_01", cable_length_mm=500.0, seed=5)
    bad_eye = bad_serdes / "20250404_01" / rows[0]["eye_csv"]
    bad_eye.write_text("phase,vth,polarity,hits\n0,0,0,32768\n0,0,1,32768\n")

    # Bad session: one margin CSV has the wrong columns.
    rows = generate_session(bad_serdes / "20250405_01", cable_length_mm=500.0, seed=6)
    bad_margin = bad_serdes / "20250405_01" / rows[0]["margin_csv"]
    bad_margin.write_text("amplitude,errors\n100,0\n50,12\n")

    print("Generated all SerDes fixtures successfully.")


if __name__ == "__main__":
    main()
