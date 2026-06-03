"""
Resistance entry helpers.

The resistance measurement is manual (LCR meter, one cable end shorted,
operator types the round-trip loop resistance into the app), so there is
no automated driver -- just the reading dataclass and the same sanity
rules the pipeline validator applies, so bad values are caught at entry
time instead of at PR time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResistanceReading:
    """One manually-entered round-trip loop resistance value."""

    resistance_ohm: float
    note: str = ""


def validate_reading(value_ohm: float) -> None:
    """
    Raise ValueError for implausible entries. Mirrors
    src.core.session_validator.validate_resistance_csv rules.
    """
    if not isinstance(value_ohm, int | float):
        raise ValueError(f"Resistance must be a number, got {type(value_ohm).__name__}")
    if value_ohm != value_ohm:  # NaN
        raise ValueError("Resistance must not be NaN")
    if value_ohm <= 0:
        raise ValueError(f"Resistance must be positive, got {value_ohm}")
    if value_ohm > 10_000:
        raise ValueError(
            f"Resistance {value_ohm} ohm is implausibly large for a coax loop -- "
            "check that the far end is shorted"
        )
