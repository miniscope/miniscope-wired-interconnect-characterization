from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseWikiPublisher(ABC):
    """Interface for publishing a rendered wiki bundle to the wiki."""

    @abstractmethod
    def publish(self, payload_dir: Path) -> None: ...
