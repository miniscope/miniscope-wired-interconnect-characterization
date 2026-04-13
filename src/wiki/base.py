from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseWikiPublisher(ABC):
    """Stub interface for wiki integration (Milestone 5+)."""

    @abstractmethod
    def publish(self, payload_dir: Path) -> None: ...
