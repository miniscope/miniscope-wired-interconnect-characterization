"""SerDes measurement page: automated capture with progress + live previews."""

from __future__ import annotations

import threading

from nicegui import run, ui

from src.acquire.controllers.sessions import (
    read_serdes_link_status,
    run_serdes_capture,
    save_serdes_session,
)
from src.acquire.pages.components import header, png_source, protocol_panel, require_operator
from src.acquire.plots import render_eye, render_margin
from src.acquire.state import STATE
from src.core.session_schemas import parse_condition_dir
from src.instruments.registry import use_hardware
from src.instruments.serdes.driver import SerdesConfig
from src.instruments.serdes.pico_bridge import list_serial_ports
from src.instruments.types import EyeDiagram, MarginSweep, ProgressEvent, SerdesResult

# Capture-resolution presets for the full sequence. Wall-clock is dominated by
# the eye grid (eye_bins -> ~bins^2 points at ~0.1 s each over the serial
# bridge) and the per-step margin dwell; eye_observations barely moves it, so
# we leave that at the driver default. Times are rough, for a real run.
RESOLUTION_PRESETS: dict[str, dict] = {
    "Full -- 64x64 eye (~25-30 min, full fidelity)": {"eye_bins": 64, "margin_dwell_s": 2.0},
    "Standard -- 32x32 eye (~8-10 min)": {"eye_bins": 32, "margin_dwell_s": 1.0},
    "Quick -- 16x16 eye (~2-3 min, preview)": {"eye_bins": 16, "margin_dwell_s": 0.5},
}
DEFAULT_RESOLUTION = next(iter(RESOLUTION_PRESETS))  # Full -- preserves saved-data fidelity


def _status_chip(ok: bool, ok_text: str, bad_text: str) -> None:
    ui.badge(ok_text if ok else bad_text).props("color=" + ("green" if ok else "red"))


def render_link_status(container, status: dict) -> None:
    """Render the SerDes link status into a persistent, readable panel.

    Understands the real driver's rich shape (per-device part number + lock
    flags and the forward-link rate) and falls back to a flat key/value dump
    for the simulator.
    """
    container.clear()
    ser = status.get("ser")
    des = status.get("des")
    with container, ui.card().classes("w-full"):
        if isinstance(ser, dict) and isinstance(des, dict):
            clean = bool(
                ser.get("locked")
                and des.get("locked")
                and not ser.get("error")
                and not des.get("error")
            )
            with ui.row().classes("items-center gap-2"):
                ui.icon("link" if clean else "link_off").classes(
                    "text-2xl " + ("text-green-600" if clean else "text-red-600")
                )
                ui.label("Link locked & clean" if clean else "Link not clean").classes(
                    "text-lg font-bold"
                )
                if status.get("demo"):
                    ui.badge("DEMO").props("color=orange")
            ui.label(f"Forward link rate: {status.get('forward_rate', 'unknown')}").classes(
                "text-sm"
            )
            ui.label("Reverse link rate: 187.5 Mbps (fixed)").classes("text-sm text-gray-500")
            for role, dev in (("Serializer", ser), ("Deserializer", des)):
                with ui.row().classes("items-center gap-4"):
                    ui.label(f"{role}: {dev.get('part', '?')}").classes("font-medium w-64")
                    dev_id = dev.get("device_id")
                    ui.label(f"ID 0x{dev_id:02X}" if isinstance(dev_id, int) else "ID ?").classes(
                        "text-sm text-gray-600 w-20"
                    )
                    _status_chip(bool(dev.get("locked")), "locked", "unlocked")
                    _status_chip(not dev.get("error"), "no errors", "errors")
                    _status_chip(bool(dev.get("cmu")), "CMU locked", "CMU unlocked")
        else:
            for key, value in status.items():
                ui.label(f"{key}: {value}").classes("text-sm")


