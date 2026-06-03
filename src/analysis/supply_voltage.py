"""
Supply-voltage requirements per (miniscope, cable profile, length).

Users power a Miniscope through the coax tether, and thin coax drops a
meaningful voltage. Given a cable's measured round-trip resistivity and a
miniscope's power model, the supply voltage required at the DAQ side is:

    V_required = min_operating_voltage_v + I * (rho * L)

where rho is ROUND-TRIP resistivity (ohm/m). No extra factor of 2: the
shorted-loop resistance protocol already measures the full out-and-back
path (center conductor + shield return).

We report a range: baseline current (typical recording) to max current
(excitation LED at full power). Users should budget for the max.
"""

from __future__ import annotations

from src.core.model_schemas import MiniscopeModel


def required_supply_v(
    min_operating_voltage_v: float,
    current_ma: float,
    roundtrip_resistivity_ohm_per_m: float,
    length_m: float,
) -> float:
    """Supply voltage required at the far end of the tether."""
    drop_v = (current_ma / 1000.0) * roundtrip_resistivity_ohm_per_m * length_m
    return min_operating_voltage_v + drop_v


def supply_voltage_rows(
    miniscope: MiniscopeModel,
    profile_id: str,
    roundtrip_resistivity_ohm_per_m: float,
    lengths_mm: list[float],
) -> list[dict]:
    """
    Build supply-voltage table rows for one (miniscope, profile) pair.

    Returns one row per length with the baseline->max supply range.
    Returns [] if the miniscope is missing power fields.
    """
    if (
        miniscope.min_operating_voltage_v is None
        or miniscope.baseline_current_ma is None
        or miniscope.max_current_ma is None
    ):
        return []

    rows: list[dict] = []
    for length_mm in sorted(lengths_mm):
        length_m = length_mm / 1000.0
        rows.append(
            {
                "miniscope_model": miniscope.model_id,
                "profile_id": profile_id,
                "cable_length_mm": length_mm,
                "roundtrip_resistivity_ohm_per_m": round(roundtrip_resistivity_ohm_per_m, 4),
                "min_supply_v_baseline": round(
                    required_supply_v(
                        miniscope.min_operating_voltage_v,
                        miniscope.baseline_current_ma,
                        roundtrip_resistivity_ohm_per_m,
                        length_m,
                    ),
                    3,
                ),
                "min_supply_v_max_load": round(
                    required_supply_v(
                        miniscope.min_operating_voltage_v,
                        miniscope.max_current_ma,
                        roundtrip_resistivity_ohm_per_m,
                        length_m,
                    ),
                    3,
                ),
            }
        )
    return rows
