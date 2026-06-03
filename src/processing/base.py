from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord


class BaseProcessor(ABC):
    """
    Abstract base class for session data processors.

    Each processor corresponds to a `processing_steps` entry in a
    definition.yaml. It takes a session directory and produces
    derived output files.
    """

    @abstractmethod
    def process(
        self,
        session_dir: Path,
        session: SessionRecord,
        definition: MeasurementDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        """
        Process one session.

        Args:
            session_dir: Path to the session folder (contains session.yaml + data)
            session: The validated SessionRecord
            definition: The measurement type definition
            output_dir: Where to write derived outputs

        Returns:
            Mapping of output logical name -> output file path
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of this processor (must match definition.yaml step name)."""
        ...
