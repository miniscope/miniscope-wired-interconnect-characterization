from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from src.core.experiment_schemas import ExperimentRecord
from src.core.schemas import ExperimentDefinition, FieldType
from src.core.validation import TypeFieldValidator


@dataclass
class ValidationResult:
    """Collects errors and warnings from experiment validation."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_experiment(
    experiment_dir: Path,
    experiment: ExperimentRecord,
    definition: ExperimentDefinition,
    models_dir: Path | None = None,
) -> ValidationResult:
    """
    Validate an experiment folder against its type definition.

    Checks type_fields, required files, and model references.
    Returns a ValidationResult collecting all errors and warnings.
    """
    result = ValidationResult()

    _validate_type_fields(experiment, definition, result)
    _validate_required_files(experiment_dir, definition, result)

    if models_dir is not None:
        _validate_model_refs(experiment, definition, models_dir, result)

    return result


def _validate_type_fields(
    experiment: ExperimentRecord,
    definition: ExperimentDefinition,
    result: ValidationResult,
) -> None:
    """Delegate to TypeFieldValidator and collect errors."""
    validator = TypeFieldValidator(definition)
    errors = validator.validate(experiment.type_fields)
    for e in errors:
        result.add_error(e)


def _validate_required_files(
    experiment_dir: Path,
    definition: ExperimentDefinition,
    result: ValidationResult,
) -> None:
    """Check that every required FileSpec has a matching file."""
    for file_spec in definition.files:
        if not file_spec.required:
            continue
        matches = list(experiment_dir.glob(file_spec.filename_pattern))
        if not matches:
            result.add_error(
                f"Required file missing: '{file_spec.filename_pattern}' " f"({file_spec.name})"
            )


def _validate_model_refs(
    experiment: ExperimentRecord,
    definition: ExperimentDefinition,
    models_dir: Path,
    result: ValidationResult,
) -> None:
    """For each model_ref field with a value, check that a matching YAML exists."""
    for field_spec in definition.fields:
        if field_spec.field_type != FieldType.MODEL_REF:
            continue
        if field_spec.model_ref_type is None:
            continue

        value = experiment.type_fields.get(field_spec.name)
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

    Required columns: resistance_ohm, cable_length_mm
    Optional columns: notes
    All numeric values must be positive.
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
            if "cable_length_mm" not in headers:
                result.add_error("CSV missing required column: 'cable_length_mm'")

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

                l_val = row.get("cable_length_mm", "").strip()
                try:
                    length = float(l_val)
                    if length <= 0:
                        result.add_error(f"Row {i}: cable_length_mm must be positive, got {length}")
                        error_count += 1
                except ValueError:
                    result.add_error(f"Row {i}: cable_length_mm is not numeric: '{l_val}'")
                    error_count += 1

            if row_count == 0:
                result.add_warning("CSV has no data rows (header only)")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {csv_path}")


def validate_eye_manifest_csv(
    csv_path: Path,
    result: ValidationResult,
    experiment_dir: Path | None = None,
) -> None:
    """
    Eye diagram manifest CSV validation.

    Required columns: filename, cable_length_mm, data_rate_mbps
    Optional columns: signal_type, notes
    Each filename must reference an existing .npz file in raw/.
    """
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                result.add_error(f"CSV file is empty: {csv_path.name}")
                return

            headers = [h.strip() for h in reader.fieldnames]

            for required_col in ["filename", "cable_length_mm", "data_rate_mbps"]:
                if required_col not in headers:
                    result.add_error(f"CSV missing required column: '{required_col}'")

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
                elif experiment_dir is not None:
                    npz_path = experiment_dir / "raw" / filename
                    if not npz_path.exists():
                        result.add_error(f"Row {i}: referenced file not found: raw/{filename}")
                        error_count += 1

                l_val = row.get("cable_length_mm", "").strip()
                try:
                    length = float(l_val)
                    if length <= 0:
                        result.add_error(f"Row {i}: cable_length_mm must be positive, got {length}")
                        error_count += 1
                except ValueError:
                    result.add_error(f"Row {i}: cable_length_mm is not numeric: '{l_val}'")
                    error_count += 1

                dr_val = row.get("data_rate_mbps", "").strip()
                try:
                    dr = float(dr_val)
                    if dr <= 0:
                        result.add_error(f"Row {i}: data_rate_mbps must be positive, got {dr}")
                        error_count += 1
                except ValueError:
                    result.add_error(f"Row {i}: data_rate_mbps is not numeric: '{dr_val}'")
                    error_count += 1

            if row_count == 0:
                result.add_warning("CSV has no data rows (header only)")

    except FileNotFoundError:
        result.add_error(f"CSV file not found: {csv_path}")


def validate_npz_file(
    npz_path: Path,
    result: ValidationResult,
) -> None:
    """
    Validate a single .npz eye diagram file.

    Checks:
    - File loads as a valid .npz
    - Contains an 'eye' array
    - 'eye' array has 3 dimensions with last dimension == 2 (rising/falling phase)
    - 'eye' array has a numeric dtype
    """
    import numpy as np

    try:
        data = np.load(npz_path)
    except Exception as e:
        result.add_error(f"{npz_path.name}: failed to load .npz: {e}")
        return

    if "eye" not in data:
        result.add_error(f"{npz_path.name}: missing required 'eye' array")
        return

    eye = data["eye"]
    if eye.ndim != 3:
        result.add_error(
            f"{npz_path.name}: 'eye' array must be 3D (voltage, time, phase), "
            f"got {eye.ndim}D with shape {eye.shape}"
        )
        return

    if eye.shape[2] != 2:
        result.add_error(
            f"{npz_path.name}: 'eye' array phase dimension must be 2 "
            f"(rising/falling), got {eye.shape[2]}"
        )

    if not np.issubdtype(eye.dtype, np.number):
        result.add_error(f"{npz_path.name}: 'eye' array must be numeric, got dtype {eye.dtype}")
