from __future__ import annotations

from pathlib import Path

import yaml

from src.core.experiment_schemas import ExperimentRecord
from src.core.model_schemas import (
    BaseHardwareModel,
    CableModel,
    CommutatorModel,
    ConnectorModel,
    MiniscopeModel,
    PowerProfile,
)

_MODEL_TYPE_MAP: dict[str, type[BaseHardwareModel] | type[PowerProfile]] = {
    "cable_models": CableModel,
    "connector_models": ConnectorModel,
    "commutator_models": CommutatorModel,
    "miniscope_models": MiniscopeModel,
    "power_profiles": PowerProfile,
}


def load_experiment(path: Path) -> ExperimentRecord:
    """Load and validate an experiment.yaml file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return ExperimentRecord.model_validate(raw)


def load_model(path: Path, model_type: str | None = None) -> BaseHardwareModel | PowerProfile:
    """
    Load a hardware model YAML file.

    If model_type is not specified, it is inferred from the parent directory name.
    """
    with open(path) as f:
        raw = yaml.safe_load(f)

    if model_type is None:
        model_type = path.parent.name

    model_class = _MODEL_TYPE_MAP.get(model_type)
    if model_class is None:
        raise ValueError(f"Unknown model type: {model_type}. Known: {list(_MODEL_TYPE_MAP)}")

    return model_class.model_validate(raw)