@ui.page("/measure/serdes/{profile_id}/{condition}")
def serdes_page(profile_id: str, condition: str) -> None:
    header(f"SerDes -- {profile_id} @ {condition}")
    # Simulated drivers model loss vs cable length; named conditions
    # (commutator states) use a short nominal length.
    sim_length_mm = parse_condition_dir(condition) or 100.0
    protocol_panel("serdes")

    # Real captures talk to the Pico bridge over a serial port whose name is
    # platform-specific (COMx on Windows, /dev/tty* on Linux), so we can't
    # hard-code it. In hardware mode the operator picks from the detected
    # ports; with none present we warn and disable the capture buttons rather
    # than letting a capture fail deep in the driver. The simulator needs no
    # port, so this whole section is skipped in simulate mode.
    hardware = use_hardware(STATE.simulate)
    port_select = None
    port_warning = None

    def refresh_ports() -> None:
        ports = list_serial_ports()
        options = {p.device: f"{p.device} -- {p.description}" for p in ports}
        port_select.set_options(options)
        if ports:
            if port_select.value not in options:
                port_select.set_value(ports[0].device)
            port_warning.text = ""
            check_button.enable()
            go_button.enable()
        else:
            port_select.set_value(None)
            port_warning.text = (
                "No serial ports detected. Connect the Pico bridge, then click Refresh."
            )
            check_button.disable()
            go_button.disable()

    if hardware:
        with ui.row().classes("items-center gap-2 w-full"):
            port_select = (
                ui.select({}, label="Pico serial port *").props("outlined").classes("w-96")
            )
            ui.button("Refresh", icon="refresh", on_click=refresh_ports).props("outline")
        port_warning = ui.label("").classes("text-red-600 text-sm")

    device = ui.input(label="SerDes device *").props("outlined").classes("w-96")
    notes = ui.input(label="Session notes").props("outlined").classes("w-full")
    resolution = (
        ui.select(list(RESOLUTION_PRESETS), value=DEFAULT_RESOLUTION, label="Capture resolution")
        .props("outlined")
        .classes("w-96")
    )

    status_label = ui.label("").classes("text-gray-700")
    progress_bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
    previews = ui.grid(columns=4).classes("w-full gap-2")

    # Shared between the worker thread and the UI timer
    shared: dict = {"events": [], "result": None, "running": False, "lock": threading.Lock()}

    def selected_port() -> str | None:
        """The chosen serial port, or None in simulate mode (driver default)."""
        return port_select.value if hardware else None

    async def check_link() -> None:
        if hardware and not port_select.value:
            ui.notify("Select a serial port first", type="warning")
            return
        check_button.disable()
        link_panel.clear()
        with link_panel:
            ui.label("Checking link...").classes("text-gray-600")
        try:
            status = await run.io_bound(
                read_serdes_link_status, sim_length_mm, STATE.simulate, selected_port()
            )
        except Exception as e:
            link_panel.clear()
            with link_panel:
                ui.label(f"Link check failed: {e}").classes("text-red-600")
            ui.notify(f"Link check failed: {e}", type="negative", multi_line=True)
            return
        finally:
            check_button.enable()
        render_link_status(link_panel, status)

    def on_progress(event: ProgressEvent) -> None:
        # Called on the worker thread; the UI timer drains the queue.
        with shared["lock"]:
            shared["events"].append(event)

    def drain_events() -> None:
        with shared["lock"]:
            events: list[ProgressEvent] = shared["events"][:]
            shared["events"].clear()
        for event in events:
            progress_bar.value = event.fraction
            status_label.text = event.message
            if isinstance(event.partial, EyeDiagram):
                with previews:
                    ui.image(png_source(render_eye(event.partial))).classes("w-full")
            elif isinstance(event.partial, MarginSweep):
                with previews:
                    ui.image(png_source(render_margin(event.partial))).classes("w-full")

    ui.timer(0.3, drain_events)

    async def go() -> None:
        if shared["running"]:
            return
        if hardware and not port_select.value:
            ui.notify("Select a serial port first", type="warning")
            return
        shared["running"] = True
        shared["result"] = None
        previews.clear()
        progress_bar.value = 0.0
        config = SerdesConfig(**RESOLUTION_PRESETS[resolution.value])
        status_label.text = f"Running full SerDes sequence ({resolution.value.split(' --')[0]})..."
        go_button.disable()
        try:
            result: SerdesResult = await run.io_bound(
                run_serdes_capture,
                sim_length_mm,
                on_progress,
                STATE.simulate,
                selected_port(),
                config,
            )
            shared["result"] = result
            status_label.text = "Capture complete -- review previews, then save."
            save_button.enable()
        except Exception as e:
            status_label.text = f"Capture failed: {e}"
            ui.notify(f"Capture failed: {e}", type="negative", multi_line=True)
        finally:
            shared["running"] = False
            go_button.enable()

    def save() -> None:
        if not require_operator():
            return
        if not device.value:
            ui.notify("Enter the SerDes device", type="warning")
            return
        result = shared["result"]
        if result is None:
            ui.notify("Run a capture first", type="warning")
            return
        try:
            ref = save_serdes_session(
                STATE.repo_root,
                profile_id,
                condition,
                result,
                operator=STATE.operator,
                notes=notes.value or "",
                serdes_device=device.value,
            )
        except Exception as e:
            ui.notify(f"Save failed: {e}", type="negative", multi_line=True)
            return
        ui.notify(f"Saved session {ref.ref}", type="positive")
        ui.navigate.to(f"/profile/{profile_id}")

    with ui.row().classes("gap-2 mt-4"):
        check_button = ui.button("Check link", icon="cable", on_click=check_link).props("outline")
        go_button = ui.button("Go -- run full sequence", icon="play_arrow", on_click=go)
        save_button = ui.button("Save session", icon="save", on_click=save)
        save_button.disable()

    # Persistent readout for "Check link" (lock state, link rate, part numbers).
    link_panel = ui.column().classes("w-full mt-2")

    # Populate the port list and set the initial button-enabled state. Done
    # after the buttons exist so refresh_ports can toggle them.
    if hardware:
        refresh_ports()
