"""Shared UI building blocks for the acquisition pages."""

from __future__ import annotations

import base64

from nicegui import app, ui

from src.acquire.controllers.protocols import load_protocol_markdown
from src.acquire.state import STATE


def png_source(png_bytes: bytes) -> str:
    """Data URL for ui.image from raw PNG bytes."""
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode()


def header(title: str) -> None:
    with ui.row().classes("items-center w-full justify-between"):
        ui.label(title).classes("text-2xl font-bold")
        with ui.row().classes("items-center gap-2"):
            ui.label("Operator:")
            ui.input(value=STATE.operator, on_change=lambda e: _set_operator(e.value)).props(
                "dense outlined"
            )
            ui.link("Home", "/")
            ui.button("Close tool", icon="power_settings_new", on_click=_confirm_close).props(
                "flat color=red"
            ).tooltip("Stop the app and free the port")


def _confirm_close() -> None:
    """Ask before shutting the server down -- it stops the app for everyone."""
    with ui.dialog() as dialog, ui.card():
        ui.label("Close the tool?").classes("text-lg font-bold")
        ui.label(
            "This stops the app for everyone and frees the port. " "Any unsaved capture is lost."
        ).classes("text-sm text-gray-600")
        with ui.row().classes("justify-end gap-2 w-full"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Close tool", color="red", on_click=lambda: _shutdown(dialog))
    dialog.open()


def _shutdown(dialog) -> None:
    dialog.close()
    ui.notify("Shutting down -- you can close this browser tab.", type="warning")
    # Delay slightly so the notification reaches the client before the server
    # stops; app.shutdown() works because the app runs with reload disabled.
    ui.timer(0.5, app.shutdown, once=True)


def _set_operator(value: str) -> None:
    STATE.operator = value or ""


def require_operator() -> bool:
    """Sessions must record who ran them; block saves until a name is set."""
    if not STATE.operator.strip():
        ui.notify("Enter your name in the Operator box first", type="warning")
        return False
    return True


def protocol_panel(measurement_type: str) -> None:
    """Collapsible panel showing the embedded measurement protocol."""
    with ui.expansion("Protocol -- read me before measuring", icon="menu_book").classes(
        "w-full"
    ) as panel:
        panel.open()
        ui.markdown(load_protocol_markdown(measurement_type))
