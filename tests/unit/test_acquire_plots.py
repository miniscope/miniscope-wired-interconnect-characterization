"""Tests for acquisition preview plot rendering (headless)."""

from src.acquire.plots import render_attenuation, render_eye, render_margin
from src.instruments.registry import get_serdes_driver, get_vna_driver
from src.instruments.serdes.driver import SerdesConfig
from src.instruments.types import FORWARD_3G, REVERSE_187M
from src.instruments.vna.driver import VnaConfig

PNG_MAGIC = b"\x89PNG"


class TestPlots:
    def test_render_eye(self):
        driver = get_serdes_driver(simulate=True)
        eye = driver.capture_eye(FORWARD_3G, SerdesConfig(eye_bins=16))
        png = render_eye(eye)
        assert png.startswith(PNG_MAGIC)
        assert len(png) > 1000

    def test_render_margin(self):
        driver = get_serdes_driver(simulate=True)
        sweep = driver.sweep_margin(REVERSE_187M, SerdesConfig())
        png = render_margin(sweep)
        assert png.startswith(PNG_MAGIC)

    def test_render_attenuation(self):
        result = get_vna_driver(simulate=True).sweep(VnaConfig(num_points=21))
        png = render_attenuation(result)
        assert png.startswith(PNG_MAGIC)
