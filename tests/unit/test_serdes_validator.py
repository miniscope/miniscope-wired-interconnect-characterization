"""Tests for SerDes session validation."""

from pathlib import Path

import numpy as np
import pytest

from src.core.session_validator import (
    ValidationResult,
    validate_margin_csv,
    validate_serdes_npz,
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

    def test_missing_combo(self, bad_serdes_dir: Path):
        result = ValidationResult()
        validate_serdes_session(bad_serdes_dir / "20250403_01", result)
        assert not result.is_valid
        assert any("missing combo" in e for e in result.errors)
        assert any("back, 6" in e for e in result.errors)

    def test_bad_npz_keys(self, bad_serdes_dir: Path):
        result = ValidationResult()
        validate_serdes_session(bad_serdes_dir / "20250404_01", result)
        assert not result.is_valid
        assert any("voltage_range_mv" in e for e in result.errors)

    def test_bad_margin_columns(self, bad_serdes_dir: Path):
        result = ValidationResult()
        validate_serdes_session(bad_serdes_dir / "20250405_01", result)
        assert not result.is_valid
        assert any("tx_amplitude_mv" in e for e in result.errors)

    def test_missing_manifest(self, tmp_path: Path):
        result = ValidationResult()
        validate_serdes_session(tmp_path, result)
        assert not result.is_valid


class TestValidateSerdesNpz:
    def test_valid(self, serdes_session_dir: Path):
        result = ValidationResult()
        validate_serdes_npz(serdes_session_dir / "eye_forward_3g.npz", result)
        assert result.is_valid

    def test_wrong_ndim(self, tmp_path: Path):
        path = tmp_path / "bad.npz"
        np.savez(
            path,
            error_counts=np.zeros(8, dtype=np.int64),
            voltage_range_mv=np.array([-1.0, 1.0]),
            time_range_ps=np.array([0.0, 1.0]),
        )
        result = ValidationResult()
        validate_serdes_npz(path, result)
        assert not result.is_valid
        assert any("2D" in e for e in result.errors)

    def test_bad_range_shape(self, tmp_path: Path):
        path = tmp_path / "bad.npz"
        np.savez(
            path,
            error_counts=np.zeros((8, 8), dtype=np.int64),
            voltage_range_mv=np.array([1.0]),
            time_range_ps=np.array([0.0, 1.0]),
        )
        result = ValidationResult()
        validate_serdes_npz(path, result)
        assert not result.is_valid
        assert any("shape (2,)" in e for e in result.errors)


class TestValidateMarginCsv:
    def test_valid(self, serdes_session_dir: Path):
        result = ValidationResult()
        validate_margin_csv(serdes_session_dir / "margin_forward_3g.csv", result)
        assert result.is_valid

    def test_negative_amplitude(self, tmp_path: Path):
        csv_path = tmp_path / "margin.csv"
        csv_path.write_text("tx_amplitude_mv,error_count\n-10,0\n")
        result = ValidationResult()
        validate_margin_csv(csv_path, result)
        assert not result.is_valid

    def test_negative_error_count(self, tmp_path: Path):
        csv_path = tmp_path / "margin.csv"
        csv_path.write_text("tx_amplitude_mv,error_count\n100,-1\n")
        result = ValidationResult()
        validate_margin_csv(csv_path, result)
        assert not result.is_valid

    def test_empty_rows_warn(self, tmp_path: Path):
        csv_path = tmp_path / "margin.csv"
        csv_path.write_text("tx_amplitude_mv,error_count\n")
        result = ValidationResult()
        validate_margin_csv(csv_path, result)
        assert result.is_valid
        assert any("no data rows" in w for w in result.warnings)
