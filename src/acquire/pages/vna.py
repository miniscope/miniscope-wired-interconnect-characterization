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
from src.instruments.vna.real import list_vna_devices, vna_sdk_available

CALIBRATION_TYPES = ["SOLT", "TRL", "electronic_cal", "other"]


def _probe_vna() -> tuple[list, bool]:
    """Detect the PicoVNA and whether its SDK is installed (run off the UI thread)."""
    return list_vna_devices(), vna_sdk_available()


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

    # Connection check (hardware mode only). The PicoVNA is an FTDI USB device,
    # not a COM port, so we enumerate it via the OS (by Pico's USB vendor ID)
    # rather than listing serial ports. Capture additionally needs the PicoVNA 5
    # SDK, so we report three distinct states -- not connected / connected but
    # no SDK / ready -- and only enable Capture in the last. The simulator needs
    # no instrument, so this is skipped in simulate mode. Mirrors the SerDes
    # page's serial-port check.
    hardware = use_hardware(STATE.simulate)
    vna_status = None

    async def refresh_vna() -> None:
        # The detection runs a hardware/OS probe, so do it off the UI thread
        # (like the SerDes "Check link") and disable Capture while it's in
        # flight so it can't be clicked against a stale state.
        capture_button.disable()
        vna_status.text = "Checking for VNA..."
        vna_status.classes(replace="text-gray-600 text-sm")
        devices, sdk_ok = await run.io_bound(_probe_vna)
        if not devices:
            vna_status.text = "No VNA detected. Connect the PicoVNA, then click Refresh."
            vna_status.classes(replace="text-red-600 text-sm")
            return
        device = devices[0]
        if not sdk_ok:
            vna_status.text = (
                f"{device.description} detected ({device.serial}), but the PicoVNA 5 "
                "SDK isn't installed -- capture needs it. See src/instruments/vna/real.py."
            )
            vna_status.classes(replace="text-amber-700 text-sm")
            return
        vna_status.text = f"VNA ready: {device.description} ({device.serial})"
        vna_status.classes(replace="text-green-700 text-sm")
        capture_button.enable()

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
