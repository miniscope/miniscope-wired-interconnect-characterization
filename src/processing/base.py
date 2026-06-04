from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.core.schemas import MeasurementDefinition
from src.core.session_schemas import SessionRecord


def summary_filename(measurement_type: str) -> str:
    """
    Canonical name of the per-session summary JSON a processor writes.

    This is the contract between the processing stage (which writes it) and
    the aggregation/consolidation stages (which read it back), so it lives
    with the producer and is derived from the type rather than re-typed in
    each consumer.
    """
    return f"{measurement_type}_summary.json"


def session_header(session: SessionRecord) -> dict:
    """
    The per-session metadata block every summary JSON opens with.

    Each processor adds its own type-specific stats on top; this keeps the
    shared identity fields in one place so adding/renaming one touches a
    single function instead of every processor.
    """
    return {
        "session_id": session.session_id,
        "profile_id": session.profile_id,
        "cable_length_mm": session.cable_length_mm,
        "condition": session.condition,
        "measurement_type": session.measurement_type,
        "date": str(session.date),
        "operator": session.operator,
    }


def copy_type_fields(summary: dict, session: SessionRecord, keys: list[str]) -> None:
    """Copy the named type_fields into a summary dict, skipping absent ones."""
    for key in keys:
        if key in session.type_fields:
            summary[key] = session.type_fields[key]


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
