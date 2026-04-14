from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.aggregation.base import BaseAggregator
from src.core.experiment_validator import (
    ValidationResult,
    validate_experiment,
    validate_eye_manifest_csv,
    validate_resistance_csv,
    validate_vna_manifest_csv,
)
from src.core.loading import load_experiment
from src.experiment_types.registry import ExperimentTypeRegistry
from src.processing.base import BaseProcessor
from src.wiki.resolver import ModelResolver

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of running the pipeline for one experiment."""

    experiment_id: str
    validation: ValidationResult
    outputs: dict[str, Path] = field(default_factory=dict)
    error: str | None = None


# CSV validators keyed by experiment type name.
# Each entry is (filename, validator_fn, needs_experiment_dir).
_CSV_VALIDATORS: dict[str, list[tuple[str, callable, bool]]] = {
    "resistance_characterization": [("measurements.csv", validate_resistance_csv, False)],
    "eye_diagram_characterization": [("manifest.csv", validate_eye_manifest_csv, True)],
    "vna_characterization": [("manifest.csv", validate_vna_manifest_csv, True)],
}


def _resolve_class(dotted_path: str) -> type:
    """Import a class from a dotted path like 'src.processing.resistance.NormalizeResistance'."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _resolve_processor(dotted_path: str, **kwargs) -> BaseProcessor:
    """Import and instantiate a processor."""
    cls = _resolve_class(dotted_path)
    return cls(**kwargs)


def _resolve_aggregator(dotted_path: str, **kwargs) -> BaseAggregator:
    """Import and instantiate an aggregator."""
    cls = _resolve_class(dotted_path)
    return cls(**kwargs)


def process_experiment(
    experiment_dir: Path,
    repo_root: Path | None = None,
) -> PipelineResult:
    """
    Full pipeline for a single experiment:
    1. Load experiment.yaml
    2. Resolve experiment type definition
    3. Validate
    4. Run processing steps
    """
    if repo_root is None:
        repo_root = experiment_dir.parent.parent

    try:
        experiment = load_experiment(experiment_dir / "experiment.yaml")
    except Exception as e:
        result = ValidationResult()
        result.add_error(f"Failed to load experiment.yaml: {e}")
        return PipelineResult(
            experiment_id=experiment_dir.name,
            validation=result,
            error=str(e),
        )

    registry = ExperimentTypeRegistry(repo_root / "experiment_types")
    try:
        definition = registry.get(experiment.experiment_type, experiment.experiment_type_version)
    except FileNotFoundError as e:
        result = ValidationResult()
        result.add_error(str(e))
        return PipelineResult(
            experiment_id=experiment.experiment_id,
            validation=result,
            error=str(e),
        )

    validation = validate_experiment(
        experiment_dir, experiment, definition, models_dir=repo_root / "models"
    )

    csv_validators = _CSV_VALIDATORS.get(experiment.experiment_type, [])
    for filename, validator_fn, needs_exp_dir in csv_validators:
        csv_path = experiment_dir / filename
        if csv_path.exists():
            if needs_exp_dir:
                validator_fn(csv_path, validation, experiment_dir=experiment_dir)
            else:
                validator_fn(csv_path, validation)

    if not validation.is_valid:
        return PipelineResult(
            experiment_id=experiment.experiment_id,
            validation=validation,
        )

    # Resolve model references and write provenance manifest
    resolver = ModelResolver(models_dir=repo_root / "models")
    manifest = resolver.resolve_experiment(experiment, definition)
    manifest_dir = repo_root / "derived" / "manifests" / experiment.experiment_id
    manifest.write(manifest_dir / "resolution_manifest.json")

    output_dir = repo_root / "derived" / "normalized" / experiment.experiment_id
    all_outputs: dict[str, Path] = {}

    for step in definition.processing_steps:
        try:
            processor = _resolve_processor(step.processor, models_dir=repo_root / "models")
            outputs = processor.process(experiment_dir, experiment, definition, output_dir)
            all_outputs.update(outputs)
        except Exception as e:
            logger.error("Processing step '%s' failed: %s", step.name, e)
            return PipelineResult(
                experiment_id=experiment.experiment_id,
                validation=validation,
                outputs=all_outputs,
                error=f"Processing step '{step.name}' failed: {e}",
            )

    return PipelineResult(
        experiment_id=experiment.experiment_id,
        validation=validation,
        outputs=all_outputs,
    )


def process_all(
    experiments_dir: Path,
    repo_root: Path | None = None,
    experiment_type: str | None = None,
) -> list[PipelineResult]:
    """Process all experiments, optionally filtered by type."""
    if repo_root is None:
        repo_root = experiments_dir.parent

    results: list[PipelineResult] = []
    for exp_dir in sorted(experiments_dir.iterdir()):
        if not exp_dir.is_dir():
            continue
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.exists():
            continue

        if experiment_type is not None:
            try:
                exp = load_experiment(yaml_path)
                if exp.experiment_type != experiment_type:
                    continue
            except Exception:
                continue

        result = process_experiment(exp_dir, repo_root)
        results.append(result)

    return results


def aggregate_type(
    experiment_type: str,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    """Run aggregation for all processed experiments of a given type."""
    if repo_root is None:
        repo_root = Path(".")

    registry = ExperimentTypeRegistry(repo_root / "experiment_types")
    definition = registry.get_latest(experiment_type)

    experiments_dir = repo_root / "experiments"
    experiment_dirs: list[Path] = []
    for exp_dir in sorted(experiments_dir.iterdir()):
        if not exp_dir.is_dir():
            continue
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.exists():
            continue
        try:
            exp = load_experiment(yaml_path)
            if exp.experiment_type == experiment_type:
                experiment_dirs.append(exp_dir)
        except Exception:
            continue

    all_outputs: dict[str, Path] = {}
    derived_dir = repo_root / "derived"

    for agg_spec in definition.aggregation:
        aggregator = _resolve_aggregator(agg_spec.aggregator, derived_dir=derived_dir)
        output_dir = derived_dir / "aggregated" / experiment_type
        outputs = aggregator.aggregate(experiment_dirs, definition, output_dir)
        all_outputs.update(outputs)

    return all_outputs
