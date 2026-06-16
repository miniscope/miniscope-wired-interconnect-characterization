"""Weight measurement page: protocol + manual entry of repeated weighings."""

from __future__ import annotations

from nicegui import ui

from src.acquire.controllers.sessions import record_weight_session
from src.acquire.pages.components import header, protocol_panel, require_operator
from src.acquire.state import STATE

METHODS = ["digital_balance", "mechanical_scale", "other"]


@ui.page("/measure/weight/{profile_id}/{condition}")
def weight_page(profile_id: str, condition: str) -> None:
    header(f"Weight -- {profile_id} @ {condition}")
    protocol_panel("weight")

    instrument = ui.input(label="Measurement instrument *").props("outlined").classes("w-96")
    method = ui.select(METHODS, value="digital_balance", label="Method").props("outlined dense")
    notes = ui.input(label="Session notes").props("outlined").classes("w-full")

    ui.label("Weighings (assembly and bare PCB+SMA fixture, grams)").classes(
        "text-lg font-semibold mt-4"
    )
    ui.label(
        "Net cable mass = assembly - fixture. Record both so the raw masses are kept."
    ).classes("text-gray-600 text-sm")
    rows_container = ui.column().classes("w-full gap-1")
    reading_inputs: list[tuple[object, object, object]] = []

    def add_row() -> None:
        with rows_container, ui.row().classes("items-center gap-2"):
            assembly = ui.number(label=f"Assembly {len(reading_inputs) + 1} (g)").props(
                "outlined dense"
            )
            fixture = ui.number(label="Fixture PCB+SMA (g)").props("outlined dense")
            note = ui.input(label="note").props("outlined dense")
            reading_inputs.append((assembly, fixture, note))

    for _ in range(3):  # protocol asks for at least 3 weighings
        add_row()
    ui.button("Add weighing", icon="add", on_click=add_row).props("flat dense")

    def save() -> None:
        if not require_operator():
            return
        if not instrument.value:
            ui.notify("Enter the measurement instrument", type="warning")
            return
        readings = [
            (assembly.value, fixture.value, note.value or "")
            for assembly, fixture, note in reading_inputs
            if assembly.value is not None and fixture.value is not None
        ]
        if not readings:
            ui.notify("Enter at least one weighing (assembly and fixture)", type="warning")
            return
        try:
            ref = record_weight_session(
                STATE.repo_root,
                profile_id,
                condition,
                readings,
                operator=STATE.operator,
                notes=notes.value or "",
                instrument=instrument.value,
                method=method.value,
            )
        except Exception as e:
            ui.notify(f"Save failed: {e}", type="negative", multi_line=True)
            return
        ui.notify(f"Saved session {ref.ref}", type="positive")
        ui.navigate.to(f"/profile/{profile_id}")

    ui.button("Save session", icon="save", on_click=save).classes("mt-4")
