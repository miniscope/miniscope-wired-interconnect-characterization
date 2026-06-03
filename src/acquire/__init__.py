"""
Acquisition app: the lab-facing entry point for creating measurement data.

Launched via `miniscope-char acquire` (requires the `acquire` Poetry
group: `poetry install --with acquire`). The GUI is a thin layer over
plain controller functions (src/acquire/controllers/) which in turn call
the instrument drivers (src/instruments/) and the session writers
(src/core/session_writer.py) -- so all behavior is testable without a
browser or hardware.
"""
