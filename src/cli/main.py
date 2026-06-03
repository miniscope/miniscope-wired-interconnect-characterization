"""
CLI entry point (`miniscope-char`).

Thin argparse wrapper over the pipeline, analysis, wiki, and acquisition
modules. Imports happen inside each command so that `--help` and the
lean (no-extras) install stay fast and functional -- e.g. `acquire` only
imports NiceGUI when actually launched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a single session."""
    from src.core.loading import load_session
    from src.core.session_validator import validate_session
    from src.measurement_types.registry import MeasurementTypeRegistry

    session_dir = Path(args.session_dir)
    repo_root = Path(args.repo_root)

    session = load_session(session_dir / "session.yaml")
    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    definition = registry.get(session.measurement_type, session.measurement_type_version)

    result = validate_session(
        session_dir,
        session,
        definition,
        models_dir=repo_root / "models",
        profiles_dir=repo_root / "profiles",
    )

    ref = "/".join(session_dir.resolve().parts[-4:])
    if result.warnings:
        for w in result.warnings:
            print(f"  WARNING: {w}")
    if result.errors:
        for e in result.errors:
            print(f"  ERROR: {e}")
        print(f"FAILED: {ref}")
        return 1

    print(f"VALID: {ref}")
    return 0


def cmd_validate_all(args: argparse.Namespace) -> int:
    """Validate every profile and session in the repository."""
    from src.core.loading import load_profile, load_session
    from src.core.session_validator import validate_session
    from src.measurement_types.registry import MeasurementTypeRegistry
    from src.pipeline import discover_sessions

    repo_root = Path(args.repo_root)
    failures = 0

    # Profiles
    profiles_dir = repo_root / "profiles"
    n_profiles = 0
    if profiles_dir.exists():
        for profile_path in sorted(profiles_dir.glob("*.yaml")):
            n_profiles += 1
            try:
                load_profile(profile_path)
                print(f"  [OK]   profile {profile_path.stem}")
            except Exception as e:
                print(f"  [FAIL] profile {profile_path.stem}: {e}")
                failures += 1

    # Sessions
    registry = MeasurementTypeRegistry(repo_root / "measurement_types")
    sessions = discover_sessions(repo_root / "measurements")
    for session_dir in sessions:
        ref = "/".join(session_dir.resolve().parts[-4:])
        try:
            session = load_session(session_dir / "session.yaml")
            definition = registry.get(session.measurement_type, session.measurement_type_version)
        except Exception as e:
            print(f"  [FAIL] {ref}: {e}")
            failures += 1
            continue

        result = validate_session(
            session_dir,
            session,
            definition,
            models_dir=repo_root / "models",
            profiles_dir=repo_root / "profiles",
        )
        if result.is_valid:
            print(f"  [OK]   {ref}")
        else:
            for e in result.errors:
                print(f"         ERROR: {e}")
            print(f"  [FAIL] {ref}")
            failures += 1

    print(f"\nValidated {n_profiles} profiles and {len(sessions)} sessions, {failures} failures")
    return 1 if failures else 0


