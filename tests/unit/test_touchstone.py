"""Tests for the Touchstone .s2p parser."""

from pathlib import Path

import numpy as np
import pytest

from src.processing.touchstone import TouchstoneData, parse_s2p


class TestParseS2p:
    def test_parse_valid_fixture(self, vna_fixtures_dir: Path):
        s2p_path = vna_fixtures_dir / "valid_experiment" / "raw" / "cable_500mm.s2p"
        ts = parse_s2p(s2p_path)

        assert isinstance(ts, TouchstoneData)
        assert ts.num_points == 101
        assert ts.format_type == "DB"
        assert ts.ref_impedance == 50.0
        assert len(ts.frequencies_hz) == 101
        assert len(ts.s21_db) == 101
        assert len(ts.s11_db) == 101

    def test_frequencies_in_hz(self, vna_fixtures_dir: Path):
        s2p_path = vna_fixtures_dir / "valid_experiment" / "raw" / "cable_500mm.s2p"
        ts = parse_s2p(s2p_path)

        assert ts.frequency_start_hz == pytest.approx(1e6, rel=0.01)
        assert ts.frequency_stop_hz == pytest.approx(1e9, rel=0.01)

    def test_s21_values_negative(self, vna_fixtures_dir: Path):
        """Insertion loss should be negative dB values."""
        s2p_path = vna_fixtures_dir / "valid_experiment" / "raw" / "cable_500mm.s2p"
        ts = parse_s2p(s2p_path)
        assert np.all(ts.s21_db <= 0)

    def test_parse_db_format(self, tmp_path: Path):
        s2p = tmp_path / "test.s2p"
        s2p.write_text(
            "! Test\n"
            "# MHZ S DB R 50\n"
            "100.0  -10.0 0.0  -3.0 -90.0  -3.0 -90.0  -10.0 0.0\n"
            "200.0  -12.0 0.0  -5.0 -90.0  -5.0 -90.0  -12.0 0.0\n"
        )
        ts = parse_s2p(s2p)
        assert ts.num_points == 2
        assert ts.frequencies_hz[0] == pytest.approx(100e6)
        assert ts.frequencies_hz[1] == pytest.approx(200e6)
        assert ts.s21_db[0] == pytest.approx(-3.0)
        assert ts.s11_db[0] == pytest.approx(-10.0)

    def test_parse_ma_format(self, tmp_path: Path):
        s2p = tmp_path / "test_ma.s2p"
        s2p.write_text("# GHZ S MA R 50\n" "1.0  0.1 0.0  0.5 -90.0  0.5 -90.0  0.1 0.0\n")
        ts = parse_s2p(s2p)
        assert ts.frequencies_hz[0] == pytest.approx(1e9)
        # MA: magnitude 0.5 -> 20*log10(0.5) = -6.02 dB
        assert ts.s21_db[0] == pytest.approx(-6.0206, abs=0.01)

    def test_parse_ri_format(self, tmp_path: Path):
        s2p = tmp_path / "test_ri.s2p"
        s2p.write_text("# HZ S RI R 50\n" "1000000  0.0 0.1  0.5 0.0  0.5 0.0  0.0 0.1\n")
        ts = parse_s2p(s2p)
        assert ts.frequencies_hz[0] == pytest.approx(1e6)
        # RI: real=0.5, imag=0.0 -> magnitude=0.5 -> -6.02 dB
        assert ts.s21_db[0] == pytest.approx(-6.0206, abs=0.01)

    def test_no_data_raises(self, tmp_path: Path):
        s2p = tmp_path / "empty.s2p"
        s2p.write_text("! Comment only\n# GHZ S DB R 50\n")
        with pytest.raises(ValueError, match="No data"):
            parse_s2p(s2p)

    def test_insufficient_columns_raises(self, tmp_path: Path):
        s2p = tmp_path / "short.s2p"
        s2p.write_text("# GHZ S DB R 50\n1.0 -10.0 0.0 -3.0\n")
        with pytest.raises(ValueError, match="at least 9 columns"):
            parse_s2p(s2p)

    def test_comments_captured(self, vna_fixtures_dir: Path):
        s2p_path = vna_fixtures_dir / "valid_experiment" / "raw" / "cable_500mm.s2p"
        ts = parse_s2p(s2p_path)
        assert "comments" in ts.metadata
        assert len(ts.metadata["comments"]) > 0
