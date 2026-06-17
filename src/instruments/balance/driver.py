"""
Mass entry helpers.

The mass measurement is manual (a balance, operator weighs the cable
assembly and the bare PCB+SMA fixture, then types both masses into the
app), so there is no automated driver -- just the reading dataclass and the
same sanity rules the pipeline validator applies, so bad values are caught
at entry time instead of at PR time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MassReading:
    """One manually-entered weighing: full assembly and bare fixture masses."""

    assembly_mass_g: float
    fixture_mass_g: float
    note: str = ""

    @property
    def cable_mass_g(self) -> float:
        """Net cable mass (assembly minus the non-cable fixture)."""
        return self.assembly_mass_g - self.fixture_mass_g


def validate_reading(assembly_mass_g: float, fixture_mass_g: float) -> None:
    """
    Raise ValueError for implausible entries. Mirrors
    src.core.session_validator.validate_mass_csv rules.
    """
    for label, value in [
        ("assembly_mass_g", assembly_mass_g),
        ("fixture_mass_g", fixture_mass_g),
    ]:
        if not isinstance(value, int | float):
            raise ValueError(f"{label} must be a number, got {type(value).__name__}")
        if value != value:  # NaN
            raise ValueError(f"{label} must not be NaN")
    if assembly_mass_g <= 0:
        raise ValueError(f"assembly_mass_g must be positive, got {assembly_mass_g}")
    if fixture_mass_g < 0:
        raise ValueError(f"fixture_mass_g must be >= 0, got {fixture_mass_g}")
    if assembly_mass_g <= fixture_mass_g:
        raise ValueError(
            f"assembly_mass_g ({assembly_mass_g}) must exceed fixture_mass_g "
            f"({fixture_mass_g}) for a positive net cable mass"
        )
