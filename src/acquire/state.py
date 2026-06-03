"""Process-wide state for the acquisition app (single-user lab tool)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AcquireState:
    repo_root: Path = Path(".")
    operator: str = ""
    # None -> registry decides (simulator unless MINISCOPE_ACQUIRE_HARDWARE=1)
    simulate: bool | None = None


STATE = AcquireState()
