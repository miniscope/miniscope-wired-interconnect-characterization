"""VNA measurement page: guided setup, capture, attenuation preview."""

from __future__ import annotations

from nicegui import run, ui

from src.acquire.controllers.sessions import run_vna_capture, save_vna_session
from src.acquire.pages.components import header, png_source, protocol_panel, require_operator
from src.acquire.plots import render_attenuation
from src.acquire.state import STATE
from src.core.session_schemas import parse_condition_dir
from src.instruments.types import VnaSweepResult

CALIBRATION_TYPES = ["SOLT", "TRL", "electronic_cal", "other"]


@ui.page("/measure/vna/{profile_id}/{condition}")
def vna_page(profile_id: str, condition: str) -> None:
    header(f"VNA -- {profile_id} @ {condition}")
    # Simulated drivers model loss vs cable length; named conditions
    # (commutator states) use a short nominal length.
    sim_length_mm = parse_condition_dir(condition) or 100.0
    protocol_panel("vna")

    instrument = ui.input(label="VNA instrument *").props("outlined").classes("w-96")
    calibration = ui.select(CALIBRATION_TYPES, value="SOLT", label="Calibration type").props(
        "outlined dense"
    )
    notes = ui.input(label="Session notes").props("outlined").classes("w-full")

    status_label = ui.label("").classes("text-gray-700")
    preview = ui.column().classes("w-full")

    shared: dict = {"result": None}

    async def capture() -> None:
        status_label.text = "Sweeping..."
        capture_button.disable()
        try:
            result: VnaSweepResult = await run.io_bound(
                run_vna_capture, sim_length_mm, None, STATE.simulate
            )
            shared["result"] = result
            preview.clear()
            with preview:
                ui.image(png_source(render_attenuation(result))).classes("w-full max-w-2xl")
            status_label.text = "Capture complete -- review the attenuation curve, then save."
            save_button.enable()
        except Exception as e:
            status_label.text = f"Capture failed: {e}"
            ui.notify(f"Capture failed: {e}", type="negative", multi_line=True)
        finally:
            capture_button.enable()

    def save() -> None:
        if not require_operator():
            return
        if not instrument.value:
            ui.notify("Enter the VNA instrument", type="warning")
            return
        result = shared["result"]
        if result is None:
            ui.notify("Run a capture first", type="warning")
            return
        try:
            ref = save_vna_session(
                STATE.repo_root,
                profile_id,
                condition,
                result,
                operator=STATE.operator,
                notes=notes.value or "",
                vna_instrument=instrument.value,
                calibration_type=calibration.value,
            )
        except Exception as e:
            ui.notify(f"Save failed: {e}", type="negative", multi_line=True)
            return
        ui.notify(f"Saved session {ref.ref}", type="positive")
        ui.navigate.to(f"/profile/{profile_id}")

    with ui.row().classes("gap-2 mt-4"):
        capture_button = ui.button("Capture sweep", icon="play_arrow", on_click=capture)
        save_button = ui.button("Save session", icon="save", on_click=save)
        save_button.disable()
