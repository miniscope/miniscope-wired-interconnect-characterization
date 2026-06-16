"""Tests for weight CSV validation."""

from pathlib import Path

from src.core.session_validator import ValidationResult, validate_weight_csv

HEADER = "assembly_weight_g,fixture_weight_g,notes"


def write_csv(tmp_path: Path, body: str) -> Path:
    csv_path = tmp_path / "weight.csv"
    csv_path.write_text(body)
    return csv_path


class TestValidateWeightCsv:
    def test_valid_csv(self, tmp_path: Path):
        csv_path = write_csv(tmp_path, f"{HEADER}\n12.0,4.0,a\n12.1,4.0,b\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert result.is_valid, result.errors

    def test_missing_required_column(self, tmp_path: Path):
        csv_path = write_csv(tmp_path, "assembly_weight_g,notes\n12.0,a\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert not result.is_valid
        assert any("fixture_weight_g" in e for e in result.errors)

    def test_length_column_rejected(self, tmp_path: Path):
        csv_path = write_csv(tmp_path, f"{HEADER},cable_length_mm\n12.0,4.0,a,500\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert not result.is_valid
        assert any("cable_length_mm" in e for e in result.errors)

    def test_non_numeric_and_negative(self, tmp_path: Path):
        csv_path = write_csv(tmp_path, f"{HEADER}\nabc,4.0,a\n12.0,-1.0,b\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert not result.is_valid
        assert len(result.errors) >= 2

    def test_assembly_must_exceed_fixture(self, tmp_path: Path):
        csv_path = write_csv(tmp_path, f"{HEADER}\n4.0,12.0,inverted\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert not result.is_valid
        assert any("must exceed" in e for e in result.errors)

    def test_zero_fixture_is_allowed(self, tmp_path: Path):
        """A bare cable with no fixture (fixture = 0) is valid."""
        csv_path = write_csv(tmp_path, f"{HEADER}\n8.0,0.0,bare\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert result.is_valid, result.errors

    def test_empty_csv_warns(self, tmp_path: Path):
        csv_path = write_csv(tmp_path, f"{HEADER}\n")
        result = ValidationResult()
        validate_weight_csv(csv_path, result)
        assert result.is_valid
        assert any("no data rows" in w for w in result.warnings)

    def test_nonexistent_csv(self, tmp_path: Path):
        result = ValidationResult()
        validate_weight_csv(tmp_path / "nope.csv", result)
        assert not result.is_valid
