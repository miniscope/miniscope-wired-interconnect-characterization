from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FieldType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    LIST_STRING = "list[string]"
    LIST_FLOAT = "list[float]"
    ENUM = "enum"
    MODEL_REF = "model_ref"


class FieldSpec(BaseModel):
    """Specification for a single field in an experiment type."""

    model_config = ConfigDict(extra="forbid")

    name: str
    field_type: FieldType
    required: bool = True
    description: str = ""
    default: Any = None
    enum_values: list[str] | None = None
    model_ref_type: str | None = None

    @model_validator(mode="after")
    def enum_values_required_for_enum(self) -> FieldSpec:
        if self.field_type == FieldType.ENUM and not self.enum_values:
            raise ValueError("enum_values must be provided when field_type is 'enum'")
        return self


class FileSpec(BaseModel):
    """Specification for a required/optional data file in an experiment."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    required: bool = True
    filename_pattern: str
    file_format: str


class ProcessingStep(BaseModel):
    """Defines a processing step that applies to this experiment type."""

    model_config = ConfigDict(extra="forbid")

    name: str
    processor: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class AggregationSpec(BaseModel):
    """Defines how experiments of this type aggregate across the dataset."""

    model_config = ConfigDict(extra="forbid")

    name: str
    aggregator: str
    description: str = ""
    outputs: list[str] = Field(default_factory=list)


class ExperimentDefinition(BaseModel):
    """
    Top-level model for an experiment type definition.yaml.
    Lives at experiment_types/<type_name>/v<N>/definition.yaml
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    version: int
    description: str
    fields: list[FieldSpec]
    files: list[FileSpec] = Field(default_factory=list)
    processing_steps: list[ProcessingStep] = Field(default_factory=list)
    aggregation: list[AggregationSpec] = Field(default_factory=list)
