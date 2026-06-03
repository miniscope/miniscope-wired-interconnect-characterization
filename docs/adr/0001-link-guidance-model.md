# ADR 0001: Miniscope-centric link guidance; DAQ folded into the miniscope model

## Status

Accepted — 2026-06-03

## Context

The platform was built to characterize coax cables, but the real goal is to
give users actionable guidance for the path between a Miniscope and its DAQ.
Two facts from the lab's hardware reality drive the design:

- **A given Miniscope version only ever runs with one DAQ model.** An
  FPD-Link III Miniscope never connects to a GMSL2 DAQ and vice versa, so
  the DAQ (and therefore the SERDES family/rate) is implied by the Miniscope.
- **Miniscopes regulate onboard.** The relevant voltage limits are the
  onboard regulator's dropout (`Vmin`) and maximum input (`Vmax`), not raw
  rail tolerances.

Users think in terms of "I have a Miniscope V4 / MiniLFOV / MiniXL." They
want to pick a cable and length and know (a) whether the link will be clean
and (b) what supply voltage to use. They do not want to reason about DAQs,
SERDES rates, PoC filters, or connectors.

A Miniscope can fail two independent ways, and **both matter equally**:

- **Brownout** — the resistive chain drops too much voltage and the onboard
  regulator falls out of regulation.
- **Link errors** — signal integrity degrades until the SERDES link loses
  margin.

The power supply defaults to 5 V (USB) but can be switched to an adjustable
input. The DC power loop runs in series through: supply-side PoC choke →
cable (round-trip) → receive-side PoC choke → Miniscope regulator. PoC
filters are vendor-validated reference designs; their effect on the link is
already captured by the SerDes measurement (which runs through the real eval
boards), and their only first-order DC contribution is choke series
resistance (DCR), a datasheet value.

## Decision

1. **Fold the DAQ into the Miniscope model.** No separate user-facing DAQ
   entity. The Miniscope model carries: regulator `Vmin` (dropout) / `Vmax`,
   currents (min / normal / max), receive-side PoC DCR, supply-side PoC DCR,
   supply mode (5 V default / adjustable), and the SERDES rate. (An internal
   DAQ model may be introduced later only if multiple Miniscopes share a DAQ
   and the duplication becomes painful.)

2. **Publish two co-equal curves per (Miniscope × cable), over length:**
   - **Signal quality vs length** — works / marginal / not-recommended zones
     at the Miniscope's rate.
   - **Supply-voltage range vs length** — allowable supply window per length,
     with the 5 V default line marked.
   - **Max usable length = min(signal-limited, voltage-limited)**, with both
     curves shown so the binding constraint (and its failure mode) is visible.

3. **Voltage/power guidance is SERDES-agnostic** and applies to every
   Miniscope immediately. It uses the cable's measured round-trip resistance
   plus the Miniscope's currents, regulator limits, and PoC DCRs:

   ```
   R_chain      = DCR_supply + R_cable_roundtrip + DCR_receive
   V_supply_min = Vmin + I_max * R_chain        # worst-case droop sets the floor
   V_supply_max = Vmax + I_min * R_chain        # least droop sets the ceiling
   ```

   If `V_supply_min > V_supply_max`, the (cable, length) is **infeasible** for
   that Miniscope — itself a key published result. At the 5 V default, the
   binding test is `5 - I_max * R_chain >= Vmin`, which yields a max usable
   length at 5 V.

4. **Signal quality is per Miniscope rate, measured or projected:**
   - GMSL2 Miniscopes → measured eye/link-margin curve at their rate (3 or 6
     Gbps).
   - Miniscope V4 (FPD-Link III) → quality-vs-length **projected from the VNA
     attenuation curve** at the FPD-Link III frequency, **tagged "projected"**
     (no FPD-Link III eye hardware). Lower rate → less loss → generally longer
     allowable cable than 6 Gbps.

5. **Commutator stays a separate profile and page.** It is characterized with
   the same measurement types, but its page reports its *standalone* impact
   ("adds ~X dB and ~Y Ω → typically shortens max length by ~Z and raises
   required voltage by ~I·Y"). **No cable × commutator product matrix** for
   now.

6. **PoC filters and connectors are not characterized as DUTs.** PoC effects
   on the link are already captured by the SerDes measurement; the only DC
   contribution (choke DCR) is entered from datasheets on the Miniscope model.
   Connectors are second-order for nominal performance (the open question
   there is U.FL reliability/repeatability, not insertion loss).

### Entity model

- **Profiles (measured DUTs):** cable, commutator.
- **Models (datasheet specs, hand-entered):** Miniscope (DAQ folded in).
- **Skipped:** PoC and connector characterization.

The user-facing selection is only **Miniscope → cable → length**.

## Consequences

- Collapses a `DAQ × Miniscope × cable × length × rate` cross-product to
  **`Miniscope × cable × length`**. No SERDES compatibility gate or rate
  matrix is needed, because the Miniscope implies its DAQ and rate.
- The highest-value half of the deliverable (length + supply-voltage range)
  needs no eye data, no rate projection, and works for every Miniscope today.
- Signal quality and voltage range are treated as equally important; usable
  length is the more restrictive of the two, and both curves are always shown.
- The V4 quality curve is a VNA-based projection, not a measurement. This is
  acceptable interim guidance and becomes more credible once a VNA→eye/BER
  correlation exists from the GMSL2 data (the U24 "feature extraction" goal).
- Folding the DAQ into the Miniscope is a deliberate simplification that holds
  only while the Miniscope↔DAQ mapping stays 1:1. A future DAQ that pairs with
  several Miniscopes (or a Miniscope that supports several DAQs/rates) would
  require revisiting decision 1 and reintroducing a DAQ model.
- Commutator guidance is initially a standalone "delta" rather than a fully
  composed cable+commutator prediction. Full path composition / de-embedding
  remains deferred.

## Supersedes

Earlier discussion proposed a separate user-facing DAQ profile and a
`DAQ × Miniscope × rate` compatibility matrix. The 1:1 Miniscope↔DAQ mapping
and onboard regulation make that unnecessary; this ADR replaces it.
