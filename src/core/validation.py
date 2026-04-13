from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.core.schemas import ExperimentDefinition, FieldSpec, FieldType


class TypeFieldValidator:
    """
    Validates the type_fields dict of an ExperimentRecord against
    the FieldSpec list from an ExperimentDefinition.
    """

    TYPE_MAP: dict[FieldType, type | tuple[type, ...]] = {
        FieldType.STRING: str,
        FieldType.INTEGER: int,
        FieldType.FLOAT: (int, float),
        FieldType.BOOLEAN: bool,
        FieldType.DATE: (str, date),
        FieldType.DATETIME: (str, datetime),
        FieldType.LIST_STRING: list,
        FieldType.LIST_FLOAT: list,
        FieldType.ENUM: str,
        FieldType.MODEL_REF: str,
    }

    def __init__(self, definition: ExperimentDefinition) -> None:
        self.definition = definition
        self._field_map: dict[str, FieldSpec] = {f.name: f for f in definition.fields}

    def validate(self, type_fields: dict[str, Any]) -> list[str]:
        """Return list of error messages. Empty list means valid."""
        errors: list[str] = []

        for field_spec in self.definition.fields:
            if field_spec.required and field_spec.name not in type_fields:
                if field_spec.default is None:
                    errors.append(f"Missing required field: {field_spec.name}")

        for key, value in type_fields.items():
            if key not in self._field_map:
                errors.append(f"Unknown field: {key}")
                continue

            spec = self._field_map[key]
            expected_types = self.TYPE_MAP.get(spec.field_type)
            if expected_types and not isinstance(value, expected_types):
                errors.append(
                    f"Field '{key}': expected {spec.field_type.value}, got {type(value).__name__}"
                )

            if spec.field_type == FieldType.ENUM and spec.enum_values:
                if value not in spec.enum_values:
                    errors.append(f"Field '{key}': value '{value}' not in {spec.enum_values}")

        return errors
