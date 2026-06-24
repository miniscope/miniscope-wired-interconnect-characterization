"""
Session writers: the ONLY way new measurement data enters the repository.

The acquisition app never serializes YAML/CSV/NPZ itself -- it hands the
driver result dataclasses to these functions, which:
1. allocate a session id (YYYYMMDD_NN) under the profile/length tree,
2. write session.yaml + the type's data files per the on-disk contract,
3. validate the freshly-written session against its measurement type
   definition, deleting it again if validation fails.

That last step is the guarantee that the app cannot produce data the CI
pipeline would reject.
"""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Any

import yaml

from src.core.loading import load_session
from src.core.session_schemas import length_dir_name
from src.core.session_validator import validate_session
from src.instruments.balance.driver import MassReading
from src.instruments.lcr.driver import ResistanceReading
from src.instruments.types import (
    DEFAULT_LANES,
    SerdesLane,
    SerdesResult,
    VnaSweepResult,
    group_margins_by_lane,
)
from src.instruments.vna.driver import write_s2p
from src.measurement_types.registry import MeasurementTypeRegistry

SESSION_SCHEMA_VERSION = "1.0"


@dataclass
class SessionMeta:
    """Who/when/why for a new session."""

    operator: str
    date: date_type
    notes: str = ""
    type_fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRef:
    """Identity + location of a written session."""

    profile_id: str
    condition: str  # '500mm' for cables, 'static' etc. for commutators
    cable_length_mm: float | None
    measurement_type: str
    session_id: str
    path: Path

    @property
    def ref(self) -> str:
        return "/".join(
            [
                self.profile_id,
                self.condition,
                self.measurement_type,
                self.session_id,
            ]
        )


class SessionWriteError(Exception):
    """Raised when a freshly-written session fails validation."""


def _condition_dir(cable_length_mm: float | None, condition: str | None) -> str:
    """Resolve the condition directory from a length or an explicit state."""
    if cable_length_mm is not None:
        return length_dir_name(cable_length_mm)
    if condition:
        return condition
    raise ValueError("Either cable_length_mm or condition is required")


def new_session_id(
    repo_root: Path,
    profile_id: str,
    cable_length_mm: float | None,
    measurement_type: str,
    when: date_type,
    condition: str | None = None,
) -> str:
    """Next free YYYYMMDD_NN id for this (profile, condition, type) on `when`."""
    type_dir = (
        repo_root
        / "measurements"
        / profile_id
        / _condition_dir(cable_length_mm, condition)
        / measurement_type
    )
    stamp = when.strftime("%Y%m%d")
    existing = {p.name for p in type_dir.glob(f"{stamp}_*")} if type_dir.exists() else set()
    n = 1
    while f"{stamp}_{n:02d}" in existing:
        n += 1
    return f"{stamp}_{n:02d}"


def _start_session(
    repo_root: Path,
    profile_id: str,
    cable_length_mm: float | None,
    measurement_type: str,
    meta: SessionMeta,
    condition: str | None = None,
) -> SessionRef:
    """Allocate the session directory and write session.yaml."""
    condition_dir = _condition_dir(cable_length_mm, condition)
    session_id = new_session_id(
        repo_root, profile_id, cable_length_mm, measurement_type, meta.date, condition=condition
    )
    session_dir = (
        repo_root / "measurements" / profile_id / condition_dir / measurement_type / session_id
    )
    session_dir.mkdir(parents=True)

    record = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "profile_id": profile_id,
        "condition": condition_dir,
        "measurement_type": measurement_type,
        "measurement_type_version": _latest_version(repo_root, measurement_type),
        "date": meta.date,
        "operator": meta.operator,
        "notes": meta.notes,
        "type_fields": meta.type_fields,
    }
    if cable_length_mm is not None:
        record["cable_length_mm"] = cable_length_mm
    with open(session_dir / "session.yaml", "w") as f:
        yaml.safe_dump(record, f, sort_keys=False)

    return SessionRef(
        profile_id=profile_id,
        condition=condition_dir,
        cable_length_mm=cable_length_mm,
        measurement_type=measurement_type,
        session_id=session_id,
        path=session_dir,
    )


