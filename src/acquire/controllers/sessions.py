"""
Session controllers: run measurements and persist them.

These wrap the instrument drivers + session writers so GUI pages stay
logic-free. Everything here is synchronous; the GUI runs the long calls
on a background thread.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from src.core.session_schemas import length_dir_name, parse_condition_dir
from src.core.session_writer import (
    SessionMeta,
    SessionRef,
    delete_session,
    write_mass_session,
    write_resistance_session,
    write_serdes_session,
    write_vna_session,
)
from src.instruments.balance.driver import MassReading
from src.instruments.balance.driver import validate_reading as validate_mass_reading
from src.instruments.lcr.driver import ResistanceReading, validate_reading
from src.instruments.registry import get_serdes_driver, get_vna_driver
from src.instruments.serdes.driver import SerdesConfig
from src.instruments.types import ProgressEvent, SerdesResult, VnaSweepResult
from src.instruments.vna.driver import VnaConfig

__all__ = [
    "delete_session",
    "read_serdes_link_status",
    "record_resistance_session",
    "record_mass_session",
    "run_serdes_capture",
    "run_vna_capture",
    "save_serdes_session",
    "save_vna_session",
]


def _normalize_condition(condition: float | str) -> tuple[float | None, str]:
    """
    Accept either a cable length in mm (number) or a condition directory
    name ('500mm', 'static'); return (cable_length_mm | None, condition).
    """
    if isinstance(condition, int | float):
        return float(condition), length_dir_name(float(condition))
    length = parse_condition_dir(condition)
    return length, condition


def record_resistance_session(
    repo_root: Path,
    profile_id: str,
    condition: float | str,
    readings: list[tuple[float, str]],
    operator: str,
    notes: str,
    instrument: str,
    method: str = "lcr_shorted_loop",
    temperature_c: float | None = None,
) -> SessionRef:
    """Validate manual entries and write a resistance session."""
    parsed: list[ResistanceReading] = []
    for value, note in readings:
        validate_reading(value)
        parsed.append(ResistanceReading(resistance_ohm=float(value), note=note))

    type_fields: dict = {"measurement_instrument": instrument, "measurement_method": method}
    if temperature_c is not None:
        type_fields["temperature_c"] = temperature_c

    meta = SessionMeta(operator=operator, date=date.today(), notes=notes, type_fields=type_fields)
    length_mm, condition_dir = _normalize_condition(condition)
    return write_resistance_session(
        repo_root, profile_id, length_mm, parsed, meta, condition=condition_dir
    )


def record_mass_session(
    repo_root: Path,
    profile_id: str,
    condition: float | str,
    readings: list[tuple[float, float, str]],
    operator: str,
    notes: str,
    instrument: str,
    method: str = "digital_balance",
) -> SessionRef:
    """Validate manual entries and write a mass session.

    Each reading is (assembly_mass_g, fixture_mass_g, note): the whole
    cable assembly and the bare PCB+SMA fixture; the net cable mass is their
    difference.
    """
    parsed: list[MassReading] = []
    for assembly, fixture, note in readings:
        validate_mass_reading(assembly, fixture)
        parsed.append(
            MassReading(
                assembly_mass_g=float(assembly),
                fixture_mass_g=float(fixture),
                note=note,
            )
        )

    type_fields: dict = {"measurement_instrument": instrument, "measurement_method": method}

    meta = SessionMeta(operator=operator, date=date.today(), notes=notes, type_fields=type_fields)
    length_mm, condition_dir = _normalize_condition(condition)
    return write_mass_session(
        repo_root, profile_id, length_mm, parsed, meta, condition=condition_dir
    )


def read_serdes_link_status(
    cable_length_mm: float,
    simulate: bool | None = None,
    port: str | None = None,
) -> dict:
    """Connect, read the SerDes link status, and disconnect (blocking).

    Returns the driver's status dict (lock state, device part numbers, and
    forward-link rate for the real driver). `port` selects the Pico bridge
    serial port; ignored by the simulator.
    """
    kwargs: dict = {"cable_length_mm": cable_length_mm}
    if port:
        kwargs["port"] = port
    driver = get_serdes_driver(simulate=simulate, **kwargs)
    try:
        driver.connect()
        return driver.link_status()
    finally:
        driver.close()


def run_serdes_capture(
    cable_length_mm: float,
    progress: Callable[[ProgressEvent], None] | None = None,
    simulate: bool | None = None,
    port: str | None = None,
    config: SerdesConfig | None = None,
) -> SerdesResult:
    """Run the full SerDes characterization sequence (blocking).

    `port` selects the Pico bridge serial port for the real driver; it is
    ignored by the simulator. None lets the driver use its own default.
    `config` sets the capture resolution (eye grid, margin dwell); None uses
    the driver's full-resolution default.
    """
    kwargs: dict = {"cable_length_mm": cable_length_mm}
    if port:
        kwargs["port"] = port
    driver = get_serdes_driver(simulate=simulate, **kwargs)
    try:
        driver.connect()
        return driver.run_full_sequence(config=config, progress=progress)
    finally:
        driver.close()


def save_serdes_session(
    repo_root: Path,
    profile_id: str,
    condition: float | str,
    result: SerdesResult,
    operator: str,
    notes: str,
    serdes_device: str,
) -> SessionRef:
    meta = SessionMeta(
        operator=operator,
        date=date.today(),
        notes=notes,
        type_fields={"serdes_device": serdes_device},
    )
    length_mm, condition_dir = _normalize_condition(condition)
    return write_serdes_session(
        repo_root, profile_id, length_mm, result, meta, condition=condition_dir
    )


def run_vna_capture(
    cable_length_mm: float,
    config: VnaConfig | None = None,
    simulate: bool | None = None,
    calibration_file: str | None = None,
) -> VnaSweepResult:
    """Run one VNA sweep (blocking).

    `calibration_file` (hardware only) is a PicoVNA 5 .calx applied before the
    sweep, so the capture uses a known calibration rather than whatever the
    connected server happens to have loaded. None leaves the server's current
    calibration in place; the simulator ignores it.
    """
    kwargs: dict = {"cable_length_mm": cable_length_mm}
    if calibration_file:
        kwargs["calibration_file"] = calibration_file
    driver = get_vna_driver(simulate=simulate, **kwargs)
    driver.connect()
    try:
        if not driver.is_calibrated():
            from src.instruments import InstrumentError

            raise InstrumentError("VNA reports no valid calibration -- calibrate first")
        return driver.sweep(config or VnaConfig())
    finally:
        driver.close()


def save_vna_session(
    repo_root: Path,
    profile_id: str,
    condition: float | str,
    result: VnaSweepResult,
    operator: str,
    notes: str,
    vna_instrument: str,
    calibration_type: str = "SOLT",
) -> SessionRef:
    meta = SessionMeta(
        operator=operator,
        date=date.today(),
        notes=notes,
        type_fields={
            "vna_instrument": vna_instrument,
            "calibration_type": calibration_type,
            "port_impedance_ohm": result.ref_impedance_ohm,
        },
    )
    length_mm, condition_dir = _normalize_condition(condition)
    return write_vna_session(
        repo_root, profile_id, length_mm, result, meta, condition=condition_dir
    )
