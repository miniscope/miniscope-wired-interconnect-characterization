"""CLI entry point for miniscope characterization pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a single experiment."""
    from src.core.experiment_validator import validate_experiment
    from src.core.loading import load_experiment
    from src.experiment_types.registry import ExperimentTypeRegistry

    exp_dir = Path(args.experiment_dir)
    repo_root = Path(args.repo_root)

    experiment = load_experiment(exp_dir / "experiment.yaml")
    registry = ExperimentTypeRegistry(repo_root / "experiment_types")
    definition = registry.get(experiment.experiment_type, experiment.experiment_type_version)

    result = validate_experiment(exp_dir, experiment, definition, models_dir=repo_root / "models")

    if result.warnings:
        for w in result.warnings:
            print(f"  WARNING: {w}")
    if result.errors:
        for e in result.errors:
            print(f"  ERROR: {e}")
        print(f"FAILED: {experiment.experiment_id}")
        return 1

    print(f"VALID: {experiment.experiment_id}")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    """Process a single experiment."""
    from src.pipeline import process_experiment

    exp_dir = Path(args.experiment_dir)
    repo_root = Path(args.repo_root)

    result = process_experiment(exp_dir, repo_root)

    if not result.validation.is_valid:
        for e in result.validation.errors:
            print(f"  ERROR: {e}")
        print(f"VALIDATION FAILED: {result.experiment_id}")
        return 1

    if result.error:
        print(f"PROCESSING FAILED: {result.error}")
        return 1

    print(f"PROCESSED: {result.experiment_id}")
    for name, path in result.outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_process_all(args: argparse.Namespace) -> int:
    """Process all experiments."""
    from src.pipeline import process_all

    repo_root = Path(args.repo_root)
    results = process_all(repo_root / "experiments", repo_root, args.type)

    failures = 0
    for r in results:
        status = "OK" if r.validation.is_valid and not r.error else "FAIL"
        print(f"  [{status}] {r.experiment_id}")
        if r.error:
            print(f"         {r.error}")
        if not r.validation.is_valid:
            failures += 1

    print(f"\nProcessed {len(results)} experiments, {failures} failures")
    return 1 if failures else 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    """Run aggregation for an experiment type."""
    from src.pipeline import aggregate_type

    repo_root = Path(args.repo_root)
    outputs = aggregate_type(args.type, repo_root)

    print(f"Aggregated {args.type}:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_generate_payloads(args: argparse.Namespace) -> int:
    """Generate wiki payloads."""
    from src.wiki.payloads import generate_wiki_payloads

    repo_root = Path(args.repo_root)
    outputs = generate_wiki_payloads(repo_root)

    print(f"Generated {len(outputs)} wiki payloads:")
    for model_id, path in outputs.items():
        print(f"  {model_id}: {path}")
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    """Run the full pipeline."""
    from src.pipeline import run_full_pipeline

    repo_root = Path(args.repo_root)
    summary = run_full_pipeline(repo_root)

    processed = summary["processed"]
    failures = sum(1 for p in processed if p.get("error") or not p.get("valid"))

    print(f"Processed {len(processed)} experiments ({failures} failures)")
    print(f"Aggregated {len(summary['aggregated'])} types")
    print(f"Generated {len(summary['wiki_payloads'])} wiki payloads")

    if args.json:
        print(json.dumps(summary, indent=2))

    return 1 if failures else 0


def app() -> None:
    parser = argparse.ArgumentParser(
        prog="miniscope-char",
        description="Miniscope wired interconnect characterization pipeline",
    )
    parser.add_argument("--repo-root", default=".", help="Repository root directory (default: .)")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate an experiment")
    p_validate.add_argument("experiment_dir", help="Path to experiment directory")

    # process
    p_process = subparsers.add_parser("process", help="Process an experiment")
    p_process.add_argument("experiment_dir", help="Path to experiment directory")

    # process-all
    p_process_all = subparsers.add_parser("process-all", help="Process all experiments")
    p_process_all.add_argument("--type", default=None, help="Filter by experiment type")

    # aggregate
    p_aggregate = subparsers.add_parser("aggregate", help="Aggregate an experiment type")
    p_aggregate.add_argument("type", help="Experiment type name")

    # generate-payloads
    subparsers.add_parser("generate-payloads", help="Generate wiki payloads")

    # run-all
    p_run_all = subparsers.add_parser("run-all", help="Run the full pipeline")
    p_run_all.add_argument("--json", action="store_true", help="Print summary as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "validate": cmd_validate,
        "process": cmd_process,
        "process-all": cmd_process_all,
        "aggregate": cmd_aggregate,
        "generate-payloads": cmd_generate_payloads,
        "run-all": cmd_run_all,
    }

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    app()
