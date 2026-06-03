# Architecture: How (and Why) This Platform Is Built

This document explains the design of the cable characterization platform
-- not just what each piece does, but why it is shaped that way. The
repository is deliberately a worked example of building standardized,
reproducible experiment pipelines for the lab; if you are building a
pipeline for a different experiment, the patterns here are the takeaway.

## The core idea: separate what never changes from what always does

Every experiment platform juggles four kinds of things that change at
different speeds:

| Thing | Changes | Lives in |
|---|---|---|
| What a cable IS (specs) | almost never | `profiles/` |
| How a measurement is DEFINED | rarely, versioned | `measurement_types/` |
| Measured raw DATA | grows forever, never edited | `measurements/` |
| Derived RESULTS | regenerated on every change | `derived/` |

The cardinal rule: **raw data is append-only and derived results are
disposable.** If we invent a better eye metric next year, we re-run the
pipeline over the same raw sessions and every table, plot, and wiki page
updates. Nothing measured is ever lost to an analysis decision.

## Data model

### Cable profiles (`profiles/<id>.yaml`)

Static specs only -- impedance from the datasheet, wire gauge, connector
types. **Never measured values.** Resistivity is something we measure, so
it lives downstream in `derived/`, where it can be recomputed. The schema
(`src/core/profile_schemas.py`) uses `extra="forbid"` so a measured value
cannot sneak into a profile even by accident.

### Sessions (`measurements/<profile>/<length>mm/<type>/<YYYYMMDD_NN>/`)

A **session** is one execution of one measurement type on one
(profile, length). The directory path *is* the identity: profile, length,
type, and id are read off the path, echoed inside `session.yaml` for
self-containment, and validation rejects any mismatch
(`src/core/session_validator.py:parse_session_path`). This makes the tree
browsable by humans ("what do we have for this cable at 2 m?" is an `ls`)
and unambiguous for code.

Repeated measures are the normal case, not an exception: run the same
measurement again and it lands as a sibling session. The consolidation
stage pools siblings into mean/std/n.

### Measurement type definitions (`measurement_types/<type>/v<N>/definition.yaml`)

Each type declares, as data rather than code:

- `fields`: type-specific metadata with types/enums/requirements
  (validated dynamically by `src/core/validation.py:TypeFieldValidator`)
- `files`: which data files a session must contain
- `processing_steps` / `aggregation`: dotted paths to the Python classes
  that handle this type

Two consequences worth copying:

1. **Versioning** -- definitions are frozen once data references them. A
   protocol change becomes `v2/`; old sessions keep validating against
   `v1`. History never breaks.
2. **Definition-driven everything** -- the validator, the pipeline, and
   even the acquisition app's profile form are rendered FROM the schema.
   There is exactly one source of truth, so the form, the docs, and the
   validation can't drift apart.

## The acquisition app (`src/acquire/`)

The app is **the only supported way to create data**. That is a social
contract enforced technically:

- The create-profile form is generated from the `CableProfile` schema
  (`controllers/profiles.py:profile_form_fields`) -- nobody hand-writes
  YAML, so nobody mis-remembers the format.
- Each measurement page embeds its written protocol
  (`docs/protocols/*.md`) -- the procedure ships with the tool that
  executes it.
- Session writers (`src/core/session_writer.py`) serialize driver results
  to the on-disk contracts and then **validate with exactly the CI rules,
  rolling back on failure**. The app physically cannot save a session
  that CI would reject.

The GUI itself is intentionally thin: pages call controllers; controllers
call drivers and writers. All logic is in plain functions tested without
a browser.

## Instruments (`src/instruments/`)

Every instrument hides behind an abstract driver with a **simulated
implementation**:

- `SerdesDriver` has four primitives (connect, link_status, capture_eye,
  sweep_margin); the channelxrate orchestration with progress events is
  written ONCE on the ABC (`run_full_sequence`), so the simulator and the
  real hardware behave identically to the app.
- `VnaDriver.sweep` returns complex S-parameters; `write_s2p` serializes
  them to standard Touchstone that the pipeline's parser reads back.
