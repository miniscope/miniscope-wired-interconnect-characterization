"""Landing page: pick an existing cable profile or create a new one."""

from __future__ import annotations

from nicegui import ui
from pydantic import ValidationError

from src.acquire.controllers.profiles import (
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
        "Select a cable profile to view or add measurements, or define a new "
        "cable. **All data enters the repository through this app** so that "
        "every session is validated and consistently structured."
    )

    summaries = list_profile_summaries(STATE.repo_root)

    columns = [
        {"name": "profile_id", "label": "Profile", "field": "profile_id", "align": "left"},
        {"name": "name", "label": "Name", "field": "name", "align": "left"},
        {"name": "n_lengths", "label": "Lengths", "field": "n_lengths"},
        {"name": "n_sessions", "label": "Sessions", "field": "n_sessions"},
    ]
    rows = [
        {
            "profile_id": s.profile.profile_id,
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

    ui.button("New cable profile", icon="add", on_click=_new_profile_dialog)


def _new_profile_dialog() -> None:
    """Form auto-generated from the CableProfile schema."""
    fields = profile_form_fields()
    inputs: dict[str, object] = {}

    with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
        ui.label("New cable profile").classes("text-xl font-bold")
        ui.markdown(
            "Static specs only -- measured values (resistivity, attenuation) "
            "are computed by the pipeline, never entered here."
        )
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
                profile = create_profile(STATE.repo_root, values)
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
