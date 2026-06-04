from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SESSION_ID_PATTERN = r"^\d{8}_\d{2,}$"

# Conditions a commutator can be measured under. The path's second segment
# is a condition: cables use length conditions ('500mm'), commutators use
# these named states. Rotation states (e.g. 'rotating_10rpm') get added
# here when the motorized-rotation work lands.
COMMUTATOR_CONDITIONS = {"static"}


class SessionRecord(BaseModel):
    """
    Base schema for every session.yaml.

    A session is one execution of one measurement type on one
    (profile, condition). It lives at:
        measurements/<profile_id>/<condition>/<measurement_type>/<session_id>/

    The condition is the DUT state being measured: for cables it is the
    sample length ('500mm', from cable_length_mm); for commutators it is a
    named state ('static'). The directory path is the source of truth for
    all four identity parts; session.yaml echoes them so each session
    folder is self-contained, and validation asserts they match.

    Type-specific fields live in `type_fields` and are validated dynamically
    against the MeasurementDefinition.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        description="Version of the base session schema format",
        pattern=r"^\d+\.\d+$",
    )
    session_id: str = Field(
        description="Session identifier, matches folder name (YYYYMMDD_NN)",
        pattern=SESSION_ID_PATTERN,
    )
    profile_id: str = Field(
        description="DUT profile this session measures; matches profiles/<id>.yaml",
        min_length=1,
    )
    cable_length_mm: float | None = Field(
        default=None,
        description="Length of the cable sample under test (None for non-cable DUTs)",
        gt=0,
    )
    condition: str = Field(
        default="",
        description="Condition directory name; derived from cable_length_mm for cables",
    )
    measurement_type: str = Field(
        description="Must match a measurement_types/ directory name",
    )
    measurement_type_version: int = Field(
        description="Version of the measurement type definition to validate against",
        ge=1,
    )
    date: date
    operator: str = Field(
        description="Name of the person who performed the measurement",
        min_length=1,
    )
    notes: str = ""
    type_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific fields validated against the measurement definition",
    )

    @model_validator(mode="after")
    def _sync_condition(self) -> SessionRecord:
        """condition <-> cable_length_mm consistency (derive for cables)."""
        if self.cable_length_mm is not None:
            derived = length_dir_name(self.cable_length_mm)
            if not self.condition:
                self.condition = derived
            elif self.condition != derived:
                raise ValueError(
                    f"condition '{self.condition}' does not match "
                    f"cable_length_mm {self.cable_length_mm} ('{derived}')"
                )
        elif not self.condition:
            raise ValueError("condition is required when cable_length_mm is not set")
        return self


def length_dir_name(cable_length_mm: float) -> str:
    """Canonical directory name for a cable length, e.g. 1000mm or 1524.5mm."""
    return f"{cable_length_mm:g}mm"


def parse_length_dir_name(name: str) -> float:
    """Parse a length directory name like '1000mm' back to millimeters."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)mm", name)
    if match is None:
        raise ValueError(f"Invalid length directory name: '{name}' (expected e.g. '1000mm')")
    return float(match.group(1))


def parse_condition_dir(name: str) -> float | None:
    """
    Parse a condition directory name.

    Returns the length in mm for length conditions ('500mm'), or None for
    named (non-length) conditions like 'static'. Raises on names that are
    neither a length nor a plausible condition identifier.
    """
    try:
        return parse_length_dir_name(name)
    except ValueError:
        pass
    if re.fullmatch(r"[a-z0-9_]+", name) is None:
        raise ValueError(
            f"Invalid condition directory name: '{name}' "
            "(expected a length like '1000mm' or a state like 'static')"
        )
    return None
