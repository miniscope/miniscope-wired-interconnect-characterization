"""
Schemas for hardware model metadata (models/<type>/<id>.yaml).

These describe equipment the measurements reference -- miniscopes,
connectors, commutators -- as opposed to the cables under test, which
have their own stricter schema (src/core/profile_schemas.py). Hardware
models use extra="allow" so vendors' extra fields don't break loading;
cable profiles use extra="forbid" because they are OUR contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BaseHardwareModel(BaseModel):
    """Common fields for all hardware model metadata files."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    model_id: str = Field(min_length=1)
    manufacturer: str = ""
    part_number: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class CableModel(BaseHardwareModel):
    """Metadata for a cable model."""

    conductor_count: int = Field(ge=1)
    wire_gauge_awg: float | None = None
    length_mm: float | None = None
    shield_type: str = ""
    impedance_ohm: float | None = None
    connector_type_a: str = ""
    connector_type_b: str = ""
    cable_type: str = ""


class ConnectorModel(BaseHardwareModel):
    """Metadata for a connector model."""

    connector_family: str = ""
    pin_count: int = Field(ge=1, default=1)
    mating_cycles_rated: int | None = None
    contact_resistance_mohm: float | None = None


class CommutatorModel(BaseHardwareModel):
    """Metadata for a commutator/rotary joint model."""

    channel_count: int = Field(ge=1, default=1)
    max_rotation_rpm: float | None = None
    insertion_loss_db: float | None = None
    commutator_type: str = ""


class MiniscopeModel(BaseHardwareModel):
    """
    Metadata for a Miniscope model, with the DAQ folded in.

    A given Miniscope version only ever runs with one DAQ model, so the
    DAQ's relevant parameters (its supply mode and the supply-side PoC
    choke) live here rather than in a separate entity. See ADR 0001.

    These fields drive two co-equal published outputs over cable length:

    1. **Supply-voltage range.** Miniscopes regulate onboard, so the
       limits are the regulator dropout (``min_operating_voltage_v``) and
       maximum input (``max_operating_voltage_v``). The DC power loop runs
       in series through the supply-side PoC choke, the cable (round-trip),
       and the receive-side PoC choke:

           R_chain      = poc_dcr_supply_ohm + R_cable_roundtrip + poc_dcr_receive_ohm
           V_supply_min = min_operating_voltage_v + max_current_ma * R_chain
           V_supply_max = max_operating_voltage_v + min_current_ma * R_chain

       (worst-case droop sets the floor, least droop sets the ceiling). An
       empty window means the (cable, length) is infeasible. This side is
       SERDES-agnostic and applies to every Miniscope immediately.

    2. **Signal quality.** Per the Miniscope's SERDES family/rate: GMSL2
       scopes use a measured eye/link-margin curve at their rate; an
       FPD-Link III scope (e.g. Miniscope V4) has quality projected from
       the VNA attenuation curve. See ADR 0001 / build steps 2-3.

    PoC "choke DCR" per side is the total series resistance of that side's
    PoC network (sum the inductors if there is more than one); take it from
    the choke datasheet's max DCR. All resistance/voltage fields are
    optional so partially-specified models still load; the analysis simply
    skips outputs it lacks inputs for.
    """

    miniscope_version: str = ""
    sensor_type: str = ""
    led_type: str = ""
    weight_g: float | None = None

    # --- onboard regulator limits (the relevant voltage bounds) ---
    min_operating_voltage_v: float | None = Field(
        default=None,
        description="Regulator dropout: minimum voltage at the Miniscope side of the tether",
        gt=0,
    )
    max_operating_voltage_v: float | None = Field(
        default=None,
        description="Regulator maximum input voltage at the Miniscope side of the tether",
        gt=0,
    )

    # --- current draw (min -> normal -> max) ---
    min_current_ma: float | None = Field(
        default=None,
        description="Minimum (idle) current draw; sets the supply-voltage ceiling",
        gt=0,
    )
    baseline_current_ma: float | None = Field(
        default=None,
        description="Typical current draw during a standard recording",
        gt=0,
    )
    max_current_ma: float | None = Field(
        default=None,
        description="Worst-case current draw (e.g. excitation LED at full power)",
        gt=0,
    )

    # --- Power-over-Coax choke series resistance (datasheet max DCR) ---
    poc_dcr_supply_ohm: float = Field(
        default=0.0,
        description="Total series DCR of the supply-side (DAQ) PoC choke network",
        ge=0,
    )
    poc_dcr_receive_ohm: float = Field(
        default=0.0,
        description="Total series DCR of the receive-side (Miniscope) PoC choke network",
        ge=0,
    )

    # --- supply (DAQ folded in) ---
    supply_mode: Literal["fixed_5v", "adjustable"] = Field(
        default="fixed_5v",
        description="'fixed_5v' = USB-powered 5 V default; 'adjustable' = settable supply",
    )
    default_supply_v: float = Field(
        default=5.0,
        description="Default supply voltage (the 5 V USB rail unless adjusted)",
        gt=0,
    )

    # --- link / SERDES (implies the DAQ and rate) ---
    serdes_family: str = Field(
        default="",
        description="SERDES family, e.g. 'GMSL2' or 'FPD-Link III'",
    )
    serdes_rate_gbps: float | None = Field(
        default=None,
        description="Link rate in Gbps (e.g. 3 or 6 for GMSL2)",
        gt=0,
    )
