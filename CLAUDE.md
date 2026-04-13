# CLAUDE.md - Project Conventions

## Project
Miniscope Wired Interconnect Characterization -- a data repository with
processing pipelines for electrical characterization of Miniscope cables,
connectors, and commutators.

## Architecture
- `experiment_types/` -- YAML definitions that define validation + processing contracts
- `experiments/` -- one folder per experiment submission (added via PR)
- `models/` -- hardware model metadata (cables, connectors, commutators, miniscopes, power profiles)
- `src/` -- Python package (schemas, loaders, processors, aggregators, CLI)
- `derived/` -- committed build outputs (normalized data, tables, figures, wiki payloads)
- `tests/` -- pytest test suite

## Conventions
- Python 3.10+ (use modern type hints: `X | None` not `Optional[X]`)
- Pydantic v2 models for all schema validation
- YAML for all data/config files (not JSON, not TOML)
- Test-first: write tests before or alongside implementation
- Poetry for dependency management
- Ruff for linting and formatting (line-length=100)

## Key Commands
- `poetry install` -- install dependencies
- `poetry run pytest` -- run tests
- `poetry run ruff check src/ tests/` -- lint
- `poetry run ruff format src/ tests/` -- format

## Experiment Submission
Each experiment is a folder under `experiments/` containing an `experiment.yaml`
and associated data files. The experiment.yaml references an experiment type
and version, which determines validation rules and processing steps.

## Schema Versioning
- Experiment type definitions are versioned: `experiment_types/<type>/v<N>/definition.yaml`
- The `schema_version` field in experiment.yaml tracks the base schema version
- Model metadata files use a `schema_version` field for their own versioning
