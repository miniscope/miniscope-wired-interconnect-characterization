from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord, length_dir_name


@dataclass
class SessionContext:
    """A processed session handed to aggregators: where it lives and what it is."""

    session_dir: Path
    derived_dir: Path
    record: SessionRecord

    @property
    def label(self) -> str:
        """Short human-readable label for plots and tables."""
        length = length_dir_name(self.record.cable_length_mm)
        return f"{self.record.profile_id} {length} {self.record.session_id}"


class BaseAggregator(ABC):
    """
    Abstract base class for cross-session aggregators.

    Aggregators operate on ALL processed sessions of a given measurement
    type and produce summary tables and plots.
    """

    @abstractmethod
    def aggregate(
        self,
        sessions: list[SessionContext],
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        """
        Aggregate across sessions.

        Args:
            sessions: Processed sessions (all of the same measurement type)
            definition: The measurement type definition
            output_dir: Where to write aggregated outputs

        Returns:
            Mapping of output logical name -> output file path
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of this aggregator (must match definition.yaml aggregation name)."""
        ...
