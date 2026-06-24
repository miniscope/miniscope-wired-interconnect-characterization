"""SerDes measurement page: automated capture with progress + live previews."""

from __future__ import annotations

import threading

from nicegui import run, ui

from src.acquire.controllers.sessions import (
    check_serdes_links,
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
from src.instruments.types import (
    FORWARD_3G,
    FORWARD_6G,
    EyeDiagram,
    MarginSweep,
    ProgressEvent,
    SerdesLane,
    SerdesResult,
    group_margins_by_lane,
)
from src.processing.serdes import average_margin_sweeps

# Forward lanes the 'Check link' probe reports per-rate lock for; the reverse
# control channel is excluded (it is not scored and rides on the forward link).
PROBED_FORWARD_LANES = (FORWARD_3G, FORWARD_6G)

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


def lane_section_title(lane: SerdesLane) -> str:
    """Section heading for a lane's results, e.g. 'Forward link -- 6 Gbps'.

    For the reverse channel, which is captured once per forward rate, the
    forward context is appended so the two 187.5 Mbps cards are distinguishable.
    """
    title = f"{lane.channel.display} link -- {lane.rate.display}"
    if lane.forward_rate is not None:
        title += f" (under {lane.forward_rate.display} forward)"
    return title


def _device_box(role: str, dev: dict) -> None:
    """One chip in the link diagram: role, part number, ID, lock chips."""
    with ui.card().classes("items-center p-3 min-w-48"):
        ui.label(role).classes("text-xs uppercase text-gray-500")
        ui.label(str(dev.get("part", "?"))).classes("text-lg font-bold")
        dev_id = dev.get("device_id")
        ui.label(f"ID 0x{dev_id:02X}" if isinstance(dev_id, int) else "ID ?").classes(
            "text-xs text-gray-600"
        )
        with ui.row().classes("gap-1 mt-1"):
            _status_chip(bool(dev.get("locked")), "locked", "unlocked")
            _status_chip(not dev.get("error"), "no errors", "errors")
            _status_chip(bool(dev.get("cmu")), "CMU", "no CMU")


def render_link_status(container, status: dict, cable_label: str = "") -> None:
    """Render the SerDes link status into a persistent, readable panel.

    For the real driver, draws a Serializer -- cable -- Deserializer diagram
    with each chip's part number and lock state, the cable length in the
    middle, and arrows marking the forward (Ser->Des) and reverse (Des->Ser)
    channel directions. Falls back to a flat key/value dump for the simulator.
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
            # Serializer --cable--> Deserializer, with channel-direction arrows.
            fwd_rate = status.get("forward_rate", "unknown")
            with ui.row().classes("items-center gap-3 w-full mt-1"):
                _device_box("Serializer", ser)
                with ui.column().classes("items-center grow gap-0"):
                    with ui.row().classes("items-center gap-1 text-blue-700"):
                        ui.label(f"Forward {fwd_rate}").classes("text-xs font-medium")
                        ui.icon("arrow_forward")
                    ui.separator().classes("w-full")
                    ui.label(f"cable: {cable_label}" if cable_label else "cable").classes(
                        "text-xs text-gray-600"
                    )
                    with ui.row().classes("items-center gap-1 text-amber-700"):
                        ui.icon("arrow_back")
                        ui.label("Reverse 187.5 Mbps").classes("text-xs font-medium")
                _device_box("Deserializer", des)
        else:
            for key, value in status.items():
                ui.label(f"{key}: {value}").classes("text-sm")


def render_link_rates(container, locks: dict) -> None:
    """Per-forward-rate lock chips: shows whether the link establishes at each
    rate (3 Gbps, 6 Gbps), so a cable that links at one rate but not the other
    is visible at check time. Appends to the container (does not clear it)."""
    with container, ui.card().classes("w-full"):
        ui.label("Forward link lock by rate").classes("text-sm font-semibold")
        with ui.row().classes("items-center gap-4"):
            for lane in PROBED_FORWARD_LANES:
                with ui.row().classes("items-center gap-1"):
                    ui.label(f"{lane.rate.display}:").classes("text-sm")
                    _status_chip(bool(locks.get(lane.lane_id, False)), "locked", "no link")


def margin_summary_row(sweep: MarginSweep) -> dict:
    """One link-margin summary row: deepest clean TX amplitude and where it failed.

    Walking the sweep from the strongest amplitude down, the margin floor is the
    lowest 'ok' step in the leading clean run and the first non-'ok' step is
    where the link broke. Taking the clean *prefix* (rather than the global min
    'ok' step) keeps this correct for an averaged sweep, whose ok/error steps
    can interleave below the first failure.
    """
    pts = sweep.points
    ordered = sorted(pts, key=lambda p: p.tx_amplitude_mv, reverse=True)
    clean_prefix: list[float] = []
    fail = None
    for p in ordered:
        if p.status != "ok":
            fail = p
            break
        clean_prefix.append(p.tx_amplitude_mv)
    if fail is None:
        outcome = "clean throughout"
    else:
        label = "lost lock" if fail.status == "lost_lock" else fail.status
        outcome = f"{label} at {fail.tx_amplitude_mv:.0f} mV"
    return {
        "lane": sweep.lane.label,
        "steps": len(pts),
        "clean_mv": f"{min(clean_prefix):.0f}" if clean_prefix else "--",
        "fail_mv": f"{fail.tx_amplitude_mv:.0f}" if fail else "--",
        "outcome": outcome,
    }


def margin_iteration_rows(margins: list[MarginSweep]) -> list[dict]:
    """One summary row per (lane, iteration), labelled with the iteration number."""
    rows: list[dict] = []
    for _lane, sweeps in group_margins_by_lane(margins):
        for i, sweep in enumerate(sweeps, start=1):
            rows.append({**margin_summary_row(sweep), "iteration": str(i)})
    return rows


def margin_average_rows(margins: list[MarginSweep]) -> list[dict]:
    """One averaged summary row per lane (the mean across that lane's iterations)."""
    return [
        margin_summary_row(average_margin_sweeps(sweeps))
        for _lane, sweeps in group_margins_by_lane(margins)
    ]


def _summary_columns(*, iteration: bool) -> list[dict]:
    columns = [{"name": "lane", "label": "Lane", "field": "lane", "align": "left"}]
    if iteration:
        columns.append(
            {"name": "iteration", "label": "Iteration", "field": "iteration", "align": "left"}
        )
    columns += [
        {"name": "steps", "label": "Steps", "field": "steps", "align": "right"},
        {"name": "clean_mv", "label": "Clean to (mV)", "field": "clean_mv", "align": "right"},
        {"name": "fail_mv", "label": "First error (mV)", "field": "fail_mv", "align": "right"},
        {"name": "outcome", "label": "Outcome", "field": "outcome", "align": "left"},
    ]
    return columns


def _summary_table(title: str, rows: list[dict], *, iteration: bool) -> None:
    with ui.card().classes("w-full"):
        ui.label(title).classes("text-base font-semibold")
        ui.table(columns=_summary_columns(iteration=iteration), rows=rows).props(
            "flat dense"
        ).classes("w-full")


def render_margin_summary(container, result) -> None:
    """Render the link-margin summary tables (no-op if there are none).

    When the sweep was repeated, the per-iteration rows and the per-lane
    averages are shown in two separate tables; a single run collapses to one
    table with one row per lane.
    """
    container.clear()
    margins = getattr(result, "margins", None)
    if not margins:
        return
    grouped = group_margins_by_lane(margins)
    multi_run = any(len(sweeps) > 1 for _, sweeps in grouped)
    with container:
        if multi_run:
            _summary_table(
                "Link-margin -- each iteration", margin_iteration_rows(margins), iteration=True
            )
            _summary_table(
                "Link-margin -- average per lane", margin_average_rows(margins), iteration=False
            )
        else:
            rows = [margin_summary_row(sweeps[0]) for _lane, sweeps in grouped]
            _summary_table("Link-margin summary", rows, iteration=False)


# Margin-step statuses where the link dropped lock outright (vs the normal
# "errors" floor). A margin sweep reaching one of these IS its measured floor --
# valid data, not a failure -- so a completed capture surfaces it as a note but
# does NOT block the save. (A genuinely stuck device makes the capture raise,
# which is handled separately and does prompt a power-cycle + re-check.)
LOCK_LOSS_STATUSES = frozenset({"lost_lock", "ser_unreachable"})


def lock_was_lost(result) -> bool:
    """True if any margin step lost lock / lost the serializer during the run."""
    return any(
        point.status in LOCK_LOSS_STATUSES
        for sweep in getattr(result, "margins", [])
        for point in sweep.points
    )


@ui.page("/measure/serdes/{profile_id}/{condition}")
def serdes_page(profile_id: str, condition: str) -> None:
    header(f"SerDes -- {profile_id} @ {condition}")
    # Simulated drivers model loss vs cable length; named conditions
    # (commutator states) use a short nominal length.
    parsed_length_mm = parse_condition_dir(condition)
    sim_length_mm = parsed_length_mm or 100.0
    cable_label = f"{parsed_length_mm:.0f} mm" if parsed_length_mm is not None else condition
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
        # Only gate "Check link" on a port being present; "Go" is unlocked
        # separately, once a link check succeeds (see check_link()).
        ports = list_serial_ports()
        options = {p.device: f"{p.device} -- {p.description}" for p in ports}
        port_select.set_options(options)
        if ports:
            if port_select.value not in options:
                port_select.set_value(ports[0].device)
            port_warning.text = ""
            check_button.enable()
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

    # "Check link" readout, pinned near the top so it stays visible while the
    # capture results stream in below.
    link_panel = ui.column().classes("w-full")

    device = ui.input(label="SerDes device *").props("outlined").classes("w-96")
    notes = ui.input(label="Session notes").props("outlined").classes("w-full")
    with ui.row().classes("items-center gap-3 w-full"):
        resolution = (
            ui.select(
                list(RESOLUTION_PRESETS), value=DEFAULT_RESOLUTION, label="Capture resolution"
            )
            .props("outlined")
            .classes("w-96")
        )
        # Repeat just the link-margin sweep this many times per lane (the eye is
        # captured once); the results average out run-to-run noise.
        iterations = (
            ui.number(label="Margin iterations", value=1, min=1, max=20, precision=0, step=1)
            .props("outlined")
            .classes("w-48")
        )

    status_label = ui.label("").classes("text-gray-700")
    progress_bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
    # Prominent banner shown when the link drops lock mid-run (power-cycle prompt).
    reset_banner = ui.column().classes("w-full")
    # Results are grouped into one clearly-separated section per speed/lane
    # (forward 3G, forward 6G, reverse), created on demand as previews arrive.
    results = ui.column().classes("w-full gap-3")
    lane_grids: dict[str, object] = {}
    # Forward lanes the last link check found not locking; the "Log no-link"
    # button records these as not-recommended (score 0) without a full capture.
    nolink_lanes: list[SerdesLane] = []

    def show_reset_needed() -> None:
        """Warn that the link dropped lock and the device likely needs a power cycle."""
        reset_banner.clear()
        with reset_banner, ui.card().classes("w-full bg-red-50 border border-red-300"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("power_off").classes("text-red-600 text-2xl")
                ui.label("Link lost lock -- manual reset needed").classes("text-red-700 font-bold")
            ui.label(
                "The SerDes link dropped lock during the sweep and may stay stuck. "
                "Power-cycle the device (turn it OFF, then back ON), then click 'Check link' "
                "to confirm it re-locks before running again. This run was not saved."
            ).classes("text-red-700 text-sm")
        ui.notify(
            "Link lost lock -- power-cycle the device, then re-check.",
            type="negative",
            multi_line=True,
        )

    def lane_grid(lane: SerdesLane):
        """Get or create the results section (eye + margin) for one lane."""
        if lane.lane_id not in lane_grids:
            with results, ui.card().classes("w-full"):
                ui.label(lane_section_title(lane)).classes("text-base font-semibold")
                lane_grids[lane.lane_id] = ui.grid(columns=2).classes("w-full gap-2")
        return lane_grids[lane.lane_id]

    def render_final_results(result: SerdesResult) -> None:
        """Replace the streamed previews with the final view: each lane's eye
        plus its averaged link-margin curve (one margin plot per lane, even when
        the sweep was repeated several times)."""
        results.clear()
        lane_grids.clear()
        sweeps_by_lane = {
            lane.lane_id: sweeps for lane, sweeps in group_margins_by_lane(result.margins)
        }
        for eye in result.eyes:
            with lane_grid(eye.lane):
                ui.image(png_source(render_eye(eye))).classes("w-full")
                sweeps = sweeps_by_lane.get(eye.lane.lane_id)
                if sweeps:
                    ui.image(png_source(render_margin(average_margin_sweeps(sweeps)))).classes(
                        "w-full"
                    )
        # Lanes the link never established: shown as a clear no-link card; they
        # are recorded and scored 0 downstream rather than dropped.
        for lane in getattr(result, "no_link_lanes", []):
            with lane_grid(lane), ui.column().classes("items-center gap-1 p-3"):
                ui.icon("link_off").classes("text-red-600 text-3xl")
                ui.label("No link -- scored 0").classes("text-red-700 font-bold")
                ui.label("The link did not establish at this rate.").classes(
                    "text-xs text-gray-600"
                )

    # Shared between the worker thread and the UI timer
    shared: dict = {"events": [], "result": None, "running": False, "lock": threading.Lock()}

    def selected_port() -> str | None:
        """The chosen serial port, or None in simulate mode (driver default)."""
        return port_select.value if hardware else None

    def selected_iterations() -> int:
        """Margin-sweep repeats per lane (>= 1); coerces a blank/odd field to 1."""
        try:
            return max(1, int(iterations.value))
        except (TypeError, ValueError):
            return 1

    async def check_link() -> None:
        if hardware and not port_select.value:
            ui.notify("Select a serial port first", type="warning")
            return
        check_button.disable()
        reset_banner.clear()
        log_nolink_button.disable()
        nolink_lanes.clear()
        link_panel.clear()
        with link_panel:
            ui.label("Checking link...").classes("text-gray-600")
        try:
            checked = await run.io_bound(
                check_serdes_links, sim_length_mm, STATE.simulate, selected_port()
            )
        except Exception as e:
            link_panel.clear()
            with link_panel:
                ui.label(f"Link check failed: {e}").classes("text-red-600")
            ui.notify(f"Link check failed: {e}", type="negative", multi_line=True)
            return
        finally:
            check_button.enable()

        # check_serdes_links never raises (it runs on a worker thread, which can
        # swallow exceptions to None); a bench-reach failure comes back as
        # "error". Surface either as a failed check rather than crashing here.
        error = checked.get("error") if checked else "no result returned from link check"
        if error:
            link_panel.clear()
            with link_panel:
                ui.label(f"Link check failed: {error}").classes("text-red-600")
            ui.notify(f"Link check failed: {error}", type="negative", multi_line=True)
            return

        status = checked.get("status")
        locks = checked.get("locks", {})
        link_panel.clear()
        if status is not None:
            render_link_status(link_panel, status, cable_label)
        render_link_rates(link_panel, locks)

        # Forward rate(s) that did not lock can be logged as no-link (scored 0).
        nolink_lanes.extend(
            lane for lane in PROBED_FORWARD_LANES if not locks.get(lane.lane_id, False)
        )
        if nolink_lanes:
            log_nolink_button.enable()
        # Go is the gate for a full capture: enabled once at least one forward
        # rate locks. The capture records any non-locking lane as no-link itself.
        if any(locks.get(lane.lane_id, False) for lane in PROBED_FORWARD_LANES):
            go_button.enable()
        else:
            go_button.disable()

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
                with lane_grid(event.partial.lane):
                    ui.image(png_source(render_eye(event.partial))).classes("w-full")
            elif isinstance(event.partial, MarginSweep):
                with lane_grid(event.partial.lane):
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
        results.clear()
        lane_grids.clear()
        margin_summary.clear()
        reset_banner.clear()
        save_button.disable()
        log_nolink_button.disable()
        progress_bar.value = 0.0
        runs = selected_iterations()
        config = SerdesConfig(**RESOLUTION_PRESETS[resolution.value], margin_iterations=runs)
        preset = resolution.value.split(" --")[0]
        runs_note = f", {runs} margin iterations" if runs > 1 else ""
        status_label.text = f"Running full SerDes sequence ({preset}{runs_note})..."
        go_button.disable()
        # When the link drops lock the device needs a manual power cycle, so we
        # keep Go disabled until the operator re-checks the link (post reset).
        needs_reset = False
        try:
            result: SerdesResult = await run.io_bound(
                run_serdes_capture,
                sim_length_mm,
                on_progress,
                STATE.simulate,
                selected_port(),
                config,
            )
            # Drop any previews still queued so the rebuilt (averaged) view wins.
            with shared["lock"]:
                shared["events"].clear()
            render_final_results(result)
            render_margin_summary(margin_summary, result)
            # The capture completed, so the device is functional and the recorded
            # eye/margin data is valid -- including a margin sweep that reached its
            # floor by dropping lock (lost_lock / ser_unreachable is the measured
            # floor, not a failure). Always saveable; a genuinely stuck device
            # would have raised instead (handled in the except branch).
            shared["result"] = result
            notes: list[str] = []
            if result.no_link_lanes:
                lanes_txt = ", ".join(lane.label for lane in result.no_link_lanes)
                notes.append(f"{lanes_txt} did not link (scored 0)")
            if lock_was_lost(result):
                notes.append("a margin sweep hit its lock-loss floor (the measured floor, normal)")
            suffix = f" -- {'; '.join(notes)}" if notes else ""
            status_label.text = f"Capture complete{suffix}. Review results, then save."
            save_button.enable()
        except Exception as e:
            status_label.text = f"Capture failed: {e}"
            ui.notify(f"Capture failed: {e}", type="negative", multi_line=True)
            if "lock" in str(e).lower():
                needs_reset = True
                show_reset_needed()
        finally:
            shared["running"] = False
            # Re-enable Go for a retry, unless the link must be reset + re-checked.
            if not needs_reset:
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

    def log_no_link() -> None:
        """Record the forward rate(s) that failed the last link check as no-link.

        Writes a serdes session marking the failed lanes linked=0 (scored 0
        downstream), so a cable that won't link stays visible on the wiki rather
        than vanishing -- without running a full ~25-min capture. Lanes that did
        link are recorded but left uncharacterized until a real capture covers them.
        """
        if not require_operator():
            return
        if not device.value:
            ui.notify("Enter the SerDes device", type="warning")
            return
        if not nolink_lanes:
            ui.notify("Run a link check that finds a no-link rate first", type="warning")
            return
        try:
            ref = save_serdes_session(
                STATE.repo_root,
                profile_id,
                condition,
                SerdesResult(no_link_lanes=list(nolink_lanes)),
                operator=STATE.operator,
                notes=notes.value or "",
                serdes_device=device.value,
            )
        except Exception as e:
            ui.notify(f"Save failed: {e}", type="negative", multi_line=True)
            return
        lanes_txt = ", ".join(lane.label for lane in nolink_lanes)
        ui.notify(f"Logged no-link ({lanes_txt}) -- session {ref.ref}", type="positive")
        ui.navigate.to(f"/profile/{profile_id}")

    with ui.row().classes("gap-2 mt-4"):
        check_button = ui.button("Check link", icon="cable", on_click=check_link).props("outline")
        go_button = ui.button("Go -- run full sequence", icon="play_arrow", on_click=go)
        log_nolink_button = ui.button("Log no-link", icon="link_off", on_click=log_no_link).props(
            "outline color=red"
        )
        save_button = ui.button("Save session", icon="save", on_click=save)
        # Go is gated behind a successful "Check link"; Save behind a clean run.
        go_button.disable()
        go_button.tooltip("Run a link check first")
        # Enabled when a link check finds a forward rate that won't lock.
        log_nolink_button.disable()
        log_nolink_button.tooltip(
            "Record a rate that won't lock as not-recommended (score 0), no full capture"
        )
        save_button.disable()

    # Per-lane link-margin summary table, pinned at the bottom: one row per run
    # plus an averaged row when the sweep was repeated. Filled when a run ends.
    margin_summary = ui.column().classes("w-full")

    # Populate the port list and set the initial button-enabled state. Done
    # after the buttons exist so refresh_ports can toggle them.
    if hardware:
        refresh_ports()
