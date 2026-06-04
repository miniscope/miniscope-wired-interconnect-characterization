"""Tests for session validation."""

from pathlib import Path

import pytest

from src.core.loading import load_session
from src.core.session_validator import (
    ValidationResult,
    parse_session_path,
    validate_resistance_csv,
    validate_session,
)
from src.measurement_types.loader import load_definition

RESISTANCE_DEFINITION = Path("measurement_types/resistance/v1/definition.yaml")


class TestValidationResult:
    def test_empty_is_valid(self):
        result = ValidationResult()
        assert result.is_valid

    def test_with_errors_not_valid(self):
        result = ValidationResult()
        result.add_error("something wrong")
        assert not result.is_valid

    def test_warnings_still_valid(self):
        result = ValidationResult()
        result.add_warning("heads up")
        assert result.is_valid

    def test_add_error(self):
        result = ValidationResult()
        result.add_error("err1")
        result.add_error("err2")
        assert len(result.errors) == 2

    def test_add_warning(self):
        result = ValidationResult()
        result.add_warning("warn1")
        assert len(result.warnings) == 1


class TestParseSessionPath:
    def test_parse_valid(self, resistance_session_dir: Path):
        info = parse_session_path(resistance_session_dir)
        assert info.profile_id == "test_cable"
        assert info.cable_length_mm == 500.0
        assert info.measurement_type == "resistance"
        assert info.session_id == "20250115_01"

    def test_parse_bad_length_dir(self, tmp_path: Path):
        session_dir = tmp_path / "profile" / "notalength" / "resistance" / "20250101_01"
        session_dir.mkdir(parents=True)
        with pytest.raises(ValueError):
            parse_session_path(session_dir)


class TestValidateResistanceCsv:
    def test_valid_csv(self, resistance_session_dir: Path):
        result = ValidationResult()
        validate_resistance_csv(resistance_session_dir / "resistance.csv", result)
        assert result.is_valid

    def test_missing_resistance_column(self, bad_measurements_fixtures_dir: Path):
        csv_path = (
            bad_measurements_fixtures_dir
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250117_01"
            / "resistance.csv"
        )
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert not result.is_valid
        assert any("resistance_ohm" in e for e in result.errors)

    def test_length_column_rejected(self, bad_measurements_fixtures_dir: Path):
        csv_path = (
            bad_measurements_fixtures_dir
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250117_01"
            / "resistance.csv"
        )
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert any("cable_length_mm" in e for e in result.errors)

    def test_negative_and_nonnumeric_values(self, bad_measurements_fixtures_dir: Path):
        csv_path = (
            bad_measurements_fixtures_dir
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250118_01"
            / "resistance.csv"
        )
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert not result.is_valid
        assert len(result.errors) >= 3

    def test_minimal_valid_csv(self, measurements_fixtures_dir: Path):
        csv_path = (
            measurements_fixtures_dir
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250116_01"
            / "resistance.csv"
        )
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert result.is_valid

    def test_nonexistent_csv(self, tmp_path: Path):
        result = ValidationResult()
        validate_resistance_csv(tmp_path / "nope.csv", result)
        assert not result.is_valid

    def test_empty_csv(self, tmp_path: Path):
        csv_path = tmp_path / "resistance.csv"
        csv_path.write_text("resistance_ohm\n")
        result = ValidationResult()
        validate_resistance_csv(csv_path, result)
        assert result.is_valid
        assert any("no data rows" in w for w in result.warnings)


class TestValidateSession:
    @pytest.fixture
    def definition(self):
        return load_definition(RESISTANCE_DEFINITION)

    def test_valid_session(
        self,
        resistance_session_dir: Path,
        fixture_models_dir: Path,
        fixture_profiles_dir: Path,
        definition,
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        result = validate_session(
            resistance_session_dir,
            session,
            definition,
            models_dir=fixture_models_dir,
            profiles_dir=fixture_profiles_dir,
        )
        assert result.is_valid, result.errors

    def test_missing_required_file(
        self, bad_measurements_fixtures_dir: Path, fixture_profiles_dir: Path, definition
    ):
        session_dir = (
            bad_measurements_fixtures_dir / "test_cable" / "500mm" / "resistance" / "20250119_01"
        )
        session = load_session(session_dir / "session.yaml")
        result = validate_session(
            session_dir, session, definition, profiles_dir=fixture_profiles_dir
        )
        assert not result.is_valid
        assert any("resistance.csv" in e for e in result.errors)

    def test_path_length_mismatch(
        self, bad_measurements_fixtures_dir: Path, fixture_profiles_dir: Path, definition
    ):
        session_dir = (
            bad_measurements_fixtures_dir / "test_cable" / "500mm" / "resistance" / "20250120_01"
        )
        session = load_session(session_dir / "session.yaml")
        result = validate_session(
            session_dir, session, definition, profiles_dir=fixture_profiles_dir
        )
        assert not result.is_valid
        assert any("cable_length_mm mismatch" in e for e in result.errors)

    def test_missing_profile_is_error(
        self, resistance_session_dir: Path, tmp_path: Path, definition
    ):
        session = load_session(resistance_session_dir / "session.yaml")
        empty_profiles = tmp_path / "profiles"
        empty_profiles.mkdir()
        result = validate_session(
            resistance_session_dir, session, definition, profiles_dir=empty_profiles
        )
        assert not result.is_valid
        assert any("Cable profile" in e for e in result.errors)

    @pytest.fixture
    def model_ref_definition(self):
        """Fixture definition carrying a required miniscope_models model_ref."""
        return load_definition(Path("tests/fixtures/definitions/valid_full.yaml"))

    @pytest.fixture
    def model_ref_session(self, resistance_session_dir: Path):
        """The fixture session, with a miniscope reference injected."""
        session = load_session(resistance_session_dir / "session.yaml")
        return session.model_copy(
            update={"type_fields": {"miniscope_model": "test_miniscope", "method": "method_a"}}
        )

    def test_model_ref_resolves(
        self,
        resistance_session_dir: Path,
        fixture_models_dir: Path,
        model_ref_definition,
        model_ref_session,
    ):
        result = validate_session(
            resistance_session_dir,
            model_ref_session,
            model_ref_definition,
            models_dir=fixture_models_dir,
        )
        assert not any("Model reference" in w for w in result.warnings)

    def test_model_ref_missing_warns(
        self,
        resistance_session_dir: Path,
        tmp_path: Path,
        model_ref_definition,
        model_ref_session,
    ):
        empty_models = tmp_path / "models"
        (empty_models / "miniscope_models").mkdir(parents=True)
        result = validate_session(
            resistance_session_dir,
            model_ref_session,
            model_ref_definition,
            models_dir=empty_models,
        )
        assert any("Model reference" in w for w in result.warnings)
