from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from src.core.schemas import FieldType, MeasurementDefinition
from src.core.session_schemas import SessionRecord, parse_length_dir_name
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
    cable_length_mm: float
    measurement_type: str
    session_id: str


def parse_session_path(session_dir: Path) -> SessionPathInfo:
    """
    Derive session identity from the directory layout:
        measurements/<profile_id>/<length>mm/<measurement_type>/<session_id>/
    """
    parts = session_dir.resolve().parts
    if len(parts) < 4:
        raise ValueError(f"Session path too shallow to parse: {session_dir}")
    profile_id, length_dir, measurement_type, session_id = parts[-4:]
    return SessionPathInfo(
        profile_id=profile_id,
        cable_length_mm=parse_length_dir_name(length_dir),
        measurement_type=measurement_type,
        session_id=session_id,
    )


def validate_session(
    session_dir: Path,
    session: SessionRecord,
    definition: MeasurementDefinition,
    models_dir: Path | None = None,
    profiles_dir: Path | None = None,
) -> ValidationResult:
    """
    Validate a session folder against its measurement type definition.

    Checks path<->yaml identity, type_fields, required files, the profile
    reference, and any model references.
    """
    result = ValidationResult()

    _validate_path_identity(session_dir, session, result)
    _validate_type_fields(session, definition, result)
    _validate_required_files(session_dir, definition, result)

    if profiles_dir is not None:
        profile_path = profiles_dir / f"{session.profile_id}.yaml"
        if not profile_path.exists():
            result.add_error(f"Cable profile '{session.profile_id}' not found at {profile_path}")

    if models_dir is not None:
        _validate_model_refs(session, definition, models_dir, result)

    return result


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


def _validate_model_refs(
    session: SessionRecord,
    definition: MeasurementDefinition,
    models_dir: Path,
    result: ValidationResult,
) -> None:
    """For each model_ref field with a value, check that a matching YAML exists."""
    for field_spec in definition.fields:
        if field_spec.field_type != FieldType.MODEL_REF:
            continue
        if field_spec.model_ref_type is None:
            continue

        value = session.type_fields.get(field_spec.name)
        if value is None:
            continue

        model_path = models_dir / field_spec.model_ref_type / f"{value}.yaml"
        if not model_path.exists():
            result.add_warning(
                f"Model reference '{field_spec.name}={value}' not found at {model_path}"
            )


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
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {csv_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]

            if "resistance_ohm" not in headers:
                result.add_error("CSV missing required column: 'resistance_ohm'")
            if "cable_length_mm" in headers:
                result.add_error(
                    "CSV must not contain 'cable_length_mm': length comes from "
                    "the session folder"
                )

            if not result.is_valid:
                return

            row_count = 0
            error_count = 0
            max_errors = 10

            for i, row in enumerate(reader, start=2):
                row_count += 1
                if error_count >= max_errors:
                    result.add_error(f"... and more errors (stopped after {max_errors})")
                    break

                r_val = row.get("resistance_ohm", "").strip()
                try:
                    r = float(r_val)
                    if r <= 0:
                        result.add_error(f"Row {i}: resistance_ohm must be positive, got {r}")
                        error_count += 1
                except ValueError:
                    result.add_error(f"Row {i}: resistance_ohm is not numeric: '{r_val}'")
                    error_count += 1

            if row_count == 0:
                result.add_warning("CSV has no data rows (header only)")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {csv_path}")


def validate_serdes_session(
    session_dir: Path,
    result: ValidationResult,
) -> None:
    """
    SerDes-specific session validation.

    Checks that session_manifest.csv covers exactly the
    {forward, back} x {3, 6 Gbps} combos, that every referenced eye NPZ and
    margin CSV exists, and that those files have the expected structure:
    - eye NPZ: error_counts (2D numeric), voltage_range_mv (2,), time_range_ps (2,)
    - margin CSV: tx_amplitude_mv, error_count columns with valid values
    """
    import csv as _csv

    from src.processing.serdes import EXPECTED_COMBOS

    manifest_path = session_dir / "session_manifest.csv"
    try:
        with open(manifest_path, newline="") as f:
            reader = _csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {manifest_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]
            for required_col in ["channel", "rate_gbps", "eye_npz", "margin_csv"]:
                if required_col not in headers:
                    result.add_error(f"Manifest missing required column: '{required_col}'")
            if not result.is_valid:
                return

            seen_combos: list[tuple[str, int]] = []
            for i, row in enumerate(reader, start=2):
                channel = row.get("channel", "").strip()
                rate_raw = row.get("rate_gbps", "").strip()
                try:
                    rate = int(float(rate_raw))
                except ValueError:
                    result.add_error(f"Row {i}: rate_gbps is not numeric: '{rate_raw}'")
                    continue

                if (channel, rate) not in EXPECTED_COMBOS:
                    result.add_error(
                        f"Row {i}: unexpected combo ({channel}, {rate} Gbps); "
                        f"expected channels forward/back at 3 or 6 Gbps"
                    )
                    continue
                seen_combos.append((channel, rate))

                for col in ["eye_npz", "margin_csv"]:
                    filename = row.get(col, "").strip()
                    if not filename:
                        result.add_error(f"Row {i}: {col} is empty")
                    elif not (session_dir / filename).exists():
                        result.add_error(f"Row {i}: referenced file not found: {filename}")

            missing = EXPECTED_COMBOS - set(seen_combos)
            for channel, rate in sorted(missing):
                result.add_error(f"Manifest missing combo: ({channel}, {rate} Gbps)")
            if len(seen_combos) != len(set(seen_combos)):
                result.add_error("Manifest contains duplicate channel/rate combos")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {manifest_path}")
        return

    if not result.is_valid:
        return

    # Structural checks on the referenced data files
    for npz_path in sorted(session_dir.glob("*.npz")):
        validate_serdes_npz(npz_path, result)
    for margin_path in sorted(session_dir.glob("margin_*.csv")):
        validate_margin_csv(margin_path, result)


