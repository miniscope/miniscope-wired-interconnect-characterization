"""VNA measurement page: guided setup, capture, attenuation preview."""

from __future__ import annotations

from nicegui import run, ui

from src.acquire.controllers.sessions import run_vna_capture, save_vna_session
from src.acquire.pages.components import header, png_source, protocol_panel, require_operator
from src.acquire.plots import render_attenuation
from src.acquire.state import STATE
from src.core.session_schemas import parse_condition_dir
from src.instruments.registry import use_hardware
from src.instruments.types import VnaSweepResult
from src.instruments.vna.real import list_vna_devices

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

    # Connection check (hardware mode only). The PicoVNA enumerates as an FTDI
    # USB device, not a COM port, so we ask the PicoVNA 5 SDK whether an
    # instrument is attached rather than listing serial ports. With none present
    # we warn and disable Capture instead of letting the sweep fail deep in the
    # driver. The simulator needs no instrument, so this is skipped in simulate
    # mode. This mirrors the SerDes page's serial-port check.
    hardware = use_hardware(STATE.simulate)
    vna_status = None

    async def refresh_vna() -> None:
        # Detecting the PicoVNA opens the instrument briefly, so run it off the
        # UI thread (like the SerDes "Check link"), and disable Capture while
        # the probe is in flight so it can't be clicked against a stale state.
        capture_button.disable()
        vna_status.text = "Checking for VNA..."
        vna_status.classes(replace="text-gray-600 text-sm")
        devices = await run.io_bound(list_vna_devices)
        if devices:
            vna_status.text = f"VNA detected: {devices[0].description}"
            vna_status.classes(replace="text-green-700 text-sm")
            capture_button.enable()
        else:
            vna_status.text = (
                "No VNA detected. Connect the PicoVNA (and install the PicoVNA 5 "
                "SDK), then click Refresh."
            )
            vna_status.classes(replace="text-red-600 text-sm")
            capture_button.disable()

    if hardware:
        with ui.row().classes("items-center gap-2"):
            ui.button("Refresh", icon="refresh", on_click=refresh_vna).props("outline")
            vna_status = ui.label("").classes("text-sm")

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

    # Kick off the initial detection now that the buttons exist (refresh_vna
    # toggles Capture). Deferred via a one-shot timer so the hardware probe
    # runs after the page renders instead of blocking it. Skipped in simulate
    # mode, where no instrument is needed.
    if hardware:
        capture_button.disable()
        ui.timer(0.1, refresh_vna, once=True)
