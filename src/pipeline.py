from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.aggregation.base import BaseAggregator, SessionContext
from src.analysis.consolidate import consolidate_profiles
from src.core.loading import load_session
from src.core.session_validator import (
    ValidationResult,
    validate_resistance_csv,
    validate_serdes_session,
    validate_session,
    validate_vna_manifest_csv,
)
from src.measurement_types.registry import MeasurementTypeRegistry
from src.processing.base import BaseProcessor
from src.wiki.payloads import generate_wiki_payloads
from src.wiki.resolver import ModelResolver

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of running the pipeline for one session."""

    session_ref: str
    validation: ValidationResult
    outputs: dict[str, Path] = field(default_factory=dict)
    error: str | None = None


# CSV validators keyed by measurement type name.
# Each entry is (filename, validator_fn, needs_session_dir).
_CSV_VALIDATORS: dict[str, list[tuple[str, callable, bool]]] = {
    "resistance": [("resistance.csv", validate_resistance_csv, False)],
    "vna": [("manifest.csv", validate_vna_manifest_csv, True)],
}

# Whole-session validators (beyond simple per-CSV checks) keyed by type name.
_SESSION_VALIDATORS: dict[str, callable] = {
    "serdes": validate_serdes_session,
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


def session_rel_path(session_dir: Path, measurements_dir: Path) -> Path:
    """Relative path of a session inside measurements/: profile/length/type/session."""
    return session_dir.resolve().relative_to(measurements_dir.resolve())


def derived_session_dir(repo_root: Path, session_dir: Path) -> Path:
    """Where a session's derived outputs live: derived/sessions/<profile>/<len>/<type>/<id>."""
    rel = session_rel_path(session_dir, repo_root / "measurements")
    return repo_root / "derived" / "sessions" / rel


def discover_sessions(
    measurements_dir: Path,
    measurement_type: str | None = None,
) -> list[Path]:
    """
    Walk measurements/<profile>/<length>mm/<type>/<session>/ and return all
    session directories (those containing a session.yaml), optionally
    filtered by measurement type (the third path level).
    """
    sessions: list[Path] = []
    if not measurements_dir.exists():
        return sessions

    for yaml_path in sorted(measurements_dir.glob("*/*/*/*/session.yaml")):
        session_dir = yaml_path.parent
        type_name = session_dir.parent.name
        if measurement_type is not None and type_name != measurement_type:
            continue
        sessions.append(session_dir)

    return sessions


def process_session(
    session_dir: Path,
    repo_root: Path | None = None,
) -> PipelineResult:
    """
    Full pipeline for a single session:
    1. Load session.yaml
    2. Resolve measurement type definition
    3. Validate (including path<->yaml identity)
    4. Resolve model references (provenance manifest)
    5. Run processing steps
    """
    if repo_root is None:
        repo_root = session_dir.parents[4]

    ref = "/".join(session_dir.resolve().parts[-4:])

    try:
        session = load_session(session_dir / "session.yaml")
    except Exception as e:
        result = ValidationResult()
        result.add_error(f"Failed to load session.yaml: {e}")
        return PipelineResult(session_ref=ref, validation=result, error=str(e))

    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    try:
        definition = registry.get(session.measurement_type, session.measurement_type_version)
    except FileNotFoundError as e:
        result = ValidationResult()
        result.add_error(str(e))
        return PipelineResult(session_ref=ref, validation=result, error=str(e))

    validation = validate_session(
        session_dir,
        session,
        definition,
        models_dir=repo_root / "models",
        profiles_dir=repo_root / "profiles",
    )

    csv_validators = _CSV_VALIDATORS.get(session.measurement_type, [])
    for filename, validator_fn, needs_session_dir in csv_validators:
        csv_path = session_dir / filename
        if csv_path.exists():
            if needs_session_dir:
                validator_fn(csv_path, validation, session_dir=session_dir)
            else:
                validator_fn(csv_path, validation)

    session_validator = _SESSION_VALIDATORS.get(session.measurement_type)
    if session_validator is not None:
        session_validator(session_dir, validation)

    if not validation.is_valid:
        return PipelineResult(session_ref=ref, validation=validation)

    output_dir = derived_session_dir(repo_root, session_dir)

    # Resolve model references and write provenance manifest
    resolver = ModelResolver(models_dir=repo_root / "models")
    manifest = resolver.resolve_session(session, definition)
    manifest.write(output_dir / "resolution_manifest.json")

    all_outputs: dict[str, Path] = {}

    for step in definition.processing_steps:
        try:
            processor = _resolve_processor(step.processor, models_dir=repo_root / "models")
            outputs = processor.process(session_dir, session, definition, output_dir)
            all_outputs.update(outputs)
        except Exception as e:
            logger.error("Processing step '%s' failed: %s", step.name, e)
            return PipelineResult(
                session_ref=ref,
                validation=validation,
                outputs=all_outputs,
                error=f"Processing step '{step.name}' failed: {e}",
            )

    return PipelineResult(session_ref=ref, validation=validation, outputs=all_outputs)