def validate_serdes_npz(
    npz_path: Path,
    result: ValidationResult,
) -> None:
    """
    Validate a single SerDes eye-diagram .npz file.

    Required keys:
    - error_counts: 2D numeric array (voltage bins x time bins)
    - voltage_range_mv: shape (2,)
    - time_range_ps: shape (2,)
    """
    import numpy as np

    try:
        data = np.load(npz_path)
    except Exception as e:
        result.add_error(f"{npz_path.name}: failed to load .npz: {e}")
        return

    for key in ["error_counts", "voltage_range_mv", "time_range_ps"]:
        if key not in data:
            result.add_error(f"{npz_path.name}: missing required '{key}' array")
    if not result.is_valid:
        return

    counts = data["error_counts"]
    if counts.ndim != 2:
        result.add_error(
            f"{npz_path.name}: 'error_counts' must be 2D (voltage, time), "
            f"got {counts.ndim}D with shape {counts.shape}"
        )
    if not np.issubdtype(counts.dtype, np.number):
        result.add_error(
            f"{npz_path.name}: 'error_counts' must be numeric, got dtype {counts.dtype}"
        )

    for key in ["voltage_range_mv", "time_range_ps"]:
        if data[key].shape != (2,):
            result.add_error(
                f"{npz_path.name}: '{key}' must have shape (2,), got {data[key].shape}"
            )


def validate_margin_csv(
    csv_path: Path,
    result: ValidationResult,
) -> None:
    """
    Validate a link-margin sweep CSV.

    Required columns: tx_amplitude_mv, error_count.
    Amplitudes must be positive; error counts must be non-negative integers.
    """
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {csv_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]
            for required_col in ["tx_amplitude_mv", "error_count"]:
                if required_col not in headers:
                    result.add_error(f"{csv_path.name}: missing required column: '{required_col}'")
            if not result.is_valid:
                return

            row_count = 0
            error_count = 0
            max_errors = 10

            for i, row in enumerate(reader, start=2):
                row_count += 1
                if error_count >= max_errors:
                    result.add_error(f"... and more errors (stopped after {max_errors})")
                    break

                amp_val = row.get("tx_amplitude_mv", "").strip()
                try:
                    amp = float(amp_val)
                    if amp <= 0:
                        result.add_error(
                            f"{csv_path.name} row {i}: tx_amplitude_mv must be positive, got {amp}"
                        )
                        error_count += 1
                except ValueError:
                    result.add_error(
                        f"{csv_path.name} row {i}: tx_amplitude_mv is not numeric: '{amp_val}'"
                    )
                    error_count += 1

                err_val = row.get("error_count", "").strip()
                try:
                    err = float(err_val)
                    if err < 0:
                        result.add_error(
                            f"{csv_path.name} row {i}: error_count must be >= 0, got {err}"
                        )
                        error_count += 1
                except ValueError:
                    result.add_error(
                        f"{csv_path.name} row {i}: error_count is not numeric: '{err_val}'"
                    )
                    error_count += 1

            if row_count == 0:
                result.add_warning(f"{csv_path.name} has no data rows (header only)")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {csv_path}")


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
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {csv_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]

            if "filename" not in headers:
                result.add_error("CSV missing required column: 'filename'")
            if "cable_length_mm" in headers:
                result.add_error(
                    "CSV must not contain 'cable_length_mm': length comes from "
                    "the session folder"
                )

            if not result.is_valid:
                return

            row_count = 0
            error_count = 0
            max_errors = 10

            for i, row in enumerate(reader, start=2):
                row_count += 1
                if error_count >= max_errors:
                    result.add_error(f"... and more errors (stopped after {max_errors})")
                    break

                filename = row.get("filename", "").strip()
                if not filename:
                    result.add_error(f"Row {i}: filename is empty")
                    error_count += 1
                elif session_dir is not None:
                    s2p_path = session_dir / "raw" / filename
                    if not s2p_path.exists():
                        result.add_error(f"Row {i}: referenced file not found: raw/{filename}")
                        error_count += 1

            if row_count == 0:
                result.add_warning("CSV has no data rows (header only)")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {csv_path}")


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
