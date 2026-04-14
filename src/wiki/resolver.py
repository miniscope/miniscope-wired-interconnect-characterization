"""Model metadata resolution with wiki-then-repo-fallback protocol."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.core.experiment_schemas import ExperimentRecord
from src.core.schemas import ExperimentDefinition, FieldType
from src.wiki.base import BaseWikiClient

logger = logging.getLogger(__name__)


@dataclass
class ResolvedModel:
    """A resolved model reference with provenance."""

    field_name: str
    model_id: str
    model_type: str
    source: str  # "repo" or "wiki"
    path: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "source": self.source,
            "path": self.path,
            "resolved": True,
        }


@dataclass
class UnresolvedModel:
    """A model reference that could not be resolved."""

    field_name: str
    model_id: str | None
    model_type: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_type": self.model_type,
            "resolved": False,
            "reason": self.reason,
        }


@dataclass
class ResolutionManifest:
    """Records how all model references in an experiment were resolved."""

    experiment_id: str
    resolved_at: str = ""
    models: dict[str, ResolvedModel | UnresolvedModel] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resolved_at:
            self.resolved_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "resolved_at": self.resolved_at,
            "models": {name: model.to_dict() for name, model in self.models.items()},
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(self.to_json())


class ModelResolver:
    """
    Resolves model references using wiki-then-repo-fallback protocol.

    Resolution order:
    1. Wiki client (if provided and model found)
    2. Repository fallback (models/<model_type>/<model_id>.yaml)
    3. Not found (returns None)
    """

    def __init__(
        self,
        models_dir: Path,
        wiki_client: BaseWikiClient | None = None,
    ) -> None:
        self._models_dir = models_dir
        self._wiki_client = wiki_client

    def resolve(
        self, field_name: str, model_type: str, model_id: str
    ) -> ResolvedModel | UnresolvedModel:
        """Resolve a single model reference."""
        # Try wiki first
        if self._wiki_client is not None:
            try:
                wiki_data = self._wiki_client.fetch_model(model_type, model_id)
                if wiki_data is not None:
                    logger.info("Resolved %s=%s from wiki", field_name, model_id)
                    return ResolvedModel(
                        field_name=field_name,
                        model_id=model_id,
                        model_type=model_type,
                        source="wiki",
                        data=wiki_data,
                    )
            except Exception as e:
                logger.warning("Wiki fetch failed for %s=%s: %s", field_name, model_id, e)

        # Try repo fallback
        model_path = self._models_dir / model_type / f"{model_id}.yaml"
        if model_path.exists():
            try:
                with open(model_path) as f:
                    data = yaml.safe_load(f)
                logger.info("Resolved %s=%s from repo: %s", field_name, model_id, model_path)
                return ResolvedModel(
                    field_name=field_name,
                    model_id=model_id,
                    model_type=model_type,
                    source="repo",
                    path=str(model_path),
                    data=data,
                )
            except Exception as e:
                logger.warning("Failed to load repo model %s: %s", model_path, e)

        # Not found
        logger.warning("Could not resolve %s=%s in %s", field_name, model_id, model_type)
        return UnresolvedModel(
            field_name=field_name,
            model_id=model_id,
            model_type=model_type,
            reason="not found in wiki or repo",
        )

    def resolve_experiment(
        self,
        experiment: ExperimentRecord,
        definition: ExperimentDefinition,
    ) -> ResolutionManifest:
        """Resolve all model_ref fields in an experiment."""
        manifest = ResolutionManifest(experiment_id=experiment.experiment_id)

        for field_spec in definition.fields:
            if field_spec.field_type != FieldType.MODEL_REF:
                continue
            if field_spec.model_ref_type is None:
                continue

            model_id = experiment.type_fields.get(field_spec.name)
            if model_id is None:
                if field_spec.required:
                    manifest.models[field_spec.name] = UnresolvedModel(
                        field_name=field_spec.name,
                        model_id=None,
                        model_type=field_spec.model_ref_type,
                        reason="required field not provided",
                    )
                else:
                    manifest.models[field_spec.name] = UnresolvedModel(
                        field_name=field_spec.name,
                        model_id=None,
                        model_type=field_spec.model_ref_type,
                        reason="not provided",
                    )
                continue

            manifest.models[field_spec.name] = self.resolve(
                field_spec.name, field_spec.model_ref_type, str(model_id)
            )

        return manifest
