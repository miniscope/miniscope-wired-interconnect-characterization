# Miniscope Wired Interconnect Characterization

Standardized submission, validation, processing, and aggregation of cable and interconnect characterization experiments for Miniscopes.

Contributors submit experiments as self-contained folders. The pipeline validates submissions against versioned experiment type definitions, processes them into normalized outputs, and aggregates results across experiments.

## Quick Start

```bash
poetry install
poetry run pytest
```

## Repository Structure

```
experiment_types/           # Versioned experiment type definitions (YAML)
  resistance_characterization/v1/
  vna_characterization/v1/
  eye_diagram_characterization/v1/

experiments/                # Submitted experiment data (one folder per experiment)
  EXP_YYYY_MM_DD_description/
    experiment.yaml
    measurements.csv | manifest.csv
    raw/                    # Raw data files (.npz, .s2p, etc.)

models/                     # Hardware model metadata (YAML)
  cable_models/
  connector_models/
  commutator_models/
  miniscope_models/
  power_profiles/

src/                        # Python package
  core/                     # Schemas, validation, loading
  experiment_types/         # Type registry and loader
  processing/               # Per-type processors
  aggregation/              # Cross-experiment aggregators
  pipeline.py               # Pipeline orchestration

derived/                    # Generated outputs (committed on main)
  normalized/               # Per-experiment normalized data
  aggregated/               # Cross-experiment tables and figures

tests/                      # Test suite (130 tests)
```

## Experiment Types

### Resistance Characterization

Round-trip DC resistance measurement of coaxial cable conductors. Each measurement is taken by looping the signal wire back through the ground shielding.

**Submission structure:**
```
EXP_YYYY_MM_DD_description/
  experiment.yaml
  measurements.csv          # Columns: resistance_ohm, cable_length_mm, [notes]
```

**Required `type_fields` in experiment.yaml:**
| Field | Type | Description |
|-------|------|-------------|
| `measurement_instrument` | string | e.g. "Keithley 2400" |
| `measurement_method` | enum | `four_wire` or `two_wire` |

**Optional `type_fields`:**
| Field | Type | Description |
|-------|------|-------------|
| `cable_model` | model_ref | Reference to cable type in `models/cable_models/` |
| `connector_model` | model_ref | Reference to connector in `models/connector_models/` |
| `temperature_c` | float | Ambient temperature (default: 25.0) |
| `mating_cycle` | integer | Mating cycle count at time of measurement |

**Derived outputs:** normalized CSV with `resistance_per_m`, summary JSON with statistics, cross-experiment boxplot.

### Eye Diagram Characterization

Signal integrity characterization via 2D histogram eye diagrams stored as `.npz` files. Each `.npz` contains an `eye` array of shape `(voltage_bins, time_bins, 2)` where the last dimension is phase (0=rising edge, 1=falling edge).

**Submission structure:**
```
EXP_YYYY_MM_DD_description/
  experiment.yaml
  manifest.csv              # Columns: filename, cable_length_mm, data_rate_mbps,
                            #          [signal_type], [notes]
  raw/
    eye_500mm_10mbps.npz
    eye_1000mm_10mbps.npz
```

**Required `type_fields` in experiment.yaml:**
| Field | Type | Description |
|-------|------|-------------|
| `oscilloscope` | string | Oscilloscope or BERT model |
| `signal_type` | enum | `SPI_CLK`, `SPI_MOSI`, `SPI_MISO`, `LVDS`, or `custom` |
| `data_rate_mbps` | float | Data rate in Mbps |

**Optional `type_fields`:**
| Field | Type | Description |
|-------|------|-------------|
| `cable_model` | model_ref | Reference to cable type |
| `signal_amplitude_mv` | float | Signal amplitude in mV |

**`.npz` file format:**
| Array | Shape | Description |
|-------|-------|-------------|
| `eye` (required) | `(V, T, 2)` | 2D histogram, axes: voltage, time, phase |
| `voltage_range` (optional) | `(2,)` | `[v_min, v_max]` in mV |
| `time_range` (optional) | `(2,)` | `[t_min, t_max]` in ps |

**Derived outputs:** per-file per-phase eye metrics (height, width, area as ratios and physical units), summary JSON, cross-experiment comparison table and bar chart.

### VNA Characterization

Vector Network Analyzer S-parameter characterization (planned for Milestone 4).

## Contributing an Experiment

1. Create a folder under `experiments/` named `EXP_YYYY_MM_DD_description`
2. Add an `experiment.yaml` with the required fields:
   ```yaml
   schema_version: "1.0"
   experiment_id: EXP_YYYY_MM_DD_description
   experiment_type: resistance_characterization  # or eye_diagram_characterization
   experiment_type_version: 1
   date: YYYY-MM-DD
   operator: Your Name
   description: Brief description of the experiment
   type_fields:
     # Type-specific fields (see experiment type docs above)
   ```
3. Add required data files as specified by the experiment type
4. Submit a pull request -- CI will validate and process your submission

## Hardware Models

Cable and connector models under `models/` describe cable *types* (not individual cable instances). Each model is a YAML file with electrical and mechanical specs:

```yaml
schema_version: "1.0"
model_id: coax_spi_sci_40awg
manufacturer: Custom / Lab-built
description: 40 AWG coaxial SPI/SCI cable assembly
conductor_count: 5
wire_gauge_awg: 40
shield_type: braided
impedance_ohm: 50.0
cable_type: coaxial
```

Individual cable properties (like length) are recorded per-measurement in the CSV data.

## Development

```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest

# Run tests with coverage
poetry run pytest --cov=src --cov-report=term-missing

# Lint
poetry run ruff check src/ tests/

# Format
poetry run ruff format src/ tests/
```

## Pipeline Usage

```python
from pathlib import Path
from src.pipeline import process_experiment, process_all, aggregate_type

# Process a single experiment
result = process_experiment(Path("experiments/EXP_2025_01_15_resistance_coax_40awg"))
print(result.validation.is_valid)  # True
print(result.outputs)              # {'normalized_resistance_csv': ..., 'resistance_summary_json': ...}

# Process all experiments of a type
results = process_all(Path("experiments"), experiment_type="resistance_characterization")

# Aggregate across experiments
outputs = aggregate_type("resistance_characterization")
```
