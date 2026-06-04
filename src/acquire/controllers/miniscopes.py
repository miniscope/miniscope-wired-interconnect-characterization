"""
Miniscope-model controllers: list existing models and create new ones.

Miniscope models carry the DAQ-folded electrical/link parameters (ADR
0001) that drive the supply-voltage and quality guidance. Like cable
profiles, the GUI form is rendered from `miniscope_form_fields()`, which
introspects the MiniscopeModel schema -- so the form can never drift from
the validated schema and nobody hand-writes model YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.acquire.controllers.profiles import FormField
from src.core.loading import load_model
from src.core.model_schemas import MiniscopeModel

# Fields the app fills automatically rather than asking the user.
_AUTO_FIELDS = {"schema_version"}


def miniscope_form_fields() -> list[FormField]:
    """Derive form inputs from the MiniscopeModel schema."""
    fields: list[FormField] = []
    for name, info in MiniscopeModel.model_fields.items():
        if name in _AUTO_FIELDS:
            continue
        annotation = str(info.annotation)
        if "list[str]" in annotation:
            python_type = "list[str]"
        elif "float" in annotation:
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


def miniscope_models_dir(repo_root: Path) -> Path:
    return repo_root / "models" / "miniscope_models"


def list_miniscopes(repo_root: Path) -> list[MiniscopeModel]:
    """Every miniscope model in the repo, sorted by model_id."""
    models_dir = miniscope_models_dir(repo_root)
    if not models_dir.exists():
        return []
    models = [
        load_model(path, model_type="miniscope_models")
        for path in sorted(models_dir.glob("*.yaml"))
    ]
    return sorted(models, key=lambda m: m.model_id)


def create_miniscope(repo_root: Path, values: dict[str, Any]) -> MiniscopeModel:
    """
    Validate form values against the schema and write
    models/miniscope_models/<model_id>.yaml.

    Raises pydantic.ValidationError on bad values and FileExistsError when
    the model_id is taken -- the GUI surfaces both inline.
    """
    raw = {"schema_version": "1.0", **{k: v for k, v in values.items() if v not in (None, "")}}
    model = MiniscopeModel.model_validate(raw)

    models_dir = miniscope_models_dir(repo_root)
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / f"{model.model_id}.yaml"
    if path.exists():
        raise FileExistsError(f"Miniscope model '{model.model_id}' already exists at {path}")

    with open(path, "w") as f:
        yaml.safe_dump(model.model_dump(exclude_none=True), f, sort_keys=False)
    return model