def process_all(
    measurements_dir: Path,
    repo_root: Path | None = None,
    measurement_type: str | None = None,
) -> list[PipelineResult]:
    """Process all sessions, optionally filtered by measurement type."""
    if repo_root is None:
        repo_root = measurements_dir.parent

    results: list[PipelineResult] = []
    for session_dir in discover_sessions(measurements_dir, measurement_type):
        results.append(process_session(session_dir, repo_root))

    return results


def _collect_session_contexts(
    repo_root: Path,
    measurement_type: str,
) -> list[SessionContext]:
    """Build SessionContexts for every loadable session of a measurement type."""
    contexts: list[SessionContext] = []
    for session_dir in discover_sessions(repo_root / "measurements", measurement_type):
        try:
            record = load_session(session_dir / "session.yaml")
        except Exception as e:
            logger.warning("Skipping unloadable session %s: %s", session_dir, e)
            continue
        contexts.append(
            SessionContext(
                session_dir=session_dir,
                derived_dir=derived_session_dir(repo_root, session_dir),
                record=record,
            )
        )
    return contexts


def aggregate_type(
    measurement_type: str,
    repo_root: Path | None = None,
) -> dict[str, Path]:
    """Run aggregation for all processed sessions of a given measurement type."""
    if repo_root is None:
        repo_root = Path(".")

    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    definition = registry.get_latest(measurement_type)

    contexts = _collect_session_contexts(repo_root, measurement_type)

    all_outputs: dict[str, Path] = {}
    derived_dir = repo_root / "derived"

    for agg_spec in definition.aggregation:
        aggregator = _resolve_aggregator(agg_spec.aggregator, derived_dir=derived_dir)
        output_dir = derived_dir / "aggregated" / measurement_type
        outputs = aggregator.aggregate(contexts, definition, output_dir)
        all_outputs.update(outputs)

    return all_outputs


def run_full_pipeline(repo_root: Path | None = None) -> dict:
    """
    Run the complete pipeline: process all sessions, aggregate all types,
    consolidate per-profile metrics, generate wiki payloads.

    Returns a summary dict with processing results, aggregation outputs,
    consolidation outputs, and wiki payload paths.
    """
    if repo_root is None:
        repo_root = Path(".")

    summary: dict = {
        "processed": [],
        "aggregated": {},
        "consolidated": {},
        "wiki_payloads": {},
    }

    # Process all sessions
    measurements_dir = repo_root / "measurements"
    if measurements_dir.exists():
        results = process_all(measurements_dir, repo_root)
        for r in results:
            summary["processed"].append(
                {
                    "session_ref": r.session_ref,
                    "valid": r.validation.is_valid,
                    "error": r.error,
                    "outputs": {k: str(v) for k, v in r.outputs.items()},
                }
            )

    # Aggregate all measurement types
    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    for type_name, _version in registry.discover():
        try:
            outputs = aggregate_type(type_name, repo_root)
            summary["aggregated"][type_name] = {k: str(v) for k, v in outputs.items()}
        except Exception as e:
            logger.error("Aggregation failed for %s: %s", type_name, e)
            summary["aggregated"][type_name] = {"error": str(e)}

    # Consolidate per-profile metrics across sessions
    try:
        consolidated = consolidate_profiles(repo_root)
        summary["consolidated"] = {k: str(v) for k, v in consolidated.items()}
    except Exception as e:
        logger.error("Profile consolidation failed: %s", e)
        summary["consolidated"] = {"error": str(e)}

    # Generate wiki payloads
    try:
        payloads = generate_wiki_payloads(repo_root)
        summary["wiki_payloads"] = {k: str(v) for k, v in payloads.items()}
    except Exception as e:
        logger.error("Wiki payload generation failed: %s", e)
        summary["wiki_payloads"] = {"error": str(e)}

    return summary
