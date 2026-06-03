"""
Per-profile round-trip resistivity from resistance measurements across lengths.

The resistance protocol measures round-trip loop resistance (one cable end
shorted), so resistance grows linearly with length:

    R(L) = rho * L + R0

where rho is the round-trip resistivity (ohm/m, center conductor + shield
return combined) and R0 captures length-independent contributions such as
connector contact resistance. With measurements at two or more lengths we
fit both; with a single length we can only report R/L (which then includes
any connector resistance).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ResistivityFit:
    """Result of fitting resistance vs length for one profile."""

    roundtrip_resistivity_ohm_per_m: float
    intercept_ohm: float | None  # length-independent (e.g. connector) resistance
    r_squared: float | None
    n_lengths: int
    method: str  # "linear_fit" or "single_length_ratio"

    def to_dict(self) -> dict:
        return {
            "roundtrip_resistivity_ohm_per_m": round(self.roundtrip_resistivity_ohm_per_m, 6),
            "intercept_ohm": round(self.intercept_ohm, 6)
            if self.intercept_ohm is not None
            else None,
            "r_squared": round(self.r_squared, 6) if self.r_squared is not None else None,
            "n_lengths": self.n_lengths,
            "method": self.method,
        }


def fit_resistivity(
    lengths_mm: list[float],
    mean_resistance_per_m: list[float],
) -> ResistivityFit | None:
    """
    Fit round-trip resistivity from consolidated per-length data.

    Args:
        lengths_mm: cable lengths with resistance data
        mean_resistance_per_m: pooled roundtrip_resistance_ohm_per_m at each length

    Returns None when there is no data.
    """
    pairs = [
        (length, per_m)
        for length, per_m in zip(lengths_mm, mean_resistance_per_m, strict=True)
        if length is not None and per_m is not None
    ]
    if not pairs:
        return None

    lengths_m = np.array([length / 1000.0 for length, _ in pairs])
    # Reconstruct absolute resistance at each length from the per-meter value
    resistances = np.array([per_m for _, per_m in pairs]) * lengths_m

    if len(pairs) == 1:
        return ResistivityFit(
            roundtrip_resistivity_ohm_per_m=float(resistances[0] / lengths_m[0]),
            intercept_ohm=None,
            r_squared=None,
            n_lengths=1,
            method="single_length_ratio",
        )

    slope, intercept = np.polyfit(lengths_m, resistances, 1)
    predicted = slope * lengths_m + intercept
    ss_res = float(np.sum((resistances - predicted) ** 2))
    ss_tot = float(np.sum((resistances - resistances.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    return ResistivityFit(
        roundtrip_resistivity_ohm_per_m=float(slope),
        intercept_ohm=float(intercept),
        r_squared=r_squared,
        n_lengths=len(pairs),
        method="linear_fit",
    )
