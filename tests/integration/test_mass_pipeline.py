"""Integration tests: full mass characterization pipeline."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.acquire.controllers.sessions import record_mass_session
from src.analysis.consolidate import consolidate_profile
from src.core.loading import load_session
from src.core.session_writer import SessionMeta, SessionWriteError, write_mass_session
from src.instruments.balance.driver import MassReading
from src.pipeline import aggregate_type, process_session

TODAY = date(2026, 6, 3)


def mass_meta(**overrides) -> SessionMeta:
    kwargs = {
        "operator": "Test Operator",
        "date": TODAY,
        "notes": "mass writer test",
        "type_fields": {
            "measurement_instrument": "Test Balance",
            "measurement_method": "digital_balance",
        },
    }
    kwargs.update(overrides)
    return SessionMeta(**kwargs)


def write_cable_mass(repo: Path, length_mm: float, rows: list[tuple[float, float, str]]):
    readings = [MassReading(a, f, n) for a, f, n in rows]
    return write_mass_session(repo, "test_cable", length_mm, readings, mass_meta())


class TestWriteMassSession:
    def test_writes_and_validates(self, test_repo: Path):
        ref = write_cable_mass(test_repo, 750.0, [(12.0, 4.0, "first"), (12.1, 4.0, "second")])

        assert ref.ref == "test_cable/750mm/mass/20260603_01"
        assert (ref.path / "session.yaml").exists()
        df = pd.read_csv(ref.path / "mass.csv")
        assert list(df["assembly_mass_g"]) == [12.0, 12.1]
        assert list(df["fixture_mass_g"]) == [4.0, 4.0]

    def test_no_readings_rejected(self, test_repo: Path):
        with pytest.raises(ValueError):
            write_mass_session(test_repo, "test_cable", 750.0, [], mass_meta())

    def test_inverted_masses_rolled_back(self, test_repo: Path):
        """A weighing whose fixture exceeds the assembly fails validation and is removed."""
        with pytest.raises(SessionWriteError):
            write_cable_mass(test_repo, 750.0, [(4.0, 12.0, "inverted")])
        assert not list((test_repo / "measurements" / "test_cable").rglob("mass.csv"))

    def test_commutator_static_roundtrip(self, test_repo: Path):
        ref = write_mass_session(
            test_repo,
            "test_commutator",
            None,
            [MassReading(5.0, 2.0, "through commutator")],
            mass_meta(),
            condition="static",
        )
        assert ref.ref == "test_commutator/static/mass/20260603_01"
        assert ref.cable_length_mm is None

        result = process_session(ref.path, test_repo)
        assert result.validation.is_valid, result.validation.errors
        with open(result.outputs["mass_summary_json"]) as f:
            summary = json.load(f)
        assert summary["mean_cable_mass_g"] == 3.0
        assert "mean_cable_mass_g_per_cm" not in summary


class TestMassPipeline:
    def test_process_session(self, test_repo: Path):
        ref = write_cable_mass(test_repo, 500.0, [(12.0, 4.0, ""), (12.0, 4.0, "")])
        result = process_session(ref.path, test_repo)

        assert result.validation.is_valid, result.validation.errors
        assert result.error is None
        assert "normalized_mass_csv" in result.outputs
        assert "mass_summary_json" in result.outputs

        df = pd.read_csv(result.outputs["normalized_mass_csv"])
        assert "cable_mass_g_per_cm" in df.columns

        with open(result.outputs["mass_summary_json"]) as f:
            summary = json.load(f)
        # net 8 g over 50 cm -> 0.16 g/cm
        assert 0.15 < summary["mean_cable_mass_g_per_cm"] < 0.17

    def test_aggregate_after_processing(self, test_repo: Path):
        for length in [500.0, 1000.0]:
            ref = write_cable_mass(test_repo, length, [(10.0, 3.0, "")])
            assert process_session(ref.path, test_repo).error is None

        outputs = aggregate_type("mass", test_repo)
        assert "mass_summary_table" in outputs
        assert "mass_boxplot" in outputs

        df = pd.read_csv(outputs["mass_summary_table"])
        assert len(df) == 2
        assert (df["profile_id"] == "test_cable").all()

    def test_aggregate_with_no_sessions_is_noop(self, test_repo: Path):
        """The fixture tree has no mass sessions, so aggregation returns nothing."""
        assert aggregate_type("mass", test_repo) == {}

    def test_consolidation_pools_sessions(self, test_repo: Path):
        for session_n in range(2):
            ref = write_cable_mass(test_repo, 500.0, [(12.0, 4.0, f"s{session_n}")])
            process_session(ref.path, test_repo)

        outputs = consolidate_profile(test_repo, "test_cable")
        assert "test_cable_mass_by_length" in outputs

        df = pd.read_csv(outputs["test_cable_mass_by_length"])
        assert len(df) == 1
        row = df.iloc[0]
        assert row["cable_length_mm"] == 500.0
        assert row["n_sessions"] == 2
        assert row["total_measurements"] == 2
        assert row["mean_cable_mass_g"] > 0
        assert row["mean_cable_mass_g_per_cm"] > 0


class TestRecordMassController:
    def test_record_mass_session(self, test_repo: Path):
        ref = record_mass_session(
            test_repo,
            "test_cable",
            750.0,
            [(12.0, 4.0, "a"), (12.1, 4.05, "")],
            operator="Federico",
            notes="controller test",
            instrument="Test Balance",
        )
        assert ref.path.exists()

        session = load_session(ref.path / "session.yaml")
        assert session.operator == "Federico"
        assert session.type_fields["measurement_method"] == "digital_balance"

    def test_record_mass_rejects_inverted(self, test_repo: Path):
        with pytest.raises(ValueError):
            record_mass_session(
                test_repo,
                "test_cable",
                750.0,
                [(4.0, 12.0, "bad")],
                operator="Federico",
                notes="",
                instrument="Test Balance",
            )
