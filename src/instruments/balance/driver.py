"""
Weight entry helpers.

The weight measurement is manual (a balance, operator weighs the cable
assembly and the bare PCB+SMA fixture, then types both masses into the
app), so there is no automated driver -- just the reading dataclass and the
same sanity rules the pipeline validator applies, so bad values are caught
at entry time instead of at PR time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WeightReading:
    """One manually-entered weighing: full assembly and bare fixture masses."""

    assembly_weight_g: float
    fixture_weight_g: float
    note: str = ""

    @property
    def cable_weight_g(self) -> float:
        """Net cable mass (assembly minus the non-cable fixture)."""
        return self.assembly_weight_g - self.fixture_weight_g


def validate_reading(assembly_weight_g: float, fixture_weight_g: float) -> None:
    """
    Raise ValueError for implausible entries. Mirrors
    src.core.session_validator.validate_weight_csv rules.
    """
    for label, value in [
        ("assembly_weight_g", assembly_weight_g),
        ("fixture_weight_g", fixture_weight_g),
    ]:
        if not isinstance(value, int | float):
            raise ValueError(f"{label} must be a number, got {type(value).__name__}")
        if value != value:  # NaN
            raise ValueError(f"{label} must not be NaN")
    if assembly_weight_g <= 0:
        raise ValueError(f"assembly_weight_g must be positive, got {assembly_weight_g}")
    if fixture_weight_g < 0:
        raise ValueError(f"fixture_weight_g must be >= 0, got {fixture_weight_g}")
    if assembly_weight_g <= fixture_weight_g:
        raise ValueError(
            f"assembly_weight_g ({assembly_weight_g}) must exceed fixture_weight_g "
            f"({fixture_weight_g}) for a positive net cable mass"
        )
