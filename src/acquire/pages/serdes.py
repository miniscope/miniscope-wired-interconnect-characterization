"""SerDes measurement page: automated capture with progress + live previews."""

from __future__ import annotations

import threading

from nicegui import run, ui

from src.acquire.controllers.sessions import run_serdes_capture, save_serdes_session
from src.acquire.pages.components import header, png_source, protocol_panel, require_operator
from src.acquire.plots import render_eye, render_margin
from src.acquire.state import STATE
from src.core.session_schemas import parse_condition_dir
from src.instruments.registry import get_serdes_driver
from src.instruments.types import EyeDiagram, MarginSweep, ProgressEvent, SerdesResult


@ui.page("/measure/serdes/{profile_id}/{condition}")
def serdes_page(profile_id: str, condition: str) -> None:
    header(f"SerDes -- {profile_id} @ {condition}")
    # Simulated drivers model loss vs cable length; named conditions
    # (commutator states) use a short nominal length.
    sim_length_mm = parse_condition_dir(condition) or 100.0
    protocol_panel("serdes")

    device = ui.input(label="SerDes device *").props("outlined").classes("w-96")
    notes = ui.input(label="Session notes").props("outlined").classes("w-full")

    status_label = ui.label("").classes("text-gray-700")
    progress_bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
    previews = ui.grid(columns=4).classes("w-full gap-2")

    # Shared between the worker thread and the UI timer
    shared: dict = {"events": [], "result": None, "running": False, "lock": threading.Lock()}

    def check_link() -> None:
        driver = get_serdes_driver(simulate=STATE.simulate, cable_length_mm=sim_length_mm)
        try:
            driver.connect()
            status = driver.link_status()
        except Exception as e:
            ui.notify(f"Link check failed: {e}", type="negative")
            return
        finally:
            driver.close()
        ui.notify(f"Link status: {status}", type="info")

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
        shared["running"] = True
        shared["result"] = None
        previews.clear()
        progress_bar.value = 0.0
        status_label.text = "Running full SerDes sequence..."
        go_button.disable()
        try:
            result: SerdesResult = await run.io_bound(
                run_serdes_capture, sim_length_mm, on_progress, STATE.simulate
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
        ui.button("Check link", icon="cable", on_click=check_link).props("outline")
        go_button = ui.button("Go -- run full sequence", icon="play_arrow", on_click=go)
        save_button = ui.button("Save session", icon="save", on_click=save)
        save_button.disable()
