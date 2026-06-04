"""
Supply-voltage range per (miniscope, cable profile, length).

Miniscopes regulate onboard, so the relevant limits are the regulator
dropout (``min_operating_voltage_v``) and maximum input
(``max_operating_voltage_v``). The DC power loop runs in series through
the supply-side PoC choke, the cable (round-trip), and the receive-side
PoC choke:

    R_chain      = DCR_supply + R_cable_roundtrip + DCR_receive
    V_supply_min = Vmin + I_max * R_chain     # worst-case droop sets the floor
    V_supply_max = Vmax + I_min * R_chain     # least droop sets the ceiling

No extra factor of 2: the shorted-loop resistance protocol already
measures the full out-and-back path, so ``R_cable_roundtrip`` is the whole
cable contribution. "Choke DCR" per side is the total series resistance of
that side's PoC network (a datasheet value).

If ``V_supply_min > V_supply_max`` the (cable, length) is **infeasible**
for that Miniscope -- itself a key published result.

How the DAQ is powered is a USER-side choice (USB 5 V or an adjustable
input), so no supply voltage lives on the miniscope model. Reporting
instead uses a single reference supply (``reference_supply_v`` in
config/analysis.yaml, the USB 5 V rail): the binding test
``reference_supply_v - I_max * R_chain >= Vmin`` yields a maximum usable
length at that reference.

This whole module is SERDES-agnostic: it applies to every Miniscope
regardless of link rate. See ADR 0001 (build step 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.model_schemas import MiniscopeModel


def required_supply_v(
    min_operating_voltage_v: float,
    current_ma: float,
    series_resistance_ohm: float,
    length_m: float,
) -> float:
    """
    Supply voltage required at the far end of the tether to keep the
    regulator above dropout at the given current, for a per-metre series
    resistance over ``length_m``. Building block for the floor calculation.
    """
    drop_v = (current_ma / 1000.0) * series_resistance_ohm * length_m
    return min_operating_voltage_v + drop_v


def resistive_chain_ohm(
    roundtrip_resistivity_ohm_per_m: float,
    length_m: float,
    dcr_supply_ohm: float,
    dcr_receive_ohm: float,
) -> float:
    """Total series resistance of the DC power loop: both PoC chokes + cable."""
    return dcr_supply_ohm + roundtrip_resistivity_ohm_per_m * length_m + dcr_receive_ohm


@dataclass
class SupplyWindow:
    """Allowable supply-voltage window for one (miniscope, cable, length)."""

    r_chain_ohm: float
    v_supply_min: float  # floor (brownout): Vmin + I_max * R_chain
    v_supply_max: (
        float | None
    )  # ceiling (over-voltage): Vmax + I_min * R_chain; None if Vmax unknown
    feasible: bool  # window non-empty (True when there is no ceiling)
    reference_supply_v: float
    reference_supply_ok: bool  # reference supply sits within [v_supply_min, v_supply_max]


def supply_window(
    miniscope: MiniscopeModel,
    roundtrip_resistivity_ohm_per_m: float,
    length_m: float,
    reference_supply_v: float,
) -> SupplyWindow | None:
    """
    Compute the supply-voltage window for one length.

    Returns None if the miniscope lacks the floor essentials (regulator
    dropout and max current). The ceiling is computed only when the
    regulator's max input voltage is known; the idle current defaults to 0
    (the most conservative, i.e. lowest, ceiling) when unspecified.
    """
    if miniscope.min_operating_voltage_v is None or miniscope.max_current_ma is None:
        return None

    r_chain = resistive_chain_ohm(
        roundtrip_resistivity_ohm_per_m,
        length_m,
        miniscope.poc_dcr_supply_ohm,
        miniscope.poc_dcr_receive_ohm,
    )

    v_supply_min = required_supply_v(
        miniscope.min_operating_voltage_v, miniscope.max_current_ma, r_chain, 1.0
    )

    v_supply_max: float | None = None
    if miniscope.max_operating_voltage_v is not None:
        i_min_ma = miniscope.min_current_ma if miniscope.min_current_ma is not None else 0.0
        v_supply_max = miniscope.max_operating_voltage_v + (i_min_ma / 1000.0) * r_chain

    feasible = v_supply_max is None or v_supply_min <= v_supply_max
    reference_supply_ok = (
        feasible
        and v_supply_min <= reference_supply_v
        and (v_supply_max is None or reference_supply_v <= v_supply_max)
    )

    return SupplyWindow(
        r_chain_ohm=r_chain,
        v_supply_min=v_supply_min,
        v_supply_max=v_supply_max,
        feasible=feasible,
        reference_supply_v=reference_supply_v,
        reference_supply_ok=reference_supply_ok,
    )


def max_length_at_supply_v(
    miniscope: MiniscopeModel,
    roundtrip_resistivity_ohm_per_m: float,
    supply_v: float,
) -> float | None:
    """
    Maximum cable length (mm) at which the given supply still keeps the
    regulator above dropout under worst-case (max) current:

        supply_v - I_max * R_chain(L) >= Vmin

    Returns 0.0 if even a zero-length cable brownouts (the chokes alone, or
    a supply already below the regulator floor). Returns None if the
    resistivity is non-positive or the floor essentials are missing.
    """
    if (
        miniscope.min_operating_voltage_v is None
        or miniscope.max_current_ma is None
        or roundtrip_resistivity_ohm_per_m <= 0
    ):
        return None

    headroom_v = supply_v - miniscope.min_operating_voltage_v
    if headroom_v <= 0:
        return 0.0

    # Total series resistance the loop can tolerate at max current.
    r_chain_budget = headroom_v / (miniscope.max_current_ma / 1000.0)
    r_cable_budget = r_chain_budget - miniscope.poc_dcr_supply_ohm - miniscope.poc_dcr_receive_ohm
    if r_cable_budget <= 0:
        return 0.0

    length_m = r_cable_budget / roundtrip_resistivity_ohm_per_m
    return round(length_m * 1000.0, 1)


def supply_voltage_rows(
    miniscope: MiniscopeModel,
    profile_id: str,
    roundtrip_resistivity_ohm_per_m: float,
    lengths_mm: list[float],
    reference_supply_v: float,
) -> list[dict]:
    """
    Build supply-voltage-window table rows for one (miniscope, profile) pair.

    Returns one row per length with the allowable supply window, feasibility,
    and whether the reference (USB 5 V) supply lands inside it. Returns []
    if the miniscope lacks the floor essentials.
    """
    rows: list[dict] = []
    for length_mm in sorted(lengths_mm):
        window = supply_window(
            miniscope, roundtrip_resistivity_ohm_per_m, length_mm / 1000.0, reference_supply_v
        )
        if window is None:
            return []
        rows.append(
            {
                "miniscope_model": miniscope.model_id,
                "profile_id": profile_id,
                "cable_length_mm": length_mm,
                "roundtrip_resistivity_ohm_per_m": round(roundtrip_resistivity_ohm_per_m, 4),
                "r_chain_ohm": round(window.r_chain_ohm, 4),
                "v_supply_min": round(window.v_supply_min, 3),
                "v_supply_max": (
                    None if window.v_supply_max is None else round(window.v_supply_max, 3)
                ),
                "feasible": window.feasible,
                "reference_supply_v": reference_supply_v,
                "reference_supply_ok": window.reference_supply_ok,
            }
        )
    return rows


def max_length_row(
    miniscope: MiniscopeModel,
    profile_id: str,
    roundtrip_resistivity_ohm_per_m: float,
    reference_supply_v: float,
) -> dict | None:
    """
    Headline max-usable-length summary for one (miniscope, profile) pair at
    the reference supply. Returns None if it can't be computed.
    """
    max_len = max_length_at_supply_v(miniscope, roundtrip_resistivity_ohm_per_m, reference_supply_v)
    if max_len is None:
        return None
    return {
        "miniscope_model": miniscope.model_id,
        "profile_id": profile_id,
        "roundtrip_resistivity_ohm_per_m": round(roundtrip_resistivity_ohm_per_m, 4),
        "reference_supply_v": reference_supply_v,
        "voltage_limited_max_length_mm": max_len,
    }
