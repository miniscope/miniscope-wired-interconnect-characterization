"""Tests for eye diagram validation."""

from pathlib import Path

import numpy as np

from src.core.experiment_validator import (
    ValidationResult,
    validate_eye_manifest_csv,
    validate_npz_file,
)


class TestValidateEyeManifestCsv:
    def test_valid_manifest(self, eye_fixtures_dir: Path):
        csv_path = eye_fixtures_dir / "valid_experiment" / "manifest.csv"
        exp_dir = eye_fixtures_dir / "valid_experiment"
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result, experiment_dir=exp_dir)
        assert result.is_valid

    def test_missing_columns(self, eye_fixtures_dir: Path):
        csv_path = eye_fixtures_dir / "bad_manifest_columns" / "manifest.csv"
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result)
        assert not result.is_valid
        assert any("filename" in e for e in result.errors)

    def test_missing_npz_reference(self, eye_fixtures_dir: Path):
        csv_path = eye_fixtures_dir / "missing_npz" / "manifest.csv"
        exp_dir = eye_fixtures_dir / "missing_npz"
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result, experiment_dir=exp_dir)
        assert not result.is_valid
        assert any("not found" in e for e in result.errors)

    def test_valid_minimal(self, eye_fixtures_dir: Path):
        csv_path = eye_fixtures_dir / "valid_minimal" / "manifest.csv"
        exp_dir = eye_fixtures_dir / "valid_minimal"
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result, experiment_dir=exp_dir)
        assert result.is_valid

    def test_nonexistent_csv(self, tmp_path: Path):
        result = ValidationResult()
        validate_eye_manifest_csv(tmp_path / "nope.csv", result)
        assert not result.is_valid

    def test_empty_csv(self, tmp_path: Path):
        csv_path = tmp_path / "manifest.csv"
        csv_path.write_text("filename,cable_length_mm,data_rate_mbps\n")
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result)
        assert result.is_valid
        assert any("no data rows" in w for w in result.warnings)

    def test_negative_cable_length(self, tmp_path: Path):
        csv_path = tmp_path / "manifest.csv"
        csv_path.write_text("filename,cable_length_mm,data_rate_mbps\ntest.npz,-100,10\n")
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result)
        assert not result.is_valid
        assert any("cable_length_mm" in e for e in result.errors)

    def test_negative_data_rate(self, tmp_path: Path):
        csv_path = tmp_path / "manifest.csv"
        csv_path.write_text("filename,cable_length_mm,data_rate_mbps\ntest.npz,1000,-5\n")
        result = ValidationResult()
        validate_eye_manifest_csv(csv_path, result)
        assert not result.is_valid
        assert any("data_rate_mbps" in e for e in result.errors)


class TestValidateNpzFile:
    def test_valid_npz(self, eye_fixtures_dir: Path):
        npz_path = eye_fixtures_dir / "valid_experiment" / "raw" / "eye_1000mm_10mbps.npz"
        result = ValidationResult()
        validate_npz_file(npz_path, result)
        assert result.is_valid

    def test_bad_shape(self, eye_fixtures_dir: Path):
        npz_path = eye_fixtures_dir / "bad_npz_shape" / "raw" / "bad_eye.npz"
        result = ValidationResult()
        validate_npz_file(npz_path, result)
        assert not result.is_valid
        assert any("3D" in e for e in result.errors)

    def test_missing_eye_key(self, tmp_path: Path):
        npz_path = tmp_path / "no_eye.npz"
        np.savez(npz_path, other=np.zeros((10, 10, 2)))
        result = ValidationResult()
        validate_npz_file(npz_path, result)
        assert not result.is_valid
        assert any("missing" in e for e in result.errors)

    def test_wrong_phase_dim(self, tmp_path: Path):
        npz_path = tmp_path / "wrong_phase.npz"
        np.savez(npz_path, eye=np.zeros((64, 64, 3)))
        result = ValidationResult()
        validate_npz_file(npz_path, result)
        assert not result.is_valid
        assert any("phase dimension must be 2" in e for e in result.errors)

    def test_nonexistent_file(self, tmp_path: Path):
        result = ValidationResult()
        validate_npz_file(tmp_path / "nope.npz", result)
        assert not result.is_valid

    def test_valid_with_ranges(self, eye_fixtures_dir: Path):
        """Valid npz with voltage_range and time_range should pass."""
        npz_path = eye_fixtures_dir / "valid_experiment" / "raw" / "eye_1000mm_10mbps.npz"
        data = np.load(npz_path)
        assert "voltage_range" in data
        assert "time_range" in data
        result = ValidationResult()
        validate_npz_file(npz_path, result)
        assert result.is_valid
