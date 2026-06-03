"""
Real PicoVNA driver -- PLACEHOLDER.

TODO (deferred until integration on the bench PC):
The PicoVNA ships with a Windows COM/.NET automation API. Implement this
class against it (likely via `pythonnet` or `comtypes`), keeping the
vendor import INSIDE connect() so importing this module never requires the
SDK. Everything else in the codebase only touches VnaSweepResult, so this
is the single Windows-specific file.
"""

from __future__ import annotations

from src.instruments.types import VnaSweepResult
from src.instruments.vna.driver import VnaConfig, VnaDriver


class RealPicoVnaDriver(VnaDriver):
    """PicoVNA hardware driver. Not yet implemented -- see module docstring."""

    def connect(self) -> None:
        raise NotImplementedError("Real PicoVNA driver pending bench integration")

    def is_calibrated(self) -> bool:
        raise NotImplementedError("Real PicoVNA driver pending bench integration")

    def sweep(self, config: VnaConfig) -> VnaSweepResult:
        raise NotImplementedError("Real PicoVNA driver pending bench integration")

    def close(self) -> None:
        pass
