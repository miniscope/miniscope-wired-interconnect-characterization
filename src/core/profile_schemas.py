"""
Profile schemas: the measured DUTs of the platform.

A profile describes what a device-under-test IS (static, datasheet-style
specs) -- never measured values. Two DUT kinds exist (ADR 0001):

- CableProfile      -- coax tether cables, measured across lengths
- CommutatorProfile -- rotary joints, measured per condition (static now;
                       rotation states later)

Both live in profiles/<profile_id>.yaml, discriminated by `profile_type`
(absent means cable, so pre-existing cable profiles keep loading). Both
are created through the acquisition app, which renders forms from these
schemas so nobody hand-writes YAML.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CableProfile(BaseModel):
    """
    Static specification of a cable model, stored at profiles/<profile_id>.yaml.

    Profiles hold only properties that define what the cable part IS --
    never measured values and never anything length-dependent. Measured
    quantities (resistivity, attenuation, eye metrics) are derived by the
    analysis pipeline from measurement sessions.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    profile_type: Literal["cable"] = "cable"
    profile_id: str = Field(
        description="Unique identifier; must match the YAML filename stem",
        min_length=1,
        pattern=r"^[a-z0-9_]+$",
    )
    name: str = Field(
        description="Human-readable cable name",
        min_length=1,
    )
    manufacturer: str = ""
    part_number: str = ""
    mouser_part_number: str = Field(default="", description="Mouser order number, for reordering")
    digikey_part_number: str = Field(
        default="", description="Digi-Key order number, for reordering"
    )
    characteristic_impedance_ohm: float | None = Field(
        default=None,
        description="Nominal characteristic impedance from the datasheet",
        gt=0,
    )
    wire_gauge_awg: float | None = Field(default=None, gt=0)
    shield_type: str = ""
    connector_type_a: str = ""
    connector_type_b: str = ""
    cable_type: str = "coaxial"
    outer_diameter_mm: float | None = Field(default=None, gt=0)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


class CommutatorProfile(BaseModel):
    """
    Static specification of a commutator (rotary joint) under test.

    Commutators are characterized with the same measurement types as
    cables (resistance, serdes, vna) but have no length axis: sessions
    live under condition directories (currently just 'static'; rotation
    states like 'rotating_10rpm' slot in later). The published result is
    the commutator's STANDALONE impact -- added series resistance and
    added attenuation -- not a cable x commutator matrix.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    profile_type: Literal["commutator"] = "commutator"
    profile_id: str = Field(
        description="Unique identifier; must match the YAML filename stem",
        min_length=1,
        pattern=r"^[a-z0-9_]+$",
    )
    name: str = Field(
        description="Human-readable commutator name",
        min_length=1,
    )
    manufacturer: str = ""
    part_number: str = ""
    channel_count: int = Field(default=1, ge=1)
    max_rotation_rpm: float | None = Field(default=None, gt=0)
    commutator_type: str = Field(
        default="",
        description="Construction, e.g. 'passive slip ring' or 'active'",
    )
    connector_type_a: str = ""
    connector_type_b: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


Profile = CableProfile | CommutatorProfile
