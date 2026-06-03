"""Tests for CableProfile schema and profile loading."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.core.loading import list_profiles, load_profile
from src.core.profile_schemas import CableProfile


def make_profile_kwargs(**overrides) -> dict:
    kwargs = {
        "schema_version": "1.0",
        "profile_id": "test_cable",
        "name": "Test Cable",
    }
    kwargs.update(overrides)
    return kwargs


class TestCableProfile:
    def test_load_valid(self, fixture_profiles_dir: Path):
        with open(fixture_profiles_dir / "test_cable.yaml") as f:
            raw = yaml.safe_load(f)
        profile = CableProfile.model_validate(raw)
        assert profile.profile_id == "test_cable"
        assert profile.characteristic_impedance_ohm == 50.0

    def test_minimal(self):
        profile = CableProfile.model_validate(make_profile_kwargs())
        assert profile.cable_type == "coaxial"
        assert profile.tags == []

    def test_profile_id_pattern(self):
        with pytest.raises(ValidationError):
            CableProfile.model_validate(make_profile_kwargs(profile_id="Bad Name!"))

    def test_name_required(self):
        with pytest.raises(ValidationError):
            CableProfile.model_validate(make_profile_kwargs(name=""))

    def test_impedance_must_be_positive(self):
        with pytest.raises(ValidationError):
            CableProfile.model_validate(make_profile_kwargs(characteristic_impedance_ohm=-50))

    def test_no_measured_values_allowed(self):
        """Profiles are static specs: extra (e.g. measured) fields are rejected."""
        with pytest.raises(ValidationError):
            CableProfile.model_validate(make_profile_kwargs(measured_resistivity_ohm_per_m=2.4))


class TestLoadProfile:
    def test_load_valid(self, fixture_profiles_dir: Path):
        profile = load_profile(fixture_profiles_dir / "test_cable.yaml")
        assert isinstance(profile, CableProfile)
        assert profile.profile_id == "test_cable"

    def test_filename_mismatch_rejected(self, tmp_path: Path, fixture_profiles_dir: Path):
        src = fixture_profiles_dir / "test_cable.yaml"
        renamed = tmp_path / "other_name.yaml"
        renamed.write_bytes(src.read_bytes())
        with pytest.raises(ValueError, match="does not match filename"):
            load_profile(renamed)

    def test_list_profiles(self, fixture_profiles_dir: Path):
        profiles = list_profiles(fixture_profiles_dir)
        assert len(profiles) >= 1
        assert any(p.profile_id == "test_cable" for p in profiles)

    def test_list_profiles_missing_dir(self, tmp_path: Path):
        assert list_profiles(tmp_path / "nope") == []
