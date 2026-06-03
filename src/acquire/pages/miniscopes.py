"""Miniscope models page: view existing models, add new ones."""

from __future__ import annotations

from nicegui import ui
from pydantic import ValidationError

from src.acquire.controllers.miniscopes import (
    create_miniscope,
    list_miniscopes,
    miniscope_form_fields,
)
from src.acquire.pages.components import header
from src.acquire.state import STATE


@ui.page("/miniscopes")
def miniscopes_page() -> None:
    header("Miniscope Models")

    ui.markdown(
        "Miniscope models carry the electrical and link parameters that drive "
        "the published guidance: regulator limits, current draw, PoC choke "
        "DCRs, supply mode, and SERDES rate (the DAQ is folded into the "
        "Miniscope -- each version pairs with exactly one DAQ). Values come "
        "from datasheets and bench specs, not measurements."
    )

    models = list_miniscopes(STATE.repo_root)

    columns = [
        {"name": "model_id", "label": "Model", "field": "model_id", "align": "left"},
        {"name": "serdes", "label": "SERDES", "field": "serdes", "align": "left"},
        {"name": "supply", "label": "Supply", "field": "supply", "align": "left"},
        {"name": "regulator", "label": "Regulator (V)", "field": "regulator", "align": "left"},
        {"name": "current", "label": "Current (mA)", "field": "current", "align": "left"},
    ]
    rows = [
        {
            "model_id": m.model_id,
            "serdes": _serdes_cell(m),
            "supply": f"{m.supply_mode} ({m.default_supply_v:g} V)",
            "regulator": _range_cell(m.min_operating_voltage_v, m.max_operating_voltage_v),
            "current": _range_cell(m.min_current_ma, m.max_current_ma),
        }
        for m in models
    ]
    table = ui.table(columns=columns, rows=rows, row_key="model_id").classes("w-full")
    table.on("rowClick", lambda e: _detail_dialog(e.args[1]["model_id"]))

    ui.button("New miniscope model", icon="add", on_click=_new_miniscope_dialog)


def _serdes_cell(model) -> str:
    if not model.serdes_family and model.serdes_rate_gbps is None:
        return ""
    rate = f" @ {model.serdes_rate_gbps:g} Gbps" if model.serdes_rate_gbps is not None else ""
    return f"{model.serdes_family}{rate}"


def _range_cell(low, high) -> str:
    if low is None and high is None:
        return ""

    def fmt(v) -> str:
        return f"{v:g}" if v is not None else "?"

    return f"{fmt(low)} - {fmt(high)}"


def _detail_dialog(model_id: str) -> None:
    """Read-only view of every set field on a miniscope model."""
    model = next((m for m in list_miniscopes(STATE.repo_root) if m.model_id == model_id), None)
    if model is None:
        ui.notify(f"Model {model_id} not found", type="negative")
        return

    with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
        ui.label(model.model_id).classes("text-xl font-bold")
        if model.description:
            ui.label(model.description).classes("text-sm text-gray-600")
        with ui.grid(columns=2).classes("w-full gap-y-1"):
            for name, value in model.model_dump(exclude_none=True).items():
                if name in ("model_id", "description", "schema_version") or value in ("", []):
                    continue
                ui.label(name.replace("_", " ")).classes("text-sm text-gray-500")
                ui.label(", ".join(value) if isinstance(value, list) else f"{value}").classes(
                    "text-sm"
                )
        ui.button("Close", on_click=dialog.close).props("flat")

    dialog.open()


def _new_miniscope_dialog() -> None:
    """Form auto-generated from the MiniscopeModel schema."""
    fields = miniscope_form_fields()
    inputs: dict[str, object] = {}

    with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-h-[80vh] overflow-y-auto"):
        ui.label("New miniscope model").classes("text-xl font-bold")
        ui.markdown(
            "Datasheet/spec values only -- use the choke datasheet's **max "
            "DCR** for the PoC fields (summed per side if a side has more "
            "than one inductor)."
        )
        for f in fields:
            label = f.label + (" *" if f.required else "")
            if f.choices is not None:
                inputs[f.name] = (
                    ui.select(f.choices, label=label, value=f.default)
                    .props("outlined dense")
                    .classes("w-full")
                )
            elif f.python_type == "float":
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
                model = create_miniscope(STATE.repo_root, values)
            except ValidationError as e:
                error_label.text = "\n".join(
                    f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
                )
                return
            except FileExistsError as e:
                error_label.text = str(e)
                return
            dialog.close()
            ui.notify(f"Created miniscope model {model.model_id}", type="positive")
            ui.navigate.to("/miniscopes")

        with ui.row():
            ui.button("Save", on_click=save)
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()
