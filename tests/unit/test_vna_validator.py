"""Tests for VNA manifest and s2p validation."""

from pathlib import Path

from src.core.session_validator import (
    ValidationResult,
    validate_s2p_file,
    validate_vna_manifest_csv,
)


class TestValidateVnaManifestCsv:
    def test_valid_manifest(self, vna_session_dir: Path):
        result = ValidationResult()
        validate_vna_manifest_csv(
            vna_session_dir / "manifest.csv", result, session_dir=vna_session_dir
        )
        assert result.is_valid

    def test_missing_columns(self, bad_measurements_fixtures_dir: Path):
        csv_path = (
            bad_measurements_fixtures_dir
            / "test_cable"
            / "1000mm"
            / "vna"
            / "20250304_01"
            / "manifest.csv"
        )
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result)
        assert not result.is_valid
        assert any("filename" in e for e in result.errors)

    def test_length_column_rejected(self, bad_measurements_fixtures_dir: Path):
        csv_path = (
            bad_measurements_fixtures_dir
            / "test_cable"
            / "1000mm"
            / "vna"
            / "20250304_01"
            / "manifest.csv"
        )
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result)
        assert any("cable_length_mm" in e for e in result.errors)

    def test_missing_s2p_reference(self, bad_measurements_fixtures_dir: Path):
        session_dir = (
            bad_measurements_fixtures_dir / "test_cable" / "1000mm" / "vna" / "20250303_01"
        )
        result = ValidationResult()
        validate_vna_manifest_csv(session_dir / "manifest.csv", result, session_dir=session_dir)
        assert not result.is_valid
        assert any("not found" in e for e in result.errors)

    def test_valid_minimal(self, measurements_fixtures_dir: Path):
        session_dir = measurements_fixtures_dir / "test_cable" / "1000mm" / "vna" / "20250302_01"
        result = ValidationResult()
        validate_vna_manifest_csv(session_dir / "manifest.csv", result, session_dir=session_dir)
        assert result.is_valid

    def test_nonexistent_csv(self, tmp_path: Path):
        result = ValidationResult()
        validate_vna_manifest_csv(tmp_path / "nope.csv", result)
        assert not result.is_valid


class TestValidateS2pFile:
    def test_valid_s2p(self, vna_session_dir: Path):
        result = ValidationResult()
        validate_s2p_file(vna_session_dir / "raw" / "sweep_01.s2p", result)
        assert result.is_valid

    def test_bad_s2p_no_data(self, bad_measurements_fixtures_dir: Path):
        s2p_path = (
            bad_measurements_fixtures_dir
            / "test_cable"
            / "1000mm"
            / "vna"
            / "20250305_01"
            / "raw"
            / "bad_file.s2p"
        )
        result = ValidationResult()
        validate_s2p_file(s2p_path, result)
        assert not result.is_valid
        assert any("no data" in e for e in result.errors)

    def test_nonexistent_file(self, tmp_path: Path):
        result = ValidationResult()
        validate_s2p_file(tmp_path / "nope.s2p", result)
        assert not result.is_valid
