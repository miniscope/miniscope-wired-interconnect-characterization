from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord
from src.processing.base import summary_filename

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """A processed session handed to aggregators: where it lives and what it is."""

    session_dir: Path
    derived_dir: Path
    record: SessionRecord

    @property
    def label(self) -> str:
        """Short human-readable label for plots and tables."""
        return f"{self.record.profile_id} {self.record.condition} {self.record.session_id}"


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

    @staticmethod
    def load_summaries(sessions: list[SessionContext], measurement_type: str) -> list[dict]:
        """
        Load each session's per-session summary JSON.

        Sessions whose summary is missing (processing hasn't run, or failed)
        are skipped with a warning rather than aborting the aggregation.
        """
        filename = summary_filename(measurement_type)
        summaries: list[dict] = []
        for ctx in sessions:
            summary_path = ctx.derived_dir / filename
            if not summary_path.exists():
                logger.warning(
                    "No processed %s summary for %s, skipping", measurement_type, ctx.label
                )
                continue
            with open(summary_path) as f:
                summaries.append(json.load(f))
        return summaries
