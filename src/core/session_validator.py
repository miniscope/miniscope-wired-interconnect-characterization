from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import (
    COMMUTATOR_CONDITIONS,
    SessionRecord,
    parse_condition_dir,
)
from src.core.validation import TypeFieldValidator


@dataclass
class ValidationResult:
    """Collects errors and warnings from session validation."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


@dataclass
class SessionPathInfo:
    """Identity of a session as derived from its directory path."""

    profile_id: str
    condition: str
    cable_length_mm: float | None
    measurement_type: str
    session_id: str


def parse_session_path(session_dir: Path) -> SessionPathInfo:
    """
    Derive session identity from the directory layout:
        measurements/<profile_id>/<condition>/<measurement_type>/<session_id>/
    where the condition is a cable length ('500mm') or a commutator state
    ('static').
    """
    parts = session_dir.resolve().parts
    if len(parts) < 4:
        raise ValueError(f"Session path too shallow to parse: {session_dir}")
    profile_id, condition_dir, measurement_type, session_id = parts[-4:]
    return SessionPathInfo(
        profile_id=profile_id,
        condition=condition_dir,
        cable_length_mm=parse_condition_dir(condition_dir),
        measurement_type=measurement_type,
        session_id=session_id,
    )


def validate_session(
    session_dir: Path,
    session: SessionRecord,
    definition: MeasurementDefinition,
    profiles_dir: Path | None = None,
) -> ValidationResult:
    """
    Validate a session folder against its measurement type definition.

    Checks path<->yaml identity, type_fields, required files, and the
    profile reference.
    """
    result = ValidationResult()

    _validate_path_identity(session_dir, session, result)
    _validate_type_fields(session, definition, result)
    _validate_required_files(session_dir, definition, result)

    if profiles_dir is not None:
        _validate_profile_ref(session, profiles_dir, result)

    return result


def _validate_profile_ref(
    session: SessionRecord,
    profiles_dir: Path,
    result: ValidationResult,
) -> None:
    """The profile must exist, and its kind must match the session's condition."""
    profile_path = profiles_dir / f"{session.profile_id}.yaml"
    if not profile_path.exists():
        result.add_error(f"DUT profile '{session.profile_id}' not found at {profile_path}")
        return

    from src.core.loading import load_profile
    from src.core.profile_schemas import CableProfile

    try:
        profile = load_profile(profile_path)
    except Exception as e:
        result.add_error(f"DUT profile '{session.profile_id}' failed to load: {e}")
        return

    if isinstance(profile, CableProfile):
        if session.cable_length_mm is None:
            result.add_error(
                f"Cable profile '{session.profile_id}' requires a length condition, "
                f"got '{session.condition}'"
            )
    else:  # commutator
        if session.cable_length_mm is not None:
            result.add_error(
                f"Commutator profile '{session.profile_id}' takes a state condition "
                f"(e.g. 'static'), not a length ('{session.condition}')"
            )
        elif session.condition not in COMMUTATOR_CONDITIONS:
            result.add_error(
                f"Unknown commutator condition '{session.condition}' "
                f"(known: {sorted(COMMUTATOR_CONDITIONS)})"
            )


def _validate_path_identity(
    session_dir: Path,
    session: SessionRecord,
    result: ValidationResult,
) -> None:
    """The directory path is the source of truth; session.yaml must echo it."""
    try:
        info = parse_session_path(session_dir)
    except ValueError as e:
        result.add_error(str(e))
        return

    if session.profile_id != info.profile_id:
        result.add_error(
            f"profile_id mismatch: session.yaml says '{session.profile_id}' "
            f"but path says '{info.profile_id}'"
        )
    if session.condition != info.condition:
        result.add_error(
            f"condition mismatch: session.yaml says '{session.condition}' "
            f"but path says '{info.condition}'"
        )
    if session.cable_length_mm != info.cable_length_mm:
        result.add_error(
            f"cable_length_mm mismatch: session.yaml says {session.cable_length_mm} "
            f"but path says {info.cable_length_mm}"
        )
    if session.measurement_type != info.measurement_type:
        result.add_error(
            f"measurement_type mismatch: session.yaml says '{session.measurement_type}' "
            f"but path says '{info.measurement_type}'"
        )
    if session.session_id != info.session_id:
        result.add_error(
            f"session_id mismatch: session.yaml says '{session.session_id}' "
            f"but path says '{info.session_id}'"
        )


def _validate_type_fields(
    session: SessionRecord,
    definition: MeasurementDefinition,
    result: ValidationResult,
) -> None:
    """Delegate to TypeFieldValidator and collect errors."""
    validator = TypeFieldValidator(definition)
    errors = validator.validate(session.type_fields)
    for e in errors:
        result.add_error(e)


def _validate_required_files(
    session_dir: Path,
    definition: MeasurementDefinition,
    result: ValidationResult,
) -> None:
    """Check that every required FileSpec has a matching file."""
    for file_spec in definition.files:
        if not file_spec.required:
            continue
        matches = list(session_dir.glob(file_spec.filename_pattern))
        if not matches:
            result.add_error(
                f"Required file missing: '{file_spec.filename_pattern}' ({file_spec.name})"
            )


