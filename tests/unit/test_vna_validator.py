"""Tests for VNA manifest and s2p validation."""

from pathlib import Path

from src.core.experiment_validator import (
    ValidationResult,
    validate_s2p_file,
    validate_vna_manifest_csv,
)


class TestValidateVnaManifestCsv:
    def test_valid_manifest(self, vna_fixtures_dir: Path):
        csv_path = vna_fixtures_dir / "valid_experiment" / "manifest.csv"
        exp_dir = vna_fixtures_dir / "valid_experiment"
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result, experiment_dir=exp_dir)
        assert result.is_valid

    def test_missing_columns(self, vna_fixtures_dir: Path):
        csv_path = vna_fixtures_dir / "bad_manifest_columns" / "manifest.csv"
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result)
        assert not result.is_valid
        assert any("filename" in e for e in result.errors)

    def test_missing_s2p_reference(self, vna_fixtures_dir: Path):
        csv_path = vna_fixtures_dir / "missing_s2p" / "manifest.csv"
        exp_dir = vna_fixtures_dir / "missing_s2p"
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result, experiment_dir=exp_dir)
        assert not result.is_valid
        assert any("not found" in e for e in result.errors)

    def test_valid_minimal(self, vna_fixtures_dir: Path):
        csv_path = vna_fixtures_dir / "valid_minimal" / "manifest.csv"
        exp_dir = vna_fixtures_dir / "valid_minimal"
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result, experiment_dir=exp_dir)
        assert result.is_valid

    def test_nonexistent_csv(self, tmp_path: Path):
        result = ValidationResult()
        validate_vna_manifest_csv(tmp_path / "nope.csv", result)
        assert not result.is_valid

    def test_negative_cable_length(self, tmp_path: Path):
        csv_path = tmp_path / "manifest.csv"
        csv_path.write_text("filename,cable_length_mm\ntest.s2p,-100\n")
        result = ValidationResult()
        validate_vna_manifest_csv(csv_path, result)
        assert not result.is_valid


class TestValidateS2pFile:
    def test_valid_s2p(self, vna_fixtures_dir: Path):
        s2p_path = vna_fixtures_dir / "valid_experiment" / "raw" / "cable_500mm.s2p"
        result = ValidationResult()
        validate_s2p_file(s2p_path, result)
        assert result.is_valid

    def test_bad_s2p_no_data(self, vna_fixtures_dir: Path):
        s2p_path = vna_fixtures_dir / "bad_s2p_format" / "raw" / "bad_file.s2p"
        result = ValidationResult()
        validate_s2p_file(s2p_path, result)
        assert not result.is_valid
        assert any("no data" in e for e in result.errors)

    def test_nonexistent_file(self, tmp_path: Path):
        result = ValidationResult()
        validate_s2p_file(tmp_path / "nope.s2p", result)
        assert not result.is_valid
