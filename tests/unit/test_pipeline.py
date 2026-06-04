"""Tests for the pipeline runner."""

from pathlib import Path

import pytest

from src.pipeline import (
    PipelineResult,
    _resolve_class,
    discover_sessions,
    process_session,
)
from src.processing.resistance import NormalizeResistance
from tests.conftest import build_test_repo


class TestResolveClass:
    def test_valid_path(self):
        cls = _resolve_class("src.processing.resistance.NormalizeResistance")
        assert cls is NormalizeResistance

    def test_invalid_module(self):
        with pytest.raises(ModuleNotFoundError):
            _resolve_class("src.processing.nonexistent.Foo")

    def test_invalid_class(self):
        with pytest.raises(AttributeError):
            _resolve_class("src.processing.resistance.NonexistentClass")


class TestDiscoverSessions:
    def test_discovers_all(self, test_repo: Path):
        sessions = discover_sessions(test_repo / "measurements")
        # cable: 2 resistance + 2 serdes + 2 vna; commutator: 1 of each
        assert len(sessions) == 9

    def test_filter_by_type(self, test_repo: Path):
        sessions = discover_sessions(test_repo / "measurements", "resistance")
        assert len(sessions) == 3
        assert all(s.parent.name == "resistance" for s in sessions)

    def test_missing_dir(self, tmp_path: Path):
        assert discover_sessions(tmp_path / "nope") == []


class TestProcessSession:
    def test_valid_session(self, test_repo: Path):
        session_dir = (
            test_repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250115_01"
        )
        result = process_session(session_dir, test_repo)

        assert isinstance(result, PipelineResult)
        assert result.validation.is_valid, result.validation.errors
        assert result.error is None
        assert "normalized_resistance_csv" in result.outputs
        assert "resistance_summary_json" in result.outputs

    def test_outputs_in_derived_sessions_tree(self, test_repo: Path):
        session_dir = (
            test_repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250115_01"
        )
        result = process_session(session_dir, test_repo)

        expected_dir = (
            test_repo
            / "derived"
            / "sessions"
            / "test_cable"
            / "500mm"
            / "resistance"
            / "20250115_01"
        )
        assert result.outputs["resistance_summary_json"].parent == expected_dir

    def test_session_without_yaml(self, test_repo: Path):
        session_dir = (
            test_repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250199_01"
        )
        session_dir.mkdir(parents=True)
        result = process_session(session_dir, test_repo)
        assert not result.validation.is_valid

    def test_invalid_csv_stops_processing(self, tmp_path: Path):
        repo = build_test_repo(tmp_path, bad_measurements=True)
        session_dir = repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250117_01"
        result = process_session(session_dir, repo)
        assert not result.validation.is_valid
        assert result.outputs == {}

    def test_path_mismatch_fails_validation(self, tmp_path: Path):
        repo = build_test_repo(tmp_path, bad_measurements=True)
        session_dir = repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250120_01"
        result = process_session(session_dir, repo)
        assert not result.validation.is_valid
        assert any("mismatch" in e for e in result.validation.errors)
