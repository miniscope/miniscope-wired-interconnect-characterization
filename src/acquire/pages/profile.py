"""Profile page: browse conditions/sessions and start a new measurement."""

from __future__ import annotations

from nicegui import ui

from src.acquire.controllers.profiles import list_conditions
from src.acquire.pages.components import header
from src.acquire.state import STATE
from src.core.loading import load_profile
from src.core.profile_schemas import CommutatorProfile
from src.core.session_schemas import COMMUTATOR_CONDITIONS

MEASUREMENT_TYPES = ["resistance", "weight", "serdes", "vna"]


@ui.page("/profile/{profile_id}")
def profile_page(profile_id: str) -> None:
    header(f"Profile: {profile_id}")

    profile = None
    profile_path = STATE.repo_root / "profiles" / f"{profile_id}.yaml"
    if profile_path.exists():
        try:
            profile = load_profile(profile_path)
        except Exception as e:  # surfaced inline; measurements still browsable
            ui.notify(f"Profile failed to load: {e}", type="negative")

    is_commutator = isinstance(profile, CommutatorProfile)
    conditions = list_conditions(STATE.repo_root, profile_id)

    if conditions:
        noun = "conditions" if is_commutator else "cable lengths"
        ui.label(f"Existing {noun}").classes("text-lg font-semibold mt-4")
        for summary in conditions:
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between w-full"):
                    label = (
                        f"{summary.cable_length_mm:g} mm"
                        if summary.cable_length_mm is not None
                        else summary.condition
                    )
                    ui.label(label).classes("text-lg")
                    counts = ", ".join(
                        f"{t}: {n}" for t, n in sorted(summary.sessions_by_type.items())
                    )
                    ui.label(counts or "no sessions yet").classes("text-gray-600")
                    with ui.row():
                        for mtype in MEASUREMENT_TYPES:
                            ui.button(
                                f"+ {mtype}",
                                on_click=lambda mtype=mtype, cond=summary.condition: (
                                    ui.navigate.to(f"/measure/{mtype}/{profile_id}/{cond}")
                                ),
                            ).props("dense outline")
    else:
        ui.label("No measurements yet for this profile.").classes("text-gray-600")

    if is_commutator:
        ui.label("Measure this commutator").classes("text-lg font-semibold mt-6")
        ui.markdown(
            "Commutators are measured per *condition* rather than per length "
            f"(currently: {', '.join(sorted(COMMUTATOR_CONDITIONS))}). Insert "
            "the commutator in the test path with short jumpers; the results "
            "are reported as its standalone impact."
        )
        with ui.row().classes("items-end gap-2"):
            condition_select = ui.select(
                sorted(COMMUTATOR_CONDITIONS), value="static", label="Condition"
            ).props("outlined dense")

            def start_commutator(mtype: str) -> None:
                ui.navigate.to(f"/measure/{mtype}/{profile_id}/{condition_select.value}")

            for mtype in MEASUREMENT_TYPES:
                ui.button(
                    f"New {mtype} session", on_click=lambda mtype=mtype: start_commutator(mtype)
                )
    else:
        ui.label("Add a new cable length").classes("text-lg font-semibold mt-6")
        with ui.row().classes("items-end gap-2"):
            length_input = ui.number(label="Length (mm)", min=1).props("outlined dense")

            def start(mtype: str) -> None:
                if not length_input.value or length_input.value <= 0:
                    ui.notify("Enter a positive cable length in mm", type="warning")
                    return
                ui.navigate.to(f"/measure/{mtype}/{profile_id}/{length_input.value:g}mm")

            for mtype in MEASUREMENT_TYPES:
                ui.button(f"New {mtype} session", on_click=lambda mtype=mtype: start(mtype))
