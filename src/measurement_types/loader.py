from __future__ import annotations

from pathlib import Path

import yaml

from src.core.schemas import MeasurementDefinition


def load_definition(path: Path) -> MeasurementDefinition:
    """Load and validate a measurement type definition from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return MeasurementDefinition.model_validate(raw)
