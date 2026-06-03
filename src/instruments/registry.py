"""
Driver selection: simulator by default, real hardware only on request.

Selection precedence (highest first):
1. explicit `simulate=` argument
2. environment variable MINISCOPE_ACQUIRE_HARDWARE=1 -> real drivers
3. default: simulator

Real drivers are imported lazily so the simulator path never requires
hardware libraries to be installed.
"""

from __future__ import annotations

import os

from src.instruments.serdes.driver import SerdesDriver
from src.instruments.serdes.simulator import SimulatedSerdesDriver
from src.instruments.vna.driver import VnaDriver
from src.instruments.vna.simulator import SimulatedVnaDriver

HARDWARE_ENV_VAR = "MINISCOPE_ACQUIRE_HARDWARE"


def _use_hardware(simulate: bool | None) -> bool:
    if simulate is not None:
        return not simulate
    return os.environ.get(HARDWARE_ENV_VAR, "") == "1"


def get_serdes_driver(simulate: bool | None = None, **kwargs) -> SerdesDriver:
    """Return a SerDes driver. kwargs are forwarded to the chosen driver."""
    if _use_hardware(simulate):
        from src.instruments.serdes.real import RealSerdesDriver

        return RealSerdesDriver(**kwargs)
    return SimulatedSerdesDriver(**kwargs)


def get_vna_driver(simulate: bool | None = None, **kwargs) -> VnaDriver:
    """Return a VNA driver. kwargs are forwarded to the chosen driver."""
    if _use_hardware(simulate):
        from src.instruments.vna.real import RealPicoVnaDriver

        return RealPicoVnaDriver(**kwargs)
    return SimulatedVnaDriver(**kwargs)