def _validate_data_csv(
    csv_path: Path,
    result: ValidationResult,
    *,
    required_columns: list[str],
    check_row: Callable[[int, dict], int],
    forbid_length_column: bool = False,
    max_errors: int = 10,
) -> None:
    """
    Shared scaffold for the per-type data-CSV validators.

    Handles opening the file, the empty-file and required-column checks, the
    forbidden cable_length_mm column, the capped per-row loop, and the
    header-only warning. Each validator supplies only its required columns
    and a ``check_row(line_number, row)`` callback that adds its own errors
    and returns how many it added (so the loop can enforce the error cap).
    """
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {csv_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]
            for col in required_columns:
                if col not in headers:
                    result.add_error(f"CSV missing required column: '{col}'")
            if forbid_length_column and "cable_length_mm" in headers:
                result.add_error(
                    "CSV must not contain 'cable_length_mm': length comes from "
                    "the session folder"
                )

            if not result.is_valid:
                return

            row_count = 0
            error_count = 0
            for i, row in enumerate(reader, start=2):
                row_count += 1
                if error_count >= max_errors:
                    result.add_error(f"... and more errors (stopped after {max_errors})")
                    break
                error_count += check_row(i, row)

            if row_count == 0:
                result.add_warning("CSV has no data rows (header only)")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {csv_path}")


def validate_resistance_csv(
    csv_path: Path,
    result: ValidationResult,
) -> None:
    """
    Resistance-specific CSV validation.

    Required columns: resistance_ohm
    Optional columns: notes
    Cable length is structural (it comes from the session folder), so it is
    NOT a column. Values are round-trip loop resistance (one end shorted)
    and must be positive.
    """

    def check_row(i: int, row: dict) -> int:
        r_val = row.get("resistance_ohm", "").strip()
        try:
            r = float(r_val)
            if r <= 0:
                result.add_error(f"Row {i}: resistance_ohm must be positive, got {r}")
                return 1
        except ValueError:
            result.add_error(f"Row {i}: resistance_ohm is not numeric: '{r_val}'")
            return 1
        return 0

    _validate_data_csv(
        csv_path,
        result,
        required_columns=["resistance_ohm"],
        check_row=check_row,
        forbid_length_column=True,
    )


def validate_serdes_session(
    session_dir: Path,
    result: ValidationResult,
) -> None:
    """
    SerDes-specific session validation.

    Checks that session_manifest.csv covers exactly the three lanes
    {fwd_3g, fwd_6g, rev_187m}, that every referenced eye + margin CSV exists,
    and that those files have the expected raw structure:
    - eye CSV: phase, vth, polarity, hits, errors (the deserializer EOM grid)
    - margin CSV: tx_amp_mv, code, rep, locked, errors, status
    """
    import csv as _csv

    from src.processing.serdes import EXPECTED_LANES

    manifest_path = session_dir / "session_manifest.csv"
    try:
        with open(manifest_path, newline="") as f:
            reader = _csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {manifest_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]
            for required_col in ["lane_id", "channel", "rate_gbps", "eye_csv", "margin_csv"]:
                if required_col not in headers:
                    result.add_error(f"Manifest missing required column: '{required_col}'")
            if not result.is_valid:
                return

            seen_lanes: list[str] = []
            for i, row in enumerate(reader, start=2):
                lane_id = row.get("lane_id", "").strip()
                rate_raw = row.get("rate_gbps", "").strip()
                try:
                    float(rate_raw)
                except ValueError:
                    result.add_error(f"Row {i}: rate_gbps is not numeric: '{rate_raw}'")

                if lane_id not in EXPECTED_LANES:
                    result.add_error(
                        f"Row {i}: unexpected lane '{lane_id}'; "
                        f"expected one of {sorted(EXPECTED_LANES)}"
                    )
                    continue
                seen_lanes.append(lane_id)

                for col in ["eye_csv", "margin_csv"]:
                    filename = row.get(col, "").strip()
                    if not filename:
                        result.add_error(f"Row {i}: {col} is empty")
                    elif not (session_dir / filename).exists():
                        result.add_error(f"Row {i}: referenced file not found: {filename}")

                # Repeated margin sweeps (optional column; absent => single run)
                # append as margin_<lane>_run<i>.csv; check each exists.
                iters_raw = (row.get("margin_iterations") or "").strip()
                if iters_raw:
                    try:
                        iters = int(iters_raw)
                    except ValueError:
                        result.add_error(
                            f"Row {i}: margin_iterations is not an integer: '{iters_raw}'"
                        )
                    else:
                        if iters < 1:
                            result.add_error(f"Row {i}: margin_iterations must be >= 1: {iters}")
                        for n in range(2, iters + 1):
                            run = f"margin_{lane_id}_run{n}.csv"
                            if not (session_dir / run).exists():
                                result.add_error(f"Row {i}: margin run file not found: {run}")

            for lane_id in sorted(EXPECTED_LANES - set(seen_lanes)):
                result.add_error(f"Manifest missing lane: '{lane_id}'")
            if len(seen_lanes) != len(set(seen_lanes)):
                result.add_error("Manifest contains duplicate lanes")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {manifest_path}")
        return

    if not result.is_valid:
        return

    # Structural checks on the referenced data files
    for eye_path in sorted(session_dir.glob("eye_*.csv")):
        validate_eye_csv(eye_path, result)
    for margin_path in sorted(session_dir.glob("margin_*.csv")):
        validate_margin_csv(margin_path, result)