- The I2C transport is an injectable Protocol because the lab's adapter
  is not decided yet -- `serdes/real.py` and `vna/real.py` are documented
  placeholders awaiting the existing lab instrument scripts.

Why simulators? Three reasons: the app can be developed and demoed
anywhere; CI never needs hardware; and the complete path (driver ->
writer -> validation -> analysis) is exercised end-to-end in tests with
realistic data shapes.

## The pipeline (`src/pipeline.py` + `src/analysis/`)

Five deterministic stages, each idempotent and individually runnable:

1. **process** (`src/processing/`) -- one session in, normalized
   CSV/JSON out. Per-type processors compute the metrics: round-trip
   resistance/m, eye opening + link-margin floor, attenuation.
2. **aggregate** (`src/aggregation/`) -- all sessions of one type:
   comparison tables and plots.
3. **consolidate** (`src/analysis/consolidate.py`) -- per profile, pool
   repeated sessions into one row per condition with across-session
   variability. Downstream consumers never re-derive statistics.
4. **cross** (`src/analysis/cross.py`) -- the headline outputs that span
   types: the resistance-vs-length fit (slope = round-trip resistivity,
   intercept = connector resistance), supply-voltage requirements per
   miniscope (V_min + I*rho*L -- no factor of 2, the shorted-loop
   protocol already measures the round trip), and the 0-1 quality score.
5. **render/publish wiki** (`src/wiki/`) -- pure offline rendering of
   pages + an image manifest, then a thin mwclient publisher. Rendering
   and publishing are separate so pages are testable without a network.

The quality score (`src/analysis/quality_score.py`) deserves a note: the
*plumbing* is final but the *formula* is explicitly a placeholder. All
weights and the works/marginal/not-recommended thresholds live in
`config/analysis.yaml`, so tuning the score after real data exists is a
config edit, not a refactor.

## CI as the enforcement layer (`.github/workflows/ci.yml`)

- **Every PR**: lint, tests, `validate-all`, and a full analysis dry-run.
  A data PR that breaks validation cannot merge -- this is the backstop
  for anything that bypassed the app.
- **Every merge to main**: regenerate `derived/`, bot-commit it back
  (`[skip ci]` prevents loops), publish the wiki. Results in the repo are
  therefore always in sync with the data, and the wiki is always in sync
  with the repo.

## Testing strategy (`tests/`)

- `tests/fixtures/measurements*` is a miniature but complete data tree
  (valid AND deliberately-broken sessions), built by deterministic
  generator scripts (`generate_*_fixtures.py`).
- `tests/conftest.py:build_test_repo` assembles a throwaway repo from
  fixtures + the real `measurement_types/`, so integration tests exercise
  the same definitions production uses.
- Simulators stand in for hardware everywhere; the GUI smoke tests skip
  automatically when the optional `acquire` group isn't installed.

## Extending the platform (the 20-minute version)

To add a measurement type `foo`:

1. `measurement_types/foo/v1/definition.yaml` -- fields, files,
   processing/aggregation references.
2. `src/processing/foo.py` -- a `BaseProcessor` producing
   `foo_summary.json` (+ whatever normalized outputs).
3. A validator in `src/core/session_validator.py`, registered in
   `src/pipeline.py`.
4. `src/aggregation/foo.py` -- a `BaseAggregator`.
5. A consolidator entry in `src/analysis/consolidate.py`.
6. `docs/protocols/foo.md` + an acquisition page/controller.
7. Fixtures (`tests/fixtures/generate_foo_fixtures.py`) + tests mirroring
   the serdes ones.

Nothing else changes: discovery, validation wiring, CI, and wiki payloads
pick the new type up from the definition.

## Open decisions (tracked, not forgotten)

- Quality-score formula, weights, zone thresholds (`config/analysis.yaml`)
- Additional eye metrics (jitter, Q-factor) -- `src/processing/eye.py`
- Characteristic-impedance extraction method -- `src/processing/vna.py`
- Real instrument drivers -- `src/instruments/serdes/real.py`,
  `src/instruments/vna/real.py` (awaiting the lab's scripts)
- Miniscope power values are placeholders -- `models/miniscope_models/`
