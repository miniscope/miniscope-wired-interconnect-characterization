"""Resistance measurement page: protocol + manual entry of repeated readings."""

from __future__ import annotations

from nicegui import ui

from src.acquire.controllers.sessions import record_resistance_session
from src.acquire.pages.components import header, protocol_panel, require_operator
from src.acquire.state import STATE


@ui.page("/measure/resistance/{profile_id}/{length_mm}")
def resistance_page(profile_id: str, length_mm: float) -> None:
    header(f"Resistance -- {profile_id} @ {length_mm:g} mm")
    protocol_panel("resistance")

    instrument = ui.input(label="Measurement instrument *").props("outlined").classes("w-96")
    temperature = ui.number(label="Ambient temperature (C)", value=25.0).props("outlined dense")
    notes = ui.input(label="Session notes").props("outlined").classes("w-full")

    ui.label("Readings (round-trip loop resistance, ohms)").classes("text-lg font-semibold mt-4")
    rows_container = ui.column().classes("w-full gap-1")
    reading_inputs: list[tuple[object, object]] = []

    def add_row() -> None:
        with rows_container, ui.row().classes("items-center gap-2"):
            value = ui.number(label=f"Reading {len(reading_inputs) + 1} (ohm)").props(
                "outlined dense"
            )
            note = ui.input(label="note").props("outlined dense")
            reading_inputs.append((value, note))

    for _ in range(3):  # protocol asks for at least 3 readings
        add_row()
    ui.button("Add reading", icon="add", on_click=add_row).props("flat dense")

    def save() -> None:
        if not require_operator():
            return
        if not instrument.value:
            ui.notify("Enter the measurement instrument", type="warning")
            return
        readings = [
            (value.value, note.value or "")
            for value, note in reading_inputs
            if value.value is not None
        ]
        if not readings:
            ui.notify("Enter at least one reading", type="warning")
            return
        try:
            ref = record_resistance_session(
                STATE.repo_root,
                profile_id,
                length_mm,
                readings,
                operator=STATE.operator,
                notes=notes.value or "",
                instrument=instrument.value,
                temperature_c=temperature.value,
            )
        except Exception as e:
            ui.notify(f"Save failed: {e}", type="negative", multi_line=True)
            return
        ui.notify(f"Saved session {ref.ref}", type="positive")
        ui.navigate.to(f"/profile/{profile_id}")

    ui.button("Save session", icon="save", on_click=save).classes("mt-4")
