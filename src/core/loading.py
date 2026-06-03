"""
YAML -> validated Pydantic object loaders.

All disk reads of sessions, profiles, and hardware models funnel through
here so that nothing in the codebase ever works with an unvalidated dict:
if a function received a SessionRecord, the data behind it passed schema
validation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.core.model_schemas import (
    BaseHardwareModel,
    CableModel,
    CommutatorModel,
    ConnectorModel,
    MiniscopeModel,
)
from src.core.profile_schemas import CableProfile
from src.core.session_schemas import SessionRecord

_MODEL_TYPE_MAP: dict[str, type[BaseHardwareModel]] = {
    "cable_models": CableModel,
    "connector_models": ConnectorModel,
    "commutator_models": CommutatorModel,
    "miniscope_models": MiniscopeModel,
}


def load_session(path: Path) -> SessionRecord:
    """Load and validate a session.yaml file."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return SessionRecord.model_validate(raw)


def load_profile(path: Path) -> CableProfile:
    """
    Load and validate a cable profile YAML file.

    The profile_id must match the filename stem so profiles are
    discoverable by id without opening every file.
    """
    with open(path) as f:
        raw = yaml.safe_load(f)
    profile = CableProfile.model_validate(raw)
    if profile.profile_id != path.stem:
        raise ValueError(f"profile_id '{profile.profile_id}' does not match filename '{path.name}'")
    return profile


def list_profiles(profiles_dir: Path) -> list[CableProfile]:
    """Load every cable profile in profiles_dir, sorted by profile_id."""
    profiles: list[CableProfile] = []
    if not profiles_dir.exists():
        return profiles
    for path in sorted(profiles_dir.glob("*.yaml")):
        profiles.append(load_profile(path))
    return profiles


def load_model(path: Path, model_type: str | None = None) -> BaseHardwareModel:
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
