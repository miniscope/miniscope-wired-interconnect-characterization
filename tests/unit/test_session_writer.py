"""Tests for session writers: the app's only path for creating data."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.core.session_writer import (
    SessionMeta,
    SessionWriteError,
    delete_session,
    new_session_id,
    write_resistance_session,
    write_serdes_session,
    write_vna_session,
)
from src.instruments.lcr.driver import ResistanceReading
from src.instruments.registry import get_serdes_driver, get_vna_driver
from src.instruments.vna.driver import VnaConfig
from src.pipeline import process_session

TODAY = date(2026, 6, 3)


def resistance_meta(**overrides) -> SessionMeta:
    kwargs = {
        "operator": "Test Operator",
        "date": TODAY,
        "notes": "writer test",
        "type_fields": {
            "measurement_instrument": "Test LCR",
            "measurement_method": "lcr_shorted_loop",
        },
    }
    kwargs.update(overrides)
    return SessionMeta(**kwargs)


class TestNewSessionId:
    def test_first_of_day(self, test_repo: Path):
        session_id = new_session_id(test_repo, "test_cable", 750.0, "resistance", TODAY)
        assert session_id == "20260603_01"

    def test_increments(self, test_repo: Path):
        ref = write_resistance_session(
            test_repo,
            "test_cable",
            750.0,
            [ResistanceReading(1.5)],
            resistance_meta(),
        )
        assert ref.session_id == "20260603_01"
        next_id = new_session_id(test_repo, "test_cable", 750.0, "resistance", TODAY)
        assert next_id == "20260603_02"


class TestWriteResistanceSession:
    def test_writes_and_validates(self, test_repo: Path):
        ref = write_resistance_session(
            test_repo,
            "test_cable",
            750.0,
            [ResistanceReading(1.5, "first"), ResistanceReading(1.6, "second")],
            resistance_meta(),
        )

        assert ref.ref == "test_cable/750mm/resistance/20260603_01"
        assert (ref.path / "session.yaml").exists()
        df = pd.read_csv(ref.path / "resistance.csv")
        assert list(df["resistance_ohm"]) == [1.5, 1.6]
        assert list(df["notes"]) == ["first", "second"]

    def test_written_session_processes_cleanly(self, test_repo: Path):
        """The end-to-end guarantee: app output is pipeline-valid."""
        ref = write_resistance_session(
            test_repo, "test_cable", 750.0, [ResistanceReading(1.5)], resistance_meta()
        )
        result = process_session(ref.path, test_repo)
        assert result.validation.is_valid, result.validation.errors
        assert result.error is None

    def test_no_readings_rejected(self, test_repo: Path):
        with pytest.raises(ValueError):
            write_resistance_session(test_repo, "test_cable", 750.0, [], resistance_meta())

    def test_invalid_session_rolled_back(self, test_repo: Path):
        """A session that fails validation is deleted, not left half-written."""
        with pytest.raises(SessionWriteError):
            write_resistance_session(
                test_repo,
                "unknown_profile",  # no such profile -> validation error
                750.0,
                [ResistanceReading(1.5)],
                resistance_meta(),
            )
        assert not (test_repo / "measurements" / "unknown_profile").exists() or not list(
            (test_repo / "measurements" / "unknown_profile").rglob("session.yaml")
        )


class TestWriteCommutatorSession:
    def test_static_condition_roundtrip(self, test_repo: Path):
        """Commutator sessions write under a named condition, no length."""
        ref = write_resistance_session(
            test_repo,
            "test_commutator",
            None,
            [ResistanceReading(0.4, "through commutator")],
            resistance_meta(),
            condition="static",
        )

        assert ref.ref == "test_commutator/static/resistance/20260603_01"
        assert ref.cable_length_mm is None

        result = process_session(ref.path, test_repo)
        assert result.validation.is_valid, result.validation.errors
        assert result.error is None

    def test_length_on_commutator_rejected(self, test_repo: Path):
        """Validation refuses a length condition on a commutator profile."""
        with pytest.raises(SessionWriteError, match="state condition"):
            write_resistance_session(
                test_repo,
                "test_commutator",
                500.0,
                [ResistanceReading(0.4)],
                resistance_meta(),
            )

    def test_unknown_commutator_condition_rejected(self, test_repo: Path):
        with pytest.raises(SessionWriteError, match="Unknown commutator condition"):
            write_resistance_session(
                test_repo,
                "test_commutator",
                None,
                [ResistanceReading(0.4)],
                resistance_meta(),
                condition="upside_down",
            )

    def test_named_condition_on_cable_rejected(self, test_repo: Path):
        """Validation refuses a state condition on a cable profile."""
        with pytest.raises(SessionWriteError, match="length condition"):
            write_resistance_session(
                test_repo,
                "test_cable",
                None,
                [ResistanceReading(1.5)],
                resistance_meta(),
                condition="static",
            )


class TestWriteSerdesSession:
    def test_simulated_capture_roundtrip(self, test_repo: Path):
        driver = get_serdes_driver(simulate=True, cable_length_mm=750.0)
        driver.connect()
        result = driver.run_full_sequence()

        ref = write_serdes_session(
            test_repo,
            "test_cable",
            750.0,
            result,
            resistance_meta(type_fields={"serdes_device": "Sim GMSL2"}),
        )

        manifest = pd.read_csv(ref.path / "session_manifest.csv")
        assert len(manifest) == 3
        assert (ref.path / "eye_fwd_3g.csv").exists()
        assert (ref.path / "margin_rev_187m.csv").exists()

        pipeline_result = process_session(ref.path, test_repo)
        assert pipeline_result.validation.is_valid, pipeline_result.validation.errors
        assert "serdes_summary_json" in pipeline_result.outputs


class TestWriteVnaSession:
    def test_simulated_capture_roundtrip(self, test_repo: Path):
        driver = get_vna_driver(simulate=True, cable_length_mm=750.0)
        driver.connect()
        result = driver.sweep(VnaConfig(num_points=51))

        ref = write_vna_session(
            test_repo,
            "test_cable",
            750.0,
            result,
            resistance_meta(type_fields={"vna_instrument": "Sim VNA", "calibration_type": "SOLT"}),
        )

        assert (ref.path / "raw" / "sweep_01.s2p").exists()
        pipeline_result = process_session(ref.path, test_repo)
        assert pipeline_result.validation.is_valid, pipeline_result.validation.errors
        assert "vna_summary_json" in pipeline_result.outputs


class TestDeleteSession:
    def test_removes_session_and_derived(self, test_repo: Path):
        ref = write_resistance_session(
            test_repo, "test_cable", 750.0, [ResistanceReading(1.5)], resistance_meta()
        )
        process_session(ref.path, test_repo)
        derived = test_repo / "derived" / "sessions" / Path(ref.ref)
        assert derived.exists()

        delete_session(test_repo, ref)
        assert not ref.path.exists()
        assert not derived.exists()
