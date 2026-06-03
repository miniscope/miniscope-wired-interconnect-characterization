"""
SerDes driver interface.

Concrete drivers (simulated or real) only implement the four primitives:
connect, link_status, capture_eye, sweep_margin. The channel x rate
orchestration, progress reporting, and result assembly live once in
`run_full_sequence` on the ABC, so the acquisition app behaves identically
against the simulator and the hardware.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from src.instruments.types import (
    EyeDiagram,
    MarginSweep,
    ProgressEvent,
    SerdesChannel,
    SerdesRate,
    SerdesResult,
)

ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class SerdesConfig:
    """Capture parameters for a full SerDes characterization sequence."""

    channels: tuple[SerdesChannel, ...] = (SerdesChannel.FORWARD, SerdesChannel.BACK)
    rates: tuple[SerdesRate, ...] = (SerdesRate.GBPS_3, SerdesRate.GBPS_6)
    eye_voltage_bins: int = 64
    eye_time_bins: int = 64
    eye_repeats: int = 1
    margin_coarse_step_mv: float = 10.0
    margin_fine_step_mv: float = 1.0
    margin_min_mv: float = 10.0
    margin_max_mv: float = 200.0
    margin_repeats: int = 1


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
    def capture_eye(
        self, channel: SerdesChannel, rate: SerdesRate, config: SerdesConfig
    ) -> EyeDiagram:
        """Capture one eye diagram for a channel/rate combo."""
        ...

    @abstractmethod
    def sweep_margin(
        self, channel: SerdesChannel, rate: SerdesRate, config: SerdesConfig
    ) -> MarginSweep:
        """
        Run one link-margin sweep: coarse steps across the amplitude range,
        then fine steps near the error onset. Implementations may average
        internal repeats per point but return final per-point values.
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
        Capture eye + margin for every channel x rate combo.

        Emits a ProgressEvent after each sub-step; the event's `partial`
        carries the just-completed EyeDiagram/MarginSweep for live preview.
        """
        if config is None:
            config = SerdesConfig()

        result = SerdesResult()
        combos = [(c, r) for c in config.channels for r in config.rates]
        total_steps = len(combos) * 2  # eye + margin per combo
        step = 0

        def emit(message: str, stage: str, partial: object | None) -> None:
            if progress is not None:
                progress(
                    ProgressEvent(
                        fraction=step / total_steps,
                        message=message,
                        stage=stage,
                        partial=partial,
                    )
                )

        for channel, rate in combos:
            eye = self.capture_eye(channel, rate, config)
            result.eyes.append(eye)
            step += 1
            emit(
                f"Captured eye diagram: {channel.value} @ {rate.value} Gbps",
                f"eye:{channel.value}:{rate.value}",
                eye,
            )

            margin = self.sweep_margin(channel, rate, config)
            result.margins.append(margin)
            step += 1
            emit(
                f"Completed link-margin sweep: {channel.value} @ {rate.value} Gbps",
                f"margin:{channel.value}:{rate.value}",
                margin,
            )

        return result
