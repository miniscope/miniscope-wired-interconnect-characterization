"""
SerDes driver interface.

Concrete drivers (simulated or real) only implement the primitives:
connect, link_status, link_locks, capture_eye, sweep_margin. The per-lane
orchestration, progress reporting, and result assembly live once in
`run_full_sequence` on the ABC, so the acquisition app behaves identically
against the simulator and the hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from src.instruments.types import (
    DEFAULT_LANES,
    EyeDiagram,
    MarginSweep,
    ProgressEvent,
    SerdesLane,
    SerdesResult,
)

ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class SerdesConfig:
    """Capture parameters for a full SerDes characterization sequence."""

    # Which lanes to characterize (channel + rate pairs). Defaults to the three
    # real lanes: forward @ 3G, forward @ 6G, reverse @ 187.5M.
    lanes: tuple[SerdesLane, ...] = field(default_factory=lambda: DEFAULT_LANES)

    # Eye monitor (EOM) grid.
    eye_bins: int = 64  # N x N grid resolution
    eye_observations: int = 32768  # bits sampled per grid point
    eye_source: str = "idle"  # idle | prbs | sensor

    # Link-margin sweep (TX amplitude, mV).
    margin_coarse_step_mv: float = 10.0
    margin_fine_step_mv: float = 0.0  # 0 disables the fine refinement pass
    margin_stop_mv: float = 50.0  # lowest amplitude swept to
    margin_dwell_s: float = 2.0  # dwell per step before reading errors
    margin_iterations: int = 1
    margin_continue_on_error: bool = False  # keep sweeping past first error

    # Per-lane link-lock stability dwell (s) for the capture gate: before
    # measuring a lane, the link must HOLD lock for this long, else the lane is
    # recorded as no-link and skipped. Mirrors the 'Check link' probe -- without
    # it, a marginal high rate (e.g. 6 Gbps on a long cable) that locks
    # momentarily then drops would slip through and get a garbage eye/margin.
    link_lock_settle_s: float = 5.0


class SerdesDriver(ABC):
    """Abstract GMSL2 SerDes characterization driver."""

    @abstractmethod
    def connect(self) -> None:
        """Verify the serializer/deserializer pair is reachable; raise InstrumentError."""
        ...

    @abstractmethod
    def link_status(self) -> dict[str, object]:
        """Quick health check for the GUI before a run (lock state, etc.)."""
        ...

    @abstractmethod
    def capture_eye(self, lane: SerdesLane, config: SerdesConfig) -> EyeDiagram:
        """Capture one eye-monitor grid for a lane."""
        ...

    @abstractmethod
    def sweep_margin(self, lane: SerdesLane, config: SerdesConfig) -> MarginSweep:
        """
        Run one link-margin sweep: coarse steps across the amplitude range,
        then (optionally) fine steps near the error onset. Implementations may
        average internal repeats per point but return final per-point values.
        """
        ...

    @abstractmethod
    def link_locks(self, lane: SerdesLane, settle_s: float = 0.0) -> bool:
        """Whether the link establishes (locks) for this lane.

        For forward lanes the implementation must switch the link to the lane's
        rate first (a cable may lock at 3 Gbps but not 6 Gbps). Used to detect
        cables that do not link at a given rate so they are recorded as no-link
        and scored 0, rather than capturing a garbage eye/margin. Must NOT raise
        on a failure to lock -- that is the expected signal; return False.

        ``settle_s`` adds a stability dwell: after the link locks, hold the rate
        for that long and require it to still be locked and error-free. A
        marginal high-rate link can acquire lock momentarily, then drop or start
        erroring, so a non-zero dwell avoids calling a flaky link good. 0 checks
        immediately (the default, used by the capture path).
        """
        ...

    @abstractmethod
    def close(self) -> None: ...

    def run_full_sequence(
        self,
        config: SerdesConfig | None = None,
        progress: ProgressCallback | None = None,
    ) -> SerdesResult:
        """
        Capture one eye + ``config.margin_iterations`` margin sweeps per lane.

        The eye grid dominates wall-clock, so it is captured once; only the
        link-margin sweep repeats, letting callers average out run-to-run noise.
        Each repeat is appended to ``result.margins`` (so a lane may have several
        sweeps); downstream averaging lives in the acquisition layer.

        Emits a ProgressEvent after each sub-step; the event's `partial`
        carries the just-completed EyeDiagram/MarginSweep for live preview.
        """
        if config is None:
            config = SerdesConfig()

        iterations = max(1, config.margin_iterations)
        result = SerdesResult()
        total_steps = len(config.lanes) * (1 + iterations)  # 1 eye + N margins per lane
        step = 0

        def emit(message: str, stage: str, partial: object | None) -> None:
            if progress is not None:
                progress(
                    ProgressEvent(
                        fraction=step / total_steps if total_steps else 1.0,
                        message=message,
                        stage=stage,
                        partial=partial,
                    )
                )

        for lane in config.lanes:
            # Gate with a stability dwell (same as 'Check link'): a lane that
            # only locks momentarily must NOT be measured -- it's recorded as
            # no-link instead. settle_s=0 (the default) sees a transient lock and
            # would wrongly proceed, which is the bug this avoids.
            if not self.link_locks(lane, settle_s=config.link_lock_settle_s):
                # Cable doesn't establish a link at this lane's rate: record it
                # as no-link (scored 0 downstream) and skip its eye + margin,
                # advancing past this lane's would-be steps so the bar stays sane.
                result.no_link_lanes.append(lane)
                step += 1 + iterations
                emit(
                    f"No link: {lane.channel.value} @ {lane.rate.label} "
                    "-- recorded, not measured",
                    f"nolink:{lane.lane_id}",
                    None,
                )
                continue

            eye = self.capture_eye(lane, config)
            result.eyes.append(eye)
            step += 1
            emit(
                f"Captured eye diagram: {lane.channel.value} @ {lane.rate.label}",
                f"eye:{lane.lane_id}",
                eye,
            )

            for i in range(iterations):
                margin = self.sweep_margin(lane, config)
                result.margins.append(margin)
                step += 1
                run_label = f" (run {i + 1}/{iterations})" if iterations > 1 else ""
                stage = f"margin:{lane.lane_id}" + (f"#{i + 1}" if iterations > 1 else "")
                emit(
                    f"Completed link-margin sweep{run_label}: "
                    f"{lane.channel.value} @ {lane.rate.label}",
                    stage,
                    margin,
                )

        return result
