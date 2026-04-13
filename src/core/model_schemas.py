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
    """Metadata for a Miniscope model."""

    miniscope_version: str = ""
    sensor_type: str = ""
    led_type: str = ""
    weight_g: float | None = None
    power_consumption_mw: float | None = None


class PowerProfile(BaseModel):
    """Power profile for a Miniscope configuration."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    profile_id: str = Field(min_length=1)
    description: str = ""
    miniscope_model: str = ""
    voltage_v: float | None = None
    current_draw_ma: float | None = None
    power_mw: float | None = None
    signal_lines: list[str] = Field(default_factory=list)
