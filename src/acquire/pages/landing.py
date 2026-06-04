"""Landing page: pick an existing DUT profile or create a new one."""

from __future__ import annotations

from collections.abc import Callable

from nicegui import ui
from pydantic import ValidationError

from src.acquire.controllers.profiles import (
    FormField,
    commutator_form_fields,
    create_commutator_profile,
    create_profile,
    list_profile_summaries,
    profile_form_fields,
)
from src.acquire.pages.components import header
from src.acquire.state import STATE


@ui.page("/")
def landing_page() -> None:
    header("Miniscope Cable Characterization")

    ui.markdown(
        "Select a DUT profile (cable or commutator) to view or add "
        "measurements, or define a new one. **All data enters the repository "
        "through this app** so that every session is validated and "
        "consistently structured."
    )

    summaries = list_profile_summaries(STATE.repo_root)

    columns = [
        {"name": "profile_id", "label": "Profile", "field": "profile_id", "align": "left"},
        {"name": "profile_type", "label": "Type", "field": "profile_type", "align": "left"},
        {"name": "name", "label": "Name", "field": "name", "align": "left"},
        {"name": "n_lengths", "label": "Conditions", "field": "n_lengths"},
        {"name": "n_sessions", "label": "Sessions", "field": "n_sessions"},
    ]
    rows = [
        {
            "profile_id": s.profile.profile_id,
            "profile_type": s.profile.profile_type,
            "name": s.profile.name,
            "n_lengths": s.n_lengths,
            "n_sessions": s.n_sessions,
        }
        for s in summaries
    ]
    table = ui.table(columns=columns, rows=rows, row_key="profile_id").classes("w-full")
    table.on(
        "rowClick",
        lambda e: ui.navigate.to(f"/profile/{e.args[1]['profile_id']}"),
    )

    with ui.row():
        ui.button("New cable profile", icon="add", on_click=_new_cable_dialog)
        ui.button("New commutator profile", icon="add", on_click=_new_commutator_dialog).props(
            "outline"
        )
        ui.button(
            "Miniscope models",
            icon="memory",
            on_click=lambda: ui.navigate.to("/miniscopes"),
        ).props("outline")


def _new_cable_dialog() -> None:
    _profile_dialog(
        title="New cable profile",
        intro=(
            "Static specs only -- measured values (resistivity, attenuation) "
            "are computed by the pipeline, never entered here."
        ),
        fields=profile_form_fields(),
        create=create_profile,
    )


def _new_commutator_dialog() -> None:
    _profile_dialog(
        title="New commutator profile",
        intro=(
            "Static specs only. Commutators are measured with the same "
            "session types as cables, per condition ('static' for now); the "
            "published result is the commutator's standalone impact."
        ),
        fields=commutator_form_fields(),
        create=create_commutator_profile,
    )


def _profile_dialog(title: str, intro: str, fields: list[FormField], create: Callable) -> None:
    """Form auto-generated from a profile schema."""
    inputs: dict[str, object] = {}

    with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-h-[80vh] overflow-y-auto"):
        ui.label(title).classes("text-xl font-bold")
        ui.markdown(intro)
        for f in fields:
            label = f.label + (" *" if f.required else "")
            if f.python_type == "float":
                inputs[f.name] = ui.number(label=label).props("outlined dense").classes("w-full")
            elif f.python_type == "list[str]":
                inputs[f.name] = (
                    ui.input(label=f"{label} (comma-separated)")
                    .props("outlined dense")
                    .classes("w-full")
                )
            else:
                inputs[f.name] = ui.input(label=label).props("outlined dense").classes("w-full")
            if f.description:
                ui.label(f.description).classes("text-xs text-gray-500")

        error_label = ui.label("").classes("text-red-600 text-sm whitespace-pre-line")

        def save() -> None:
            values: dict[str, object] = {}
            for f in fields:
                raw = inputs[f.name].value
                if raw in (None, ""):
                    continue
                if f.python_type == "list[str]":
                    values[f.name] = [t.strip() for t in str(raw).split(",") if t.strip()]
                else:
                    values[f.name] = raw
            try:
                profile = create(STATE.repo_root, values)
            except ValidationError as e:
                error_label.text = "\n".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
                )
                return
            except FileExistsError as e:
                error_label.text = str(e)
                return
            dialog.close()
            ui.notify(f"Created profile {profile.profile_id}", type="positive")
            ui.navigate.to(f"/profile/{profile.profile_id}")

        with ui.row():
            ui.button("Save", on_click=save)
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()
