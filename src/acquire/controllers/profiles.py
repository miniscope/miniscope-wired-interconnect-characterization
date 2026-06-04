"""
Profile controllers: list existing DUT profiles and create new ones.

The create-profile forms in the GUI are rendered from
`profile_form_fields()` / `commutator_form_fields()`, which introspect the
profile schemas -- so the forms can never drift from the validated schemas
and nobody ever hand-writes profile YAML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from src.core.loading import list_profiles as _load_all_profiles
from src.core.profile_schemas import CableProfile, CommutatorProfile, Profile
from src.core.session_schemas import parse_condition_dir


@dataclass
class ProfileSummary:
    """A profile plus how much data exists for it."""

    profile: Profile
    n_lengths: int  # number of condition dirs (lengths for cables, states otherwise)
    n_sessions: int


@dataclass
class FormField:
    """One input in a schema-derived form (profiles, miniscope models)."""

    name: str
    label: str
    python_type: str  # "str" | "float" | "list[str]"
    required: bool
    default: Any = None
    description: str = ""


# Fields the app fills automatically rather than asking the user.
_AUTO_FIELDS = {"schema_version", "profile_type"}


def form_fields_for(
    schema: type[BaseModel], auto_fields: set[str] = _AUTO_FIELDS
) -> list[FormField]:
    """
    Derive form inputs from a Pydantic schema (profile or miniscope model).

    Fields named in ``auto_fields`` are filled by the app rather than asked
    of the user, so they are skipped here.
    """
    fields: list[FormField] = []
    for name, info in schema.model_fields.items():
        if name in auto_fields:
            continue
        annotation = str(info.annotation)
        if "list[str]" in annotation:
            python_type = "list[str]"
        elif "float" in annotation or "int" in annotation:
            python_type = "float"
        else:
            python_type = "str"
        fields.append(
            FormField(
                name=name,
                label=name.replace("_", " ").capitalize(),
                python_type=python_type,
                required=info.is_required(),
                default=info.default if info.default is not None else None,
                description=info.description or "",
            )
        )
    return fields


def profile_form_fields() -> list[FormField]:
    """Derive form inputs from the CableProfile schema."""
    return form_fields_for(CableProfile)


def commutator_form_fields() -> list[FormField]:
    """Derive form inputs from the CommutatorProfile schema."""
    return form_fields_for(CommutatorProfile)


def list_profile_summaries(repo_root: Path) -> list[ProfileSummary]:
    """Every profile plus its measurement counts (for the landing page)."""
    summaries: list[ProfileSummary] = []
    for profile in _load_all_profiles(repo_root / "profiles"):
        profile_dir = repo_root / "measurements" / profile.profile_id
        lengths = [d for d in profile_dir.iterdir() if d.is_dir()] if profile_dir.exists() else []
        n_sessions = len(list(profile_dir.glob("*/*/*/session.yaml"))) if lengths else 0
        summaries.append(
            ProfileSummary(profile=profile, n_lengths=len(lengths), n_sessions=n_sessions)
        )
    return summaries


def _create_dut_profile(
    repo_root: Path,
    values: dict[str, Any],
    schema: type[CableProfile] | type[CommutatorProfile],
) -> Profile:
    """
    Validate form values against the schema and write profiles/<id>.yaml.

    Raises pydantic.ValidationError on bad values and FileExistsError when
    the profile_id is taken -- the GUI surfaces both inline.
    """
    raw = {"schema_version": "1.0", **{k: v for k, v in values.items() if v not in (None, "")}}
    profile = schema.model_validate(raw)

    profiles_dir = repo_root / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    path = profiles_dir / f"{profile.profile_id}.yaml"
    if path.exists():
        raise FileExistsError(f"Profile '{profile.profile_id}' already exists at {path}")

    with open(path, "w") as f:
        yaml.safe_dump(profile.model_dump(exclude_none=True), f, sort_keys=False)
    return profile


def create_profile(repo_root: Path, values: dict[str, Any]) -> Profile:
    """Create a cable profile from form values."""
    return _create_dut_profile(repo_root, values, CableProfile)


def create_commutator_profile(repo_root: Path, values: dict[str, Any]) -> Profile:
    """Create a commutator profile from form values."""
    return _create_dut_profile(repo_root, values, CommutatorProfile)


@dataclass
class ConditionSummary:
    """One condition under a profile, with per-type session counts."""

    condition: str
    cable_length_mm: float | None  # None for named (non-length) conditions
    sessions_by_type: dict[str, int]


def list_conditions(repo_root: Path, profile_id: str) -> list[ConditionSummary]:
    """Conditions that exist for a profile, with session counts per type."""
    profile_dir = repo_root / "measurements" / profile_id
    summaries: list[ConditionSummary] = []
    if not profile_dir.exists():
        return summaries

    for condition_dir in sorted(profile_dir.iterdir()):
        if not condition_dir.is_dir():
            continue
        try:
            length_mm = parse_condition_dir(condition_dir.name)
        except ValueError:
            continue
        sessions_by_type: dict[str, int] = {}
        for type_dir in sorted(condition_dir.iterdir()):
            if type_dir.is_dir():
                count = len(list(type_dir.glob("*/session.yaml")))
                if count:
                    sessions_by_type[type_dir.name] = count
        summaries.append(
            ConditionSummary(
                condition=condition_dir.name,
                cable_length_mm=length_mm,
                sessions_by_type=sessions_by_type,
            )
        )
    return summaries