def _latest_version(repo_root: Path, measurement_type: str) -> int:
    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    return registry.get_latest(measurement_type).version


def _finalize_session(repo_root: Path, ref: SessionRef) -> SessionRef:
    """
    Validate the just-written session exactly like the CI pipeline will.
    On failure, remove the session folder and raise.
    """
    from src.pipeline import _CSV_VALIDATORS, _SESSION_VALIDATORS

    session = load_session(ref.path / "session.yaml")
    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    definition = registry.get(session.measurement_type, session.measurement_type_version)

    result = validate_session(
        ref.path,
        session,
        definition,
        profiles_dir=repo_root / "profiles",
    )
    for filename, validator_fn, needs_session_dir in _CSV_VALIDATORS.get(
        session.measurement_type, []
    ):
        csv_path = ref.path / filename
        if csv_path.exists():
            if needs_session_dir:
                validator_fn(csv_path, result, session_dir=ref.path)
            else:
                validator_fn(csv_path, result)
    session_validator = _SESSION_VALIDATORS.get(session.measurement_type)
    if session_validator is not None:
        session_validator(ref.path, result)

    if not result.is_valid:
        shutil.rmtree(ref.path)
        raise SessionWriteError(
            "Refusing to save session that fails validation:\n  " + "\n  ".join(result.errors)
        )
    return ref