def cmd_process(args: argparse.Namespace) -> int:
    """Process a single session."""
    from src.pipeline import process_session

    session_dir = Path(args.session_dir)
    repo_root = Path(args.repo_root)

    result = process_session(session_dir, repo_root)

    if not result.validation.is_valid:
        for e in result.validation.errors:
            print(f"  ERROR: {e}")
        print(f"VALIDATION FAILED: {result.session_ref}")
        return 1

    if result.error:
        print(f"PROCESSING FAILED: {result.error}")
        return 1

    print(f"PROCESSED: {result.session_ref}")
    for name, path in result.outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_process_all(args: argparse.Namespace) -> int:
    """Process all sessions."""
    from src.pipeline import process_all

    repo_root = Path(args.repo_root)
    results = process_all(repo_root / "measurements", repo_root, args.type)

    failures = 0
    for r in results:
        status = "OK" if r.validation.is_valid and not r.error else "FAIL"
        print(f"  [{status}] {r.session_ref}")
        if r.error:
            print(f"         {r.error}")
        if not r.validation.is_valid:
            failures += 1

    print(f"\nProcessed {len(results)} sessions, {failures} failures")
    return 1 if failures else 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    """Run aggregation for a measurement type."""
    from src.pipeline import aggregate_type

    repo_root = Path(args.repo_root)
    outputs = aggregate_type(args.type, repo_root)

    print(f"Aggregated {args.type}:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    """Consolidate per-profile metrics across sessions."""
    from src.analysis.consolidate import consolidate_profile, consolidate_profiles

    repo_root = Path(args.repo_root)
    if args.profile:
        outputs = consolidate_profile(repo_root, args.profile)
    else:
        outputs = consolidate_profiles(repo_root)

    print(f"Consolidated {len(outputs)} outputs:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_cross(args: argparse.Namespace) -> int:
    """Run cross-cutting analysis (resistivity, supply voltage, quality scores)."""
    from src.analysis.cross import run_cross_analysis

    repo_root = Path(args.repo_root)
    outputs = run_cross_analysis(repo_root)

    print(f"Cross-cutting analysis produced {len(outputs)} outputs:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_generate_payloads(args: argparse.Namespace) -> int:
    """Generate wiki payloads."""
    from src.wiki.payloads import generate_wiki_payloads

    repo_root = Path(args.repo_root)
    outputs = generate_wiki_payloads(repo_root)

    print(f"Generated {len(outputs)} wiki payloads:")
    for profile_id, path in outputs.items():
        print(f"  {profile_id}: {path}")
    return 0


def cmd_render_wiki(args: argparse.Namespace) -> int:
    """Render wiki pages + image manifest into derived/wiki/."""
    from src.wiki.render import render_wiki

    repo_root = Path(args.repo_root)
    outputs = render_wiki(repo_root)

    print(f"Rendered {len(outputs)} wiki outputs:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


def cmd_publish_wiki(args: argparse.Namespace) -> int:
    """Render and publish the wiki bundle (requires bot credentials in env)."""
    from src.wiki.publish import publish_wiki

    repo_root = Path(args.repo_root)
    try:
        bundle_dir = publish_wiki(repo_root)
    except Exception as e:
        print(f"PUBLISH FAILED: {e}")
        return 1

    print(f"Published wiki bundle from {bundle_dir}")
    return 0


def cmd_acquire(args: argparse.Namespace) -> int:
    """Launch the acquisition app (requires the `acquire` extra)."""
    try:
        from src.acquire.app import run_acquire
    except ImportError:
        print(
            "The acquisition app requires the 'acquire' dependency group.\n"
            "Install it with: poetry install --with acquire"
        )
        return 1

    simulate = True if args.simulate else None
    run_acquire(repo_root=Path(args.repo_root), host=args.host, port=args.port, simulate=simulate)
    return 0


def cmd_run_all(args: argparse.Namespace) -> int:
    """Run the full pipeline."""
    from src.pipeline import run_full_pipeline

    repo_root = Path(args.repo_root)
    summary = run_full_pipeline(repo_root)

    processed = summary["processed"]
    failures = sum(1 for p in processed if p.get("error") or not p.get("valid"))

    print(f"Processed {len(processed)} sessions ({failures} failures)")
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
    p_validate = subparsers.add_parser("validate", help="Validate a session")
    p_validate.add_argument("session_dir", help="Path to session directory")

    # validate-all
    subparsers.add_parser("validate-all", help="Validate every profile and session")

    # process
    p_process = subparsers.add_parser("process", help="Process a session")
    p_process.add_argument("session_dir", help="Path to session directory")

    # process-all
    p_process_all = subparsers.add_parser("process-all", help="Process all sessions")
    p_process_all.add_argument("--type", default=None, help="Filter by measurement type")

    # aggregate
    p_aggregate = subparsers.add_parser("aggregate", help="Aggregate a measurement type")
    p_aggregate.add_argument("type", help="Measurement type name")

    # consolidate
    p_consolidate = subparsers.add_parser(
        "consolidate", help="Consolidate per-profile metrics across sessions"
    )
    p_consolidate.add_argument("--profile", default=None, help="Limit to one profile id")

    # cross
    subparsers.add_parser(
        "cross", help="Run cross-cutting analysis (resistivity, supply voltage, quality)"
    )

    # generate-payloads
    subparsers.add_parser("generate-payloads", help="Generate wiki payloads")

    # render-wiki
    subparsers.add_parser("render-wiki", help="Render wiki pages into derived/wiki/")

    # publish-wiki
    subparsers.add_parser(
        "publish-wiki", help="Render and publish the wiki (needs bot credentials)"
    )

    # run-all
    p_run_all = subparsers.add_parser("run-all", help="Run the full pipeline")
    p_run_all.add_argument("--json", action="store_true", help="Print summary as JSON")

    # acquire
    p_acquire = subparsers.add_parser("acquire", help="Launch the acquisition app")
    p_acquire.add_argument("--host", default="127.0.0.1", help="Bind address")
    p_acquire.add_argument("--port", type=int, default=8080, help="Port")
    p_acquire.add_argument(
        "--simulate",
        action="store_true",
        help="Force simulated instruments (no hardware needed)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "validate": cmd_validate,
        "validate-all": cmd_validate_all,
        "process": cmd_process,
        "process-all": cmd_process_all,
        "aggregate": cmd_aggregate,
        "consolidate": cmd_consolidate,
        "cross": cmd_cross,
        "generate-payloads": cmd_generate_payloads,
        "render-wiki": cmd_render_wiki,
        "publish-wiki": cmd_publish_wiki,
        "run-all": cmd_run_all,
        "acquire": cmd_acquire,
    }

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    app()
