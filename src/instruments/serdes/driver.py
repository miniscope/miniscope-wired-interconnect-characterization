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

    # Which lanes to characterize. Defaults to the four real lanes: forward
    # @ 3G, forward @ 6G, and the 187.5M reverse channel under each forward rate.
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

    # Per-lane link-lock stability dwell (s), used ONLY when skip_lanes is None
    # (no prior link check): before measuring a lane the link must HOLD lock this
    # long, else the lane is recorded no-link and skipped.
    link_lock_settle_s: float = 5.0

    # Lanes the caller has already determined do NOT link (e.g. from the "Check
    # link" probe, which tests each forward rate with the stability dwell). When
    # provided, run_full_sequence / sweep_margins_only TRUST it: they record
    # these lanes as no-link and measure the rest WITHOUT re-probing per lane.
    # A capture's per-lane re-probe is unreliable on a marginal high rate (it can
    # momentarily lock), so honoring the up-front check is deterministic. None
    # (the default) falls back to gating each lane via link_locks -- used by
    # tests/scripts that run a capture with no prior check.
    skip_lanes: tuple[SerdesLane, ...] | None = None


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
        """Whether the link is USABLE at this lane's rate (not merely locked).

        For forward lanes the implementation must switch the link to the lane's
        rate first (a cable may lock at 3 Gbps but not 6 Gbps). Used to detect
        rates a cable can't carry so they are recorded as no-link and scored 0,
        rather than capturing a garbage eye/margin. Must NOT raise on a failure
        -- that is the expected signal; return False.

        ``settle_s`` runs a reliability dwell: after the link locks, hold the
        rate that long and accept it only if it stayed locked at the rate AND
        accrued zero decode errors. "Locked" alone is not enough -- a marginal
        high rate can lock yet error immediately under traffic. 0 checks the lock
        immediately with no reliability dwell.
        """
        ...

    @abstractmethod
    def close(self) -> None: ...

    @staticmethod
    def _margin_progress(lane: SerdesLane, i: int, iterations: int) -> tuple[str, str]:
        """(message, stage) for a just-completed margin sweep, numbering repeats.

        Shared by ``run_full_sequence`` and ``sweep_margins_only`` so a repeated
        sweep gets the same per-run stage tag (``margin:<lane>#<n>``) and label
        regardless of which entry point ran it.
        """
        run_label = f" (run {i + 1}/{iterations})" if iterations > 1 else ""
        stage = f"margin:{lane.lane_id}" + (f"#{i + 1}" if iterations > 1 else "")
        message = (
            f"Completed link-margin sweep{run_label}: " f"{lane.channel.value} @ {lane.rate.label}"
        )
        return message, stage

    def _lane_is_no_link(self, lane: SerdesLane, config: SerdesConfig) -> bool:
        """Whether to record a lane as no-link instead of measuring it.

        Trusts ``config.skip_lanes`` when the caller supplied a link-check result
        (deterministic -- the up-front check tested each forward rate with the
        stability dwell). Otherwise gates the lane live via ``link_locks``; that
        per-lane re-probe is unreliable on a marginal high rate, so it is the
        fallback for callers (tests/scripts) that ran no prior check.
        """
        if config.skip_lanes is not None:
            return lane in config.skip_lanes
        return not self.link_locks(lane, settle_s=config.link_lock_settle_s)

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
            if self._lane_is_no_link(lane, config):
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
                emit(*self._margin_progress(lane, i, iterations), margin)

        return result

    def sweep_margins_only(
        self,
        config: SerdesConfig | None = None,
        progress: ProgressCallback | None = None,
    ) -> list[MarginSweep]:
        """
        Run ``config.margin_iterations`` margin sweeps per lane, skipping the eye.

        Used to deepen the link-margin statistics of a capture whose eye has
        already been taken: the eye grid dominates wall-clock, so re-running just
        the margin lets the operator add more sweeps without paying for the eye
        again. Returns the new sweeps lane-major (like ``run_full_sequence``); the
        caller appends them to the existing ``SerdesResult.margins`` and the
        acquisition layer re-derives the per-lane average across all of them.

        Emits the same per-step ProgressEvents as the margin portion of
        ``run_full_sequence``, so the GUI previews repeats identically. Lanes that
        no longer establish a link are skipped (same stability-dwell gate as the
        full capture), so a no-link lane simply contributes no new sweeps.
        """
        if config is None:
            config = SerdesConfig()

        iterations = max(1, config.margin_iterations)
        margins: list[MarginSweep] = []
        total_steps = len(config.lanes) * iterations
        step = 0

        for lane in config.lanes:
            if self._lane_is_no_link(lane, config):
                # No link at this lane's rate -> add nothing for it (the caller's
                # existing no-link record stands), consistent with run_full_sequence.
                step += iterations
                if progress is not None:
                    progress(
                        ProgressEvent(
                            fraction=step / total_steps if total_steps else 1.0,
                            message=f"No link: {lane.channel.value} @ {lane.rate.label} -- skipped",
                            stage=f"nolink:{lane.lane_id}",
                            partial=None,
                        )
                    )
                continue

            for i in range(iterations):
                margin = self.sweep_margin(lane, config)
                margins.append(margin)
                step += 1
                if progress is not None:
                    message, stage = self._margin_progress(lane, i, iterations)
                    progress(
                        ProgressEvent(
                            fraction=step / total_steps if total_steps else 1.0,
                            message=message,
                            stage=stage,
                            partial=margin,
                        )
                    )

        return margins