def write_resistance_session(
    repo_root: Path,
    profile_id: str,
    cable_length_mm: float | None,
    readings: list[ResistanceReading],
    meta: SessionMeta,
    condition: str | None = None,
) -> SessionRef:
    """Write a manual resistance session (resistance.csv)."""
    if not readings:
        raise ValueError("At least one resistance reading is required")

    ref = _start_session(
        repo_root, profile_id, cable_length_mm, "resistance", meta, condition=condition
    )
    with open(ref.path / "resistance.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["resistance_ohm", "notes"])
        for reading in readings:
            writer.writerow([reading.resistance_ohm, reading.note])

    return _finalize_session(repo_root, ref)


def write_mass_session(
    repo_root: Path,
    profile_id: str,
    cable_length_mm: float | None,
    readings: list[MassReading],
    meta: SessionMeta,
    condition: str | None = None,
) -> SessionRef:
    """Write a manual mass session (mass.csv)."""
    if not readings:
        raise ValueError("At least one mass reading is required")

    ref = _start_session(repo_root, profile_id, cable_length_mm, "mass", meta, condition=condition)
    with open(ref.path / "mass.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["assembly_mass_g", "fixture_mass_g", "notes"])
        for reading in readings:
            writer.writerow([reading.assembly_mass_g, reading.fixture_mass_g, reading.note])

    return _finalize_session(repo_root, ref)


def write_serdes_session(
    repo_root: Path,
    profile_id: str,
    cable_length_mm: float | None,
    result: SerdesResult,
    meta: SessionMeta,
    condition: str | None = None,
) -> SessionRef:
    """Write a SerDes session (session_manifest.csv + per-lane eye + margin CSVs)."""
    ref = _start_session(
        repo_root, profile_id, cable_length_mm, "serdes", meta, condition=condition
    )

    # A repeated margin sweep yields several sweeps per lane; persist each run
    # RAW (append-only) and let processing derive the average. Run 1 keeps the
    # plain margin_<lane>.csv name; repeats append as margin_<lane>_run<i>.csv.
    margins_by_lane = {
        lane.lane_id: sweeps for lane, sweeps in group_margins_by_lane(result.margins)
    }

    eyes_by_lane = {eye.lane.lane_id: eye for eye in result.eyes}
    no_link_ids = {lane.lane_id for lane in result.no_link_lanes}

    def write_eye_csv(lane: SerdesLane) -> str:
        """Write a lane's raw EOM grid; header-only when the lane has no eye."""
        eye = eyes_by_lane.get(lane.lane_id)
        eye_csv = f"eye_{lane.lane_id}.csv"
        with open(ref.path / eye_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["phase", "vth", "polarity", "hits", "errors"])
            if eye is not None:
                for ph, vt, pol, hit, err in zip(
                    eye.phase, eye.vth, eye.polarity, eye.hits, eye.errors, strict=True
                ):
                    writer.writerow([int(ph), int(vt), int(pol), int(hit), int(err)])
        return eye_csv

    def write_margin_csvs(lane: SerdesLane) -> tuple[str, int]:
        """Write a lane's raw margin run(s); one header-only run when it has none."""
        margin_csv = f"margin_{lane.lane_id}.csv"
        runs = [s.points for s in margins_by_lane.get(lane.lane_id, [])] or [[]]
        run_files = [margin_csv] + [
            f"margin_{lane.lane_id}_run{i}.csv" for i in range(2, len(runs) + 1)
        ]
        for filename, points in zip(run_files, runs, strict=True):
            with open(ref.path / filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["tx_amp_mv", "code", "rep", "locked", "errors", "status"])
                for p in points:
                    writer.writerow(
                        [p.tx_amplitude_mv, p.code, p.rep, int(p.locked), p.errors, p.status]
                    )
        return margin_csv, len(runs)

    # A serdes session always covers the three default lanes (the validator
    # enforces this), so write a row for each. Per lane:
    #   - captured           -> linked=1, real eye + margin data
    #   - no_link_lanes       -> linked=0, header-only files (scored 0 downstream)
    #   - neither (e.g. a link-check-only record where this lane did link but was
    #     not captured) -> linked=1, header-only files; processing yields null
    #     metrics, so it is dropped from scoring until a real capture covers it.
    manifest_rows: list[dict[str, str]] = []
    for lane in DEFAULT_LANES:
        eye_csv = write_eye_csv(lane)
        margin_csv, n_runs = write_margin_csvs(lane)
        manifest_rows.append(
            {
                "lane_id": lane.lane_id,
                "channel": lane.channel.value,
                "rate_gbps": f"{lane.rate.gbps:g}",
                "eye_csv": eye_csv,
                "margin_csv": margin_csv,
                "margin_iterations": str(n_runs),
                "linked": "0" if lane.lane_id in no_link_ids else "1",
            }
        )

    with open(ref.path / "session_manifest.csv", "w", newline="") as f:
        fieldnames = [
            "lane_id",
            "channel",
            "rate_gbps",
            "eye_csv",
            "margin_csv",
            "margin_iterations",
            "linked",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    return _finalize_session(repo_root, ref)


def write_vna_session(
    repo_root: Path,
    profile_id: str,
    cable_length_mm: float | None,
    result: VnaSweepResult,
    meta: SessionMeta,
    description: str = "",
    condition: str | None = None,
) -> SessionRef:
    """Write a VNA session (manifest.csv + raw/sweep_01.s2p)."""
    ref = _start_session(repo_root, profile_id, cable_length_mm, "vna", meta, condition=condition)

    filename = "sweep_01.s2p"
    write_s2p(result, ref.path / "raw" / filename)

    with open(ref.path / "manifest.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "description"])
        writer.writerow([filename, description])

    return _finalize_session(repo_root, ref)


def delete_session(repo_root: Path, ref: SessionRef) -> None:
    """
    Delete a session folder (and its derived outputs, if any).

    Sessions are just folders, so removing a bad one is cheap; the next
    pipeline run regenerates everything downstream.
    """
    if ref.path.exists():
        shutil.rmtree(ref.path)
    derived = repo_root / "derived" / "sessions" / Path(ref.ref)
    if derived.exists():
        shutil.rmtree(derived)
