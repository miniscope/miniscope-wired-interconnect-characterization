"""Profile page: browse lengths/sessions and start a new measurement."""

from __future__ import annotations

from nicegui import ui

from src.acquire.controllers.profiles import list_lengths
from src.acquire.pages.components import header
from src.acquire.state import STATE

MEASUREMENT_TYPES = ["resistance", "serdes", "vna"]


@ui.page("/profile/{profile_id}")
def profile_page(profile_id: str) -> None:
    header(f"Profile: {profile_id}")

    lengths = list_lengths(STATE.repo_root, profile_id)

    if lengths:
        ui.label("Existing cable lengths").classes("text-lg font-semibold mt-4")
        for summary in lengths:
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label(f"{summary.cable_length_mm:g} mm").classes("text-lg")
                    counts = ", ".join(
                        f"{t}: {n}" for t, n in sorted(summary.sessions_by_type.items())
                    )
                    ui.label(counts or "no sessions yet").classes("text-gray-600")
                    with ui.row():
                        for mtype in MEASUREMENT_TYPES:
                            ui.button(
                                f"+ {mtype}",
                                on_click=lambda mtype=mtype, length=summary.cable_length_mm: (
                                    ui.navigate.to(f"/measure/{mtype}/{profile_id}/{length:g}")
                                ),
                            ).props("dense outline")
    else:
        ui.label("No measurements yet for this profile.").classes("text-gray-600")

    ui.label("Add a new cable length").classes("text-lg font-semibold mt-6")
    with ui.row().classes("items-end gap-2"):
        length_input = ui.number(label="Length (mm)", min=1).props("outlined dense")

        def start(mtype: str) -> None:
            if not length_input.value or length_input.value <= 0:
                ui.notify("Enter a positive cable length in mm", type="warning")
                return
            ui.navigate.to(f"/measure/{mtype}/{profile_id}/{length_input.value:g}")

        for mtype in MEASUREMENT_TYPES:
            ui.button(f"New {mtype} session", on_click=lambda mtype=mtype: start(mtype))
