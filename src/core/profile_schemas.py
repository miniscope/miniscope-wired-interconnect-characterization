from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CableProfile(BaseModel):
    """
    Static specification of a cable model, stored at profiles/<profile_id>.yaml.

    Profiles hold only properties that define what the cable part IS --
    never measured values and never anything length-dependent. Measured
    quantities (resistivity, attenuation, eye metrics) are derived by the
    analysis pipeline from measurement sessions.

    Profiles are created through the acquisition app, which renders a form
    from this schema so nobody hand-writes YAML.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
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
