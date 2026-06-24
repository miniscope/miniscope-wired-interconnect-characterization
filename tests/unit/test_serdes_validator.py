"""Tests for SerDes session validation."""

from pathlib import Path

import pytest

from src.core.session_validator import (
    ValidationResult,
    validate_eye_csv,
    validate_margin_csv,
    validate_serdes_session,
)


@pytest.fixture
def serdes_session_dir(measurements_fixtures_dir: Path) -> Path:
    return measurements_fixtures_dir / "test_cable" / "500mm" / "serdes" / "20250401_01"


@pytest.fixture
def bad_serdes_dir(bad_measurements_fixtures_dir: Path) -> Path:
    return bad_measurements_fixtures_dir / "test_cable" / "500mm" / "serdes"


class TestValidateSerdesSession:
    def test_valid_session(self, serdes_session_dir: Path):
        result = ValidationResult()
        validate_serdes_session(serdes_session_dir, result)
        assert result.is_valid, result.errors

    def test_missing_lane(self, bad_serdes_dir: Path):
        """The bad fixture has the two forward lanes but no reverse channel."""
        result = ValidationResult()
        validate_serdes_session(bad_serdes_dir / "20250403_01", result)
        assert not result.is_valid
        assert any("reverse channel" in e and "rev_187m" in e for e in result.errors)

    def test_bad_eye_columns(self, bad_serdes_dir: Path):
        result = ValidationResult()
        validate_serdes_session(bad_serdes_dir / "20250404_01", result)
        assert not result.is_valid
        assert any("errors" in e for e in result.errors)

    def test_bad_margin_columns(self, bad_serdes_dir: Path):
        result = ValidationResult()
        validate_serdes_session(bad_serdes_dir / "20250405_01", result)
        assert not result.is_valid
        assert any("tx_amp_mv" in e for e in result.errors)

    def test_missing_manifest(self, tmp_path: Path):
        result = ValidationResult()
        validate_serdes_session(tmp_path, result)
        assert not result.is_valid


class TestValidateEyeCsv:
    def test_valid(self, serdes_session_dir: Path):
        result = ValidationResult()
        validate_eye_csv(serdes_session_dir / "eye_fwd_3g.csv", result)
        assert result.is_valid, result.errors

    def test_out_of_range_phase(self, tmp_path: Path):
        path = tmp_path / "eye.csv"
        path.write_text("phase,vth,polarity,hits,errors\n200,0,0,32768,0\n")
        result = ValidationResult()
        validate_eye_csv(path, result)
        assert not result.is_valid
        assert any("phase" in e for e in result.errors)

    def test_missing_column(self, tmp_path: Path):
        path = tmp_path / "eye.csv"
        path.write_text("phase,vth,polarity,hits\n0,0,0,32768\n")
        result = ValidationResult()
        validate_eye_csv(path, result)
        assert not result.is_valid


class TestValidateMarginCsv:
    def test_valid(self, serdes_session_dir: Path):
        result = ValidationResult()
        validate_margin_csv(serdes_session_dir / "margin_fwd_3g.csv", result)
        assert result.is_valid, result.errors

    def test_negative_amplitude(self, tmp_path: Path):
        csv_path = tmp_path / "margin.csv"
        csv_path.write_text("tx_amp_mv,code,rep,locked,errors,status\n-10,0,0,1,0,ok\n")
        result = ValidationResult()
        validate_margin_csv(csv_path, result)
        assert not result.is_valid

    def test_lost_lock_allowed(self, tmp_path: Path):
        # errors == -1 (lock lost) is a valid raw value, not a validation error.
        csv_path = tmp_path / "margin.csv"
        csv_path.write_text("tx_amp_mv,code,rep,locked,errors,status\n100,10,0,0,-1,lost_lock\n")
        result = ValidationResult()
        validate_margin_csv(csv_path, result)
        assert result.is_valid, result.errors

    def test_missing_column(self, tmp_path: Path):
        csv_path = tmp_path / "margin.csv"
        csv_path.write_text("amplitude,errors\n100,0\n")
        result = ValidationResult()
        validate_margin_csv(csv_path, result)
        assert not result.is_valid
