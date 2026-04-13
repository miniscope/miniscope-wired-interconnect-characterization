from __future__ import annotations

from pathlib import Path

import yaml

from src.core.schemas import ExperimentDefinition


def load_definition(path: Path) -> ExperimentDefinition:
    """Load and validate an experiment type definition from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return ExperimentDefinition.model_validate(raw)
