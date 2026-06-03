"""Tests for session/profile/model loading utilities."""

from pathlib import Path

import pytest

from src.core.loading import load_model, load_session
from src.core.model_schemas import MiniscopeModel
from src.core.session_schemas import SessionRecord


class TestLoadSession:
    def test_load_valid(self, valid_session_path: Path):
        record = load_session(valid_session_path)
        assert isinstance(record, SessionRecord)
        assert record.session_id == "20250101_01"

    def test_load_nonexistent(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_session(tmp_path / "nope.yaml")


class TestLoadModel:
    def test_load_miniscope_inferred_type(self, fixture_models_dir: Path):
        path = fixture_models_dir / "miniscope_models" / "test_miniscope.yaml"
        model = load_model(path)
        assert isinstance(model, MiniscopeModel)
        assert model.min_operating_voltage_v == 3.3

    def test_power_profiles_no_longer_supported(self, valid_cable_path: Path):
        with pytest.raises(ValueError, match="Unknown model type"):
            load_model(valid_cable_path, model_type="power_profiles")