def validate_eye_csv(
    csv_path: Path,
    result: ValidationResult,
) -> None:
    """
    Validate a raw eye-monitor grid CSV.

    Required columns: phase (0-127), vth (0-63), polarity (0/1), hits (>= 0),
    errors (integer; -1 flags a measurement timeout).
    """

    def check_row(i: int, row: dict) -> int:
        errors = 0
        for col, lo, hi in [("phase", 0, 127), ("vth", 0, 63), ("polarity", 0, 1)]:
            val = row.get(col, "").strip()
            try:
                n = int(float(val))
                if not lo <= n <= hi:
                    result.add_error(f"{csv_path.name} row {i}: {col}={n} out of range [{lo},{hi}]")
                    errors += 1
            except ValueError:
                result.add_error(f"{csv_path.name} row {i}: {col} is not numeric: '{val}'")
                errors += 1

        hits_val = row.get("hits", "").strip()
        try:
            if float(hits_val) < 0:
                result.add_error(f"{csv_path.name} row {i}: hits must be >= 0")
                errors += 1
        except ValueError:
            result.add_error(f"{csv_path.name} row {i}: hits is not numeric: '{hits_val}'")
            errors += 1

        err_val = row.get("errors", "").strip()
        try:
            if float(err_val) < -1:
                result.add_error(f"{csv_path.name} row {i}: errors must be >= -1")
                errors += 1
        except ValueError:
            result.add_error(f"{csv_path.name} row {i}: errors is not numeric: '{err_val}'")
            errors += 1
        return errors

    _validate_data_csv(
        csv_path,
        result,
        required_columns=["phase", "vth", "polarity", "hits", "errors"],
        check_row=check_row,
    )


def validate_margin_csv(
    csv_path: Path,
    result: ValidationResult,
) -> None:
    """
    Validate a raw link-margin sweep CSV.

    Required columns: tx_amp_mv, code, rep, locked, errors, status.
    Amplitudes must be positive; errors is an integer (>= -1; -1 = lock lost).
    """

    def check_row(i: int, row: dict) -> int:
        errors = 0
        amp_val = row.get("tx_amp_mv", "").strip()
        try:
            if float(amp_val) <= 0:
                result.add_error(f"{csv_path.name} row {i}: tx_amp_mv must be positive")
                errors += 1
        except ValueError:
            result.add_error(f"{csv_path.name} row {i}: tx_amp_mv is not numeric: '{amp_val}'")
            errors += 1

        err_val = row.get("errors", "").strip()
        try:
            if float(err_val) < -1:
                result.add_error(f"{csv_path.name} row {i}: errors must be >= -1, got {err_val}")
                errors += 1
        except ValueError:
            result.add_error(f"{csv_path.name} row {i}: errors is not numeric: '{err_val}'")
            errors += 1
        return errors

    _validate_data_csv(
        csv_path,
        result,
        required_columns=["tx_amp_mv", "code", "rep", "locked", "errors", "status"],
        check_row=check_row,
    )


def validate_vna_manifest_csv(
    csv_path: Path,
    result: ValidationResult,
    session_dir: Path | None = None,
) -> None:
    """
    VNA manifest CSV validation.

    Required columns: filename
    Optional columns: description, notes
    Cable length is structural (it comes from the session folder).
    Each filename must reference an existing .s2p file in raw/.
    """

    def check_row(i: int, row: dict) -> int:
        filename = row.get("filename", "").strip()
        if not filename:
            result.add_error(f"Row {i}: filename is empty")
            return 1
        if session_dir is not None:
            s2p_path = session_dir / "raw" / filename
            if not s2p_path.exists():
                result.add_error(f"Row {i}: referenced file not found: raw/{filename}")
                return 1
        return 0

    _validate_data_csv(
        csv_path,
        result,
        required_columns=["filename"],
        check_row=check_row,
        forbid_length_column=True,
    )


def validate_s2p_file(
    s2p_path: Path,
    result: ValidationResult,
) -> None:
    """
    Basic validation of a Touchstone .s2p file.

    Checks that the file exists, has an option line (#), and has data rows.
    """
    try:
        with open(s2p_path) as f:
            has_option_line = False
            has_data = False
            for line in f:
                line = line.strip()
                if not line or line.startswith("!"):
                    continue
                if line.startswith("#"):
                    has_option_line = True
                    continue
                has_data = True
                break

            if not has_option_line:
                result.add_warning(f"{s2p_path.name}: no option line (#) found")
            if not has_data:
                result.add_error(f"{s2p_path.name}: no data rows found")

    except FileNotFoundError:
        result.add_error(f"S2P file not found: {s2p_path}")
