from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExperimentRecord(BaseModel):
    """
    Base schema for every experiment.yaml.

    The fixed fields are validated here. Type-specific fields live in
    `type_fields` and are validated dynamically against the ExperimentDefinition.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        description="Version of the base experiment schema format",
        pattern=r"^\d+\.\d+$",
    )
    experiment_id: str = Field(
        description="Unique identifier, typically matches folder name",
        min_length=1,
    )
    experiment_type: str = Field(
        description="Must match an experiment_types/ directory name",
    )
    experiment_type_version: int = Field(
        description="Version of the experiment type definition to validate against",
        ge=1,
    )
    date: date
    operator: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    type_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific fields validated against the experiment definition",
    )
