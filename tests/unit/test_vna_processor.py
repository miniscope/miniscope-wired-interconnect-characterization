"""Tests for ProcessVNA processor."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.core.loading import load_session
from src.measurement_types.loader import load_definition
from src.processing.touchstone import TouchstoneData
from src.processing.vna import (
    ProcessVNA,
    characteristic_impedance,
    estimate_characteristic_impedance,
    sparams_to_abcd,
    summarize_characteristic_impedance,
)


def _line_sparams(z0: float, ref: float, n: int = 101):
    """Complex S-parameters of an ideal lossless line of impedance z0 in a `ref` system.

    Reciprocal (S12 == S21), so it exercises both the ABCD determinant identity
    and the Z0 = sqrt(B/C) recovery.
    """
    freqs = np.linspace(1e6, 1e9, n)
    theta = 2 * np.pi * freqs / freqs[-1]  # arbitrary electrical-length sweep
    gamma = (z0 - ref) / (z0 + ref)
    s11 = gamma * (1 - np.exp(-2j * theta)) / (1 - gamma**2 * np.exp(-2j * theta))
    s21 = (1 - gamma**2) * np.exp(-1j * theta) / (1 - gamma**2 * np.exp(-2j * theta))
    return freqs, s11, s21


class TestProcessVNA:
    @pytest.fixture
    def processor(self, fixture_models_dir: Path) -> ProcessVNA:
        return ProcessVNA(models_dir=fixture_models_dir)

    @pytest.fixture
    def definition(self):
        return load_definition(Path("measurement_types/vna/v1/definition.yaml"))

    def test_process_valid(self, processor, definition, vna_session_dir: Path, tmp_path: Path):
        session = load_session(vna_session_dir / "session.yaml")
        output_dir = tmp_path / "output"

        outputs = processor.process(vna_session_dir, session, definition, output_dir)

        assert "vna_metrics_csv" in outputs
        assert "vna_traces_csv" in outputs
        assert "vna_summary_json" in outputs
        assert outputs["vna_metrics_csv"].exists()
        assert outputs["vna_traces_csv"].exists()
        assert outputs["vna_summary_json"].exists()

    def test_metrics_csv_columns(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        assert "filename" in df.columns
        assert "max_insertion_loss_db" in df.columns
        assert "characteristic_impedance_ohm" in df.columns
        assert "num_points" in df.columns
        assert len(df) == 2  # 2 .s2p files

    def test_traces_csv_has_all_points(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_traces_csv"])
        assert "frequency_hz" in df.columns
        assert "s21_db" in df.columns
        assert "s11_db" in df.columns
        assert "attenuation_db" in df.columns
        # 2 files * 101 points each = 202
        assert len(df) == 202

    def test_attenuation_is_negated_s21(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_traces_csv"])
        assert (df["attenuation_db"] == -df["s21_db"]).all()

    def test_insertion_loss_at_frequencies(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        has_il_cols = [
            c for c in df.columns if c.startswith("insertion_loss_") and c.endswith("_db")
        ]
        assert len(has_il_cols) > 0

    def test_summary_json(self, processor, definition, vna_session_dir: Path, tmp_path: Path):
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        with open(outputs["vna_summary_json"]) as f:
            summary = json.load(f)

        assert summary["session_id"] == "20250301_01"
        assert summary["profile_id"] == "test_cable"
        assert summary["cable_length_mm"] == 1000.0
        assert summary["num_files"] == 2
        assert "mean_max_insertion_loss_db" in summary
        assert summary["vna_instrument"] == "Test VNA"

    def test_summary_attenuation_by_frequency(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        """Summary carries attenuation at the reference frequencies the sweep covered."""
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        with open(outputs["vna_summary_json"]) as f:
            summary = json.load(f)

        att = summary["attenuation_db_by_hz"]
        # Fixture sweeps 1 MHz - 1 GHz: 750 MHz (FPD-Link III Nyquist) is
        # covered, the GMSL2 Nyquist points (1.5/3 GHz) are not.
        assert "750000000" in att
        assert "3000000000" not in att
        assert all(v > 0 for v in att.values())  # attenuation is positive dB
        # More attenuation at higher frequency (coax loss grows with f)
        assert att["750000000"] > att["1000000"]

    def test_minimal_session(
        self, processor, definition, measurements_fixtures_dir: Path, tmp_path: Path
    ):
        session_dir = measurements_fixtures_dir / "test_cable" / "1000mm" / "vna" / "20250302_01"
        session = load_session(session_dir / "session.yaml")
        outputs = processor.process(session_dir, session, definition, tmp_path / "output")

        df = pd.read_csv(outputs["vna_metrics_csv"])
        assert len(df) == 1

    def test_impedance_populated(
        self, processor, definition, vna_session_dir: Path, tmp_path: Path
    ):
        """Characteristic impedance is now computed (no longer a None stub)."""
        session = load_session(vna_session_dir / "session.yaml")
        outputs = processor.process(vna_session_dir, session, definition, tmp_path / "output")

        metrics = pd.read_csv(outputs["vna_metrics_csv"])
        z = metrics["characteristic_impedance_ohm"].dropna()
        assert len(z) > 0
        assert (z > 0).all()  # physical impedance is positive

        traces = pd.read_csv(outputs["vna_traces_csv"])
        assert "impedance_ohm" in traces.columns

        with open(outputs["vna_summary_json"]) as f:
            summary = json.load(f)
        assert "mean_characteristic_impedance_ohm" in summary


class TestCharacteristicImpedance:
    def _matched_line(self, z0: float, ref: float, n: int = 101) -> TouchstoneData:
        """Ideal lossless line of impedance z0 referenced to `ref` ohms."""
        freqs, s11, s21 = _line_sparams(z0, ref, n)
        return TouchstoneData(
            frequencies_hz=freqs,
            s11_db=20 * np.log10(np.abs(s11) + 1e-15),
            s21_db=20 * np.log10(np.abs(s21)),
            s12_db=20 * np.log10(np.abs(s21)),
            s22_db=20 * np.log10(np.abs(s11) + 1e-15),
            ref_impedance=ref,
            s11=s11,
            s21=s21,
            s12=s21,
            s22=s11,
        )

    def test_matched_line_recovers_reference(self):
        ts = self._matched_line(z0=50.0, ref=50.0)
        assert estimate_characteristic_impedance(ts) == pytest.approx(50.0, abs=1.0)

    def test_75_ohm_line(self):
        ts = self._matched_line(z0=75.0, ref=50.0)
        assert estimate_characteristic_impedance(ts) == pytest.approx(75.0, rel=0.05)

    def test_none_when_no_complex_data(self):
        ts = TouchstoneData(
            frequencies_hz=np.array([1e6]),
            s11_db=np.array([-10.0]),
            s21_db=np.array([-3.0]),
            s12_db=np.array([-3.0]),
            s22_db=np.array([-10.0]),
        )
        assert estimate_characteristic_impedance(ts) is None


class TestAbcd:
    def test_reciprocal_line_determinant_is_one(self):
        """A reciprocal 2-port (S12 == S21) has ABCD determinant AD - BC = 1."""
        _, s11, s21 = _line_sparams(z0=75.0, ref=50.0)
        abcd = sparams_to_abcd(s11, s21, s21, s11, z_ref=50.0)
        det = abcd.a * abcd.d - abcd.b * abcd.c
        np.testing.assert_allclose(det, 1.0, atol=1e-9)

    def test_characteristic_impedance_recovers_line_z0(self):
        """Z0 = sqrt(B/C) recovers the synthesized line's impedance."""
        _, s11, s21 = _line_sparams(z0=75.0, ref=50.0)
        abcd = sparams_to_abcd(s11, s21, s21, s11, z_ref=50.0)
        z0 = np.real(characteristic_impedance(abcd))
        finite = np.isfinite(z0) & (z0 > 0)
        assert np.median(z0[finite]) == pytest.approx(75.0, rel=0.05)

    def test_matches_legacy_profile(self):
        """The ABCD path agrees with characteristic_impedance_profile end to end."""
        from src.processing.vna import characteristic_impedance_profile

        ts = TestCharacteristicImpedance()._matched_line(z0=75.0, ref=50.0)
        abcd = sparams_to_abcd(ts.s11, ts.s21, ts.s12, ts.s22, z_ref=ts.ref_impedance)
        np.testing.assert_allclose(
            characteristic_impedance(abcd), characteristic_impedance_profile(ts), equal_nan=True
        )


class TestSummarizeCharacteristicImpedance:
    def test_recovers_line_z0(self):
        _, s11, s21 = _line_sparams(z0=75.0, ref=50.0)
        z0 = np.real(characteristic_impedance(sparams_to_abcd(s11, s21, s21, s11, z_ref=50.0)))
        assert summarize_characteristic_impedance(z0) == pytest.approx(75.0, rel=0.05)

    def test_ignores_nonfinite_and_nonpositive(self):
        z0 = np.array([np.nan, -3.0, 50.0, 50.0, np.inf, 50.0])
        assert summarize_characteristic_impedance(z0) == pytest.approx(50.0)

    def test_none_when_no_usable_points(self):
        assert summarize_characteristic_impedance(np.array([np.nan, -1.0, 0.0])) is None
