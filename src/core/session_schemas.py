from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SESSION_ID_PATTERN = r"^\d{8}_\d{2,}$"


class SessionRecord(BaseModel):
    """
    Base schema for every session.yaml.

    A session is one execution of one measurement type on one
    (cable profile, length). It lives at:
        measurements/<profile_id>/<length>mm/<measurement_type>/<session_id>/

    The directory path is the source of truth for profile_id, cable_length_mm,
    measurement_type, and session_id; session.yaml echoes them so each session
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
        description="Cable profile this session measures; matches profiles/<id>.yaml",
        min_length=1,
    )
    cable_length_mm: float = Field(
        description="Length of the cable sample under test",
        gt=0,
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


def length_dir_name(cable_length_mm: float) -> str:
    """Canonical directory name for a cable length, e.g. 1000mm or 1524.5mm."""
    return f"{cable_length_mm:g}mm"


def parse_length_dir_name(name: str) -> float:
    """Parse a length directory name like '1000mm' back to millimeters."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)mm", name)
    if match is None:
        raise ValueError(f"Invalid length directory name: '{name}' (expected e.g. '1000mm')")
    return float(match.group(1))
