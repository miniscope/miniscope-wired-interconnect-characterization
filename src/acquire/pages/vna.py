"""VNA measurement page: guided setup, capture, attenuation preview."""

from __future__ import annotations

import tempfile
from pathlib import Path

from nicegui import run, ui

from src.acquire.controllers.sessions import run_vna_capture, save_vna_session
from src.acquire.pages.components import header, png_source, protocol_panel, require_operator
from src.acquire.plots import (
    render_attenuation,
    render_impedance,
    render_sparameters,
    summary_impedance,
)
from src.acquire.state import STATE
from src.core.session_schemas import parse_condition_dir
from src.instruments.registry import use_hardware
from src.instruments.types import VnaSweepResult
from src.instruments.vna.real import list_vna_devices, vna_capture_available

CALIBRATION_TYPES = ["SOLT", "TRL", "electronic_cal", "other"]


def _probe_vna() -> tuple[list, bool]:
    """Detect the PicoVNA and whether a SCPI capture server is available (off the UI thread)."""
    return list_vna_devices(), vna_capture_available()


def _impedance_readout_text(result: VnaSweepResult) -> str:
    """One-line characteristic-impedance summary (mid-band median of Re(Z₀))."""
    value = summary_impedance(result)
    if value is None:
        return "Characteristic impedance (Z₀): n/a"
    return f"Characteristic impedance (Z₀): ~{value:.1f} Ω (mid-band median)"


def _preview_images(result: VnaSweepResult, xscale: str) -> tuple[bytes, bytes, bytes]:
    """Render the three preview PNGs at the given frequency scale (off the UI thread)."""
    return (
        render_sparameters(result, xscale=xscale),
        render_attenuation(result, xscale=xscale),
        render_impedance(result, xscale=xscale),
    )


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
    # rather than listing serial ports. Capture additionally needs a PicoVNA 5
    # SCPI server, so we report three distinct states -- not connected /
    # connected but no server / ready -- and only enable Capture in the last.
    # The simulator needs no instrument, so this is skipped in simulate mode.
    # Mirrors the SerDes page's serial-port check.
    hardware = use_hardware(STATE.simulate)
    vna_status = None

    # result: the last sweep, re-rendered on the Log/Linear toggle; cal_file:
    # the local path of an uploaded .calx to apply, or None for the server's cal.
    shared: dict = {"result": None, "cal_file": None}

    async def refresh_vna() -> None:
        # The detection runs a hardware/OS probe, so do it off the UI thread
        # (like the SerDes "Check link") and disable Capture while it's in
        # flight so it can't be clicked against a stale state.
        capture_button.disable()
        vna_status.text = "Checking for VNA..."
        vna_status.classes(replace="text-gray-600 text-sm")
        devices, server_ok = await run.io_bound(_probe_vna)
        if not devices:
            vna_status.text = "No VNA detected. Connect the PicoVNA, then click Refresh."
            vna_status.classes(replace="text-red-600 text-sm")
            return
        device = devices[0]
        if not server_ok:
            vna_status.text = (
                f"{device.description} detected ({device.serial}), but no PicoVNA 5 SCPI "
                "server is available -- capture needs it. Start the PicoVNA 5 software, "
                "or install it so vnaserver.exe can be launched."
            )
            vna_status.classes(replace="text-amber-700 text-sm")
            return
        vna_status.text = f"VNA ready: {device.description} ({device.serial})"
        vna_status.classes(replace="text-green-700 text-sm")
        capture_button.enable()

    if hardware:
        # Optional .calx applied before the sweep (via SCPI MMEM:APPLY:CAL) so the
        # capture uses a known calibration instead of whatever the server has
        # loaded. The SCPI server reads the file from its own (local) disk, so we
        # save the uploaded bytes to a temp file and hand the driver that path.
        # No upload -> use the server's current calibration.
        ui.label(
            "Calibration (.calx) -- optional. Upload one to apply before the sweep; "
            "otherwise the server's current calibration is used."
        ).classes("text-sm text-gray-600")

        def _on_cal_upload(e) -> None:
            dest_dir = Path(tempfile.gettempdir()) / "miniscope_vna_cal"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / e.name
            dest.write_bytes(e.content.read())
            shared["cal_file"] = str(dest)
            cal_status.text = f"Will apply: {e.name}"
            cal_status.classes(replace="text-sm text-green-700")

        def _clear_cal() -> None:
            shared["cal_file"] = None
            cal_upload.reset()
            cal_status.text = "Using the server's current calibration."
            cal_status.classes(replace="text-sm text-gray-600")

        with ui.row().classes("items-center gap-2"):
            cal_upload = (
                ui.upload(on_upload=_on_cal_upload, auto_upload=True, max_files=1)
                .props("accept=.calx")
                .classes("max-w-xs")
            )
            ui.button("Use server cal", icon="clear", on_click=_clear_cal).props("flat dense")
        cal_status = ui.label("Using the server's current calibration.").classes(
            "text-sm text-gray-600"
        )

        with ui.row().classes("items-center gap-2"):
            ui.button("Refresh", icon="refresh", on_click=refresh_vna).props("outline")
            vna_status = ui.label("").classes("text-sm")

    status_label = ui.label("").classes("text-gray-700")

    # The PicoVNA sweep is a single blocking SCPI call with no sub-steps, so an
    # indeterminate (animated) bar -- shown only while sweeping -- signals
    # "in progress" honestly, without a meaningful completion fraction.
    sweep_progress = (
        ui.linear_progress(show_value=False).props("indeterminate").classes("w-full max-w-2xl")
    )
    sweep_progress.set_visibility(False)

    async def refresh_preview() -> None:
        # Re-render the stored sweep at the selected frequency scale. Called by
        # the Log/Linear toggle and after each capture; no-op before a capture.
        result = shared["result"]
        if result is None:
            return
        sparams_png, atten_png, imp_png = await run.io_bound(
            _preview_images, result, freq_scale.value or "log"
        )
        preview.clear()
        with preview:
            ui.image(png_source(sparams_png)).classes("w-full max-w-2xl")
            ui.image(png_source(atten_png)).classes("w-full max-w-2xl")
            ui.image(png_source(imp_png)).classes("w-full max-w-2xl")
            ui.label(_impedance_readout_text(result)).classes("text-sm text-gray-700")

    with ui.row().classes("items-center gap-2 mt-2"):
        ui.label("Frequency axis:").classes("text-sm text-gray-700")
        freq_scale = ui.toggle(
            {"log": "Log", "linear": "Linear"}, value="log", on_change=refresh_preview
        ).props("dense")
    preview = ui.column().classes("w-full")

    async def capture() -> None:
        status_label.text = "Sweeping..."
        capture_button.disable()
        sweep_progress.set_visibility(True)
        try:
            result: VnaSweepResult = await run.io_bound(
                run_vna_capture, sim_length_mm, None, STATE.simulate, shared["cal_file"]
            )
            shared["result"] = result
            await refresh_preview()
            status_label.text = (
                "Capture complete -- review the S-parameters, attenuation, and "
                "characteristic impedance, then save."
            )
            save_button.enable()
        except Exception as e:
            status_label.text = f"Capture failed: {e}"
            ui.notify(f"Capture failed: {e}", type="negative", multi_line=True)
        finally:
            sweep_progress.set_visibility(False)
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
