from __future__ import annotations

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
    Metadata for a Miniscope model, including its power requirements.

    The power fields feed the supply-voltage analysis: given a cable's
    measured round-trip resistivity and a length, the pipeline computes
    the supply voltage required at the far end of the tether as
        V_required = min_operating_voltage_v + I * R_roundtrip
    where I is baseline_current_ma (typical use) or max_current_ma
    (excitation LED at full power).
    """

    miniscope_version: str = ""
    sensor_type: str = ""
    led_type: str = ""
    weight_g: float | None = None
    min_operating_voltage_v: float | None = Field(
        default=None,
        description="Minimum voltage required at the Miniscope side of the tether",
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
