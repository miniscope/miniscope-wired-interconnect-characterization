# Miniscope Wired Interconnect Characterization

Standardized submission, validation, processing, and aggregation of cable and interconnect characterization experiments for Miniscopes.

## Quick Start

```bash
poetry install
poetry run pytest
```

## Repository Structure

- `experiment_types/` -- Versioned experiment type definitions (YAML)
- `experiments/` -- Submitted experiment data (one folder per experiment)
- `models/` -- Hardware model metadata (cables, connectors, commutators, etc.)
- `src/` -- Python processing and validation code
- `derived/` -- Generated outputs (normalized data, tables, figures, wiki payloads)
- `tests/` -- Test suite

## Contributing an Experiment

1. Create a folder under `experiments/` named `EXP_YYYY_MM_DD_description`
2. Add an `experiment.yaml` referencing the appropriate experiment type and version
3. Add required data files (CSV, raw files) as specified by the experiment type
4. Submit a pull request -- CI will validate and process your submission
