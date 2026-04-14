from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseWikiClient(ABC):
    """Interface for fetching model metadata from the miniscope.org wiki."""

    @abstractmethod
    def fetch_model(self, model_type: str, model_id: str) -> dict | None:
        """
        Fetch model metadata from the wiki.

        Args:
            model_type: e.g. "cable_models", "connector_models"
            model_id: e.g. "coax_spi_sci_40awg"

        Returns:
            Dict of model fields if found, None if not available.
        """
        ...


class BaseWikiPublisher(ABC):
    """Interface for publishing payloads to the wiki (Milestone 6+)."""

    @abstractmethod
    def publish(self, payload_dir: Path) -> None: ...
