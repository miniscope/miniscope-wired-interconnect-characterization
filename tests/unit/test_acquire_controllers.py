"""Tests for acquisition controllers (no GUI, no hardware)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.acquire.controllers.miniscopes import (
    create_miniscope,
    list_miniscopes,
    miniscope_form_fields,
)
from src.acquire.controllers.profiles import (
    commutator_form_fields,
    create_commutator_profile,
    create_profile,
    list_conditions,
    list_profile_summaries,
    profile_form_fields,
)
from src.acquire.controllers.protocols import load_protocol_markdown
from src.acquire.controllers.sessions import (
    check_serdes_links,
    read_serdes_link_status,
    record_resistance_session,
    run_serdes_capture,
    run_vna_capture,
    save_serdes_session,
    save_vna_session,
)
from src.instruments.types import ProgressEvent


class TestProfileControllers:
    def test_form_fields_track_schema(self):
        fields = {f.name: f for f in profile_form_fields()}
        assert "schema_version" not in fields  # filled automatically
        assert fields["profile_id"].required
        assert fields["name"].required
        assert fields["characteristic_impedance_ohm"].python_type == "float"
        assert fields["tags"].python_type == "list[str]"
        # Distributor order numbers surface as optional text inputs.
        assert fields["mouser_part_number"].python_type == "str"
        assert not fields["mouser_part_number"].required
        assert fields["digikey_part_number"].python_type == "str"

    def test_list_profile_summaries(self, test_repo: Path):
        summaries = list_profile_summaries(test_repo)
        assert len(summaries) == 2
        by_id = {s.profile.profile_id: s for s in summaries}
        cable = by_id["test_cable"]
        assert cable.profile.profile_type == "cable"
        assert cable.n_lengths == 2
        assert cable.n_sessions == 6
        comm = by_id["test_commutator"]
        assert comm.profile.profile_type == "commutator"
        assert comm.n_lengths == 1  # the 'static' condition
        assert comm.n_sessions == 3

    def test_create_profile(self, test_repo: Path):
        profile = create_profile(
            test_repo,
            {"profile_id": "new_cable", "name": "New Cable", "wire_gauge_awg": 36},
        )
        assert profile.profile_id == "new_cable"
        path = test_repo / "profiles" / "new_cable.yaml"
        assert path.exists()
        # Round-trips through the loader (filename <-> id contract)
        from src.core.loading import load_profile

        assert load_profile(path).wire_gauge_awg == 36

    def test_create_profile_invalid(self, test_repo: Path):
        with pytest.raises(ValidationError):
            create_profile(test_repo, {"profile_id": "Bad Id!", "name": "x"})

    def test_create_profile_duplicate(self, test_repo: Path):
        with pytest.raises(FileExistsError):
            create_profile(test_repo, {"profile_id": "test_cable", "name": "dup"})

    def test_list_conditions_cable(self, test_repo: Path):
        conditions = list_conditions(test_repo, "test_cable")
        assert [c.cable_length_mm for c in conditions] == [1000.0, 500.0]
        by_length = {c.cable_length_mm: c.sessions_by_type for c in conditions}
        assert by_length[500.0] == {"resistance": 2, "serdes": 1}
        assert by_length[1000.0] == {"serdes": 1, "vna": 2}

    def test_list_conditions_unknown_profile(self, test_repo: Path):
        assert list_conditions(test_repo, "nope") == []

    def test_list_conditions_commutator(self, test_repo: Path):
        conditions = list_conditions(test_repo, "test_commutator")
        assert [c.condition for c in conditions] == ["static"]
        static = conditions[0]
        assert static.cable_length_mm is None
        assert static.sessions_by_type == {"resistance": 1, "serdes": 1, "vna": 1}

    def test_list_conditions_cable_lengths(self, test_repo: Path):
        conditions = list_conditions(test_repo, "test_cable")
        assert {c.condition for c in conditions} == {"500mm", "1000mm"}
        assert all(c.cable_length_mm is not None for c in conditions)

    def test_commutator_form_fields_track_schema(self):
        fields = {f.name: f for f in commutator_form_fields()}
        assert "schema_version" not in fields  # filled automatically
        assert "profile_type" not in fields  # set by the controller
        assert fields["profile_id"].required
        assert fields["channel_count"].python_type == "float"  # number input
        assert fields["max_rotation_rpm"].python_type == "float"

    def test_create_commutator_profile(self, test_repo: Path):
        profile = create_commutator_profile(
            test_repo,
            {"profile_id": "new_comm", "name": "New Commutator", "channel_count": 2},
        )
        assert profile.profile_type == "commutator"
        path = test_repo / "profiles" / "new_comm.yaml"
        assert path.exists()
        # Round-trips through the dispatching loader
        from src.core.loading import load_profile
        from src.core.profile_schemas import CommutatorProfile

        loaded = load_profile(path)
        assert isinstance(loaded, CommutatorProfile)
        assert loaded.channel_count == 2

    def test_create_commutator_duplicate(self, test_repo: Path):
        with pytest.raises(FileExistsError):
            create_commutator_profile(test_repo, {"profile_id": "test_commutator", "name": "dup"})


class TestMiniscopeControllers:
    def test_form_fields_track_schema(self):
        fields = {f.name: f for f in miniscope_form_fields()}
        assert "schema_version" not in fields  # filled automatically
        assert fields["model_id"].required
        assert fields["min_operating_voltage_v"].python_type == "float"
        assert fields["poc_dcr_supply_ohm"].python_type == "float"
        assert fields["serdes_rate_gbps"].python_type == "float"
        assert fields["tags"].python_type == "list[str]"
        # Supply voltage is user/DAQ-side, never entered on a miniscope
        assert "supply_mode" not in fields
        assert "default_supply_v" not in fields

    def test_list_miniscopes(self, test_repo: Path):
        models = list_miniscopes(test_repo)
        assert [m.model_id for m in models] == ["test_miniscope", "test_miniscope_fpd"]
        assert models[0].serdes_family == "GMSL2"
        assert models[1].serdes_family == "FPD-Link III"

    def test_create_miniscope(self, test_repo: Path):
        model = create_miniscope(
            test_repo,
            {
                "model_id": "new_scope",
                "min_operating_voltage_v": 3.3,
                "max_current_ma": 250.0,
                "serdes_family": "GMSL2",
                "serdes_rate_gbps": 3.0,
            },
        )
        assert model.model_id == "new_scope"
        path = test_repo / "models" / "miniscope_models" / "new_scope.yaml"
        assert path.exists()
        # Round-trips through the loader used by the analysis pipeline
        from src.core.loading import load_model

        loaded = load_model(path, model_type="miniscope_models")
        assert loaded.serdes_rate_gbps == 3.0
        assert loaded.min_operating_voltage_v == 3.3

    def test_create_miniscope_invalid(self, test_repo: Path):
        with pytest.raises(ValidationError):
            create_miniscope(test_repo, {"model_id": "bad", "min_operating_voltage_v": -1.0})

    def test_create_miniscope_duplicate(self, test_repo: Path):
        with pytest.raises(FileExistsError):
            create_miniscope(test_repo, {"model_id": "test_miniscope"})

    def test_list_miniscopes_missing_dir(self, tmp_path: Path):
        assert list_miniscopes(tmp_path) == []


class TestProtocols:
    @pytest.mark.parametrize("mtype", ["resistance", "mass", "serdes", "vna"])
    def test_every_type_has_protocol(self, mtype: str):
        text = load_protocol_markdown(mtype)
        assert len(text) > 200
        assert text.startswith("#")

    def test_unknown_type_raises(self):
        with pytest.raises(FileNotFoundError):
            load_protocol_markdown("nonexistent")


class TestSessionControllers:
    def test_record_resistance_session(self, test_repo: Path):
        ref = record_resistance_session(
            test_repo,
            "test_cable",
            750.0,
            [(1.5, "a"), (1.6, "")],
            operator="Federico",
            notes="controller test",
            instrument="Test LCR",
            temperature_c=23.0,
        )
        assert ref.path.exists()
        from src.core.loading import load_session

        session = load_session(ref.path / "session.yaml")
        assert session.operator == "Federico"
        assert session.type_fields["temperature_c"] == 23.0

    def test_record_resistance_rejects_bad_value(self, test_repo: Path):
        with pytest.raises(ValueError):
            record_resistance_session(
                test_repo,
                "test_cable",
                750.0,
                [(-1.0, "bad")],
                operator="Federico",
                notes="",
                instrument="Test LCR",
            )

    def test_serdes_capture_and_save(self, test_repo: Path):
        events: list[ProgressEvent] = []
        result = run_serdes_capture(750.0, progress=events.append, simulate=True)
        assert len(result.eyes) == 3
        assert len(events) == 6

        ref = save_serdes_session(
            test_repo,
            "test_cable",
            750.0,
            result,
            operator="Federico",
            notes="",
            serdes_device="Sim GMSL2",
        )
        assert ref.measurement_type == "serdes"
        assert (ref.path / "session_manifest.csv").exists()

    def test_serdes_capture_forwards_port(self, monkeypatch):
        """A chosen serial port reaches the driver factory; None is omitted."""
        import src.acquire.controllers.sessions as sessions

        class _RecordingDriver:
            def connect(self):
                pass

            def run_full_sequence(self, config=None, progress=None):
                return "RESULT"

            def close(self):
                pass

        seen: dict = {}

        def fake_get_serdes_driver(simulate=None, **kwargs):
            seen.clear()
            seen["simulate"] = simulate
            seen.update(kwargs)
            return _RecordingDriver()

        monkeypatch.setattr(sessions, "get_serdes_driver", fake_get_serdes_driver)

        assert run_serdes_capture(750.0, port="COM5", simulate=False) == "RESULT"
        assert seen["port"] == "COM5"
        assert seen["cable_length_mm"] == 750.0
        assert seen["simulate"] is False

        # No port (e.g. simulate mode) -> factory is left to its own default.
        run_serdes_capture(750.0, simulate=True)
        assert "port" not in seen

    def test_read_link_status_forwards_port(self, monkeypatch):
        """The link-status controller forwards the chosen port and returns the dict."""
        import src.acquire.controllers.sessions as sessions

        class _Driver:
            def connect(self):
                pass

            def link_status(self):
                return {"connected": True, "forward_rate": "6 Gbps"}

            def close(self):
                pass

        seen: dict = {}

        def fake_get_serdes_driver(simulate=None, **kwargs):
            seen.clear()
            seen["simulate"] = simulate
            seen.update(kwargs)
            return _Driver()

        monkeypatch.setattr(sessions, "get_serdes_driver", fake_get_serdes_driver)

        status = read_serdes_link_status(100.0, simulate=False, port="COM3")
        assert status["forward_rate"] == "6 Gbps"
        assert seen["port"] == "COM3"
        assert seen["cable_length_mm"] == 100.0
        assert seen["simulate"] is False

    def test_serdes_simulator_link_status(self):
        """Simulate mode returns a flat status dict (no GMSL2 part numbers)."""
        status = read_serdes_link_status(100.0, simulate=True)
        assert status["connected"] is True
        assert status["simulated"] is True
        assert "ser" not in status

    def test_check_serdes_links_reports_per_rate_lock(self):
        """check_serdes_links returns link status + per-forward-rate lock; a long
        cable shows 6 Gbps not locking (the no-link signal)."""
        short = check_serdes_links(1000.0, simulate=True)
        assert short["status"] is not None
        assert short["locks"] == {"fwd_3g": True, "fwd_6g": True}

        long = check_serdes_links(2500.0, simulate=True)
        assert long["locks"]["fwd_3g"] is True
        assert long["locks"]["fwd_6g"] is False

    def test_check_serdes_links_surfaces_bench_error_in_band(self, monkeypatch):
        """A bench-reach failure (e.g. serial port) is returned as 'error', not
        raised -- run.io_bound can swallow a raised exception into a None result."""
        import src.acquire.controllers.sessions as sessions

        def boom(simulate=None, **kwargs):
            raise OSError("could not open COM5")

        monkeypatch.setattr(sessions, "get_serdes_driver", boom)
        out = check_serdes_links(100.0, simulate=False, port="COM5")
        assert out["error"] and "COM5" in out["error"]
        assert out["status"] is None
        assert out["locks"] == {}

    def test_serdes_capture_honors_resolution_config(self):
        """A custom SerdesConfig (resolution preset) flows through to the capture."""
        from src.instruments.serdes.driver import SerdesConfig

        result = run_serdes_capture(750.0, simulate=True, config=SerdesConfig(eye_bins=8))
        assert result.eyes
        assert all(eye.bins == 8 for eye in result.eyes)

    def test_vna_capture_forwards_calibration_file(self, monkeypatch):
        """A chosen .cal reaches the driver factory; None is omitted."""
        import src.acquire.controllers.sessions as sessions

        class _RecordingDriver:
            def connect(self):
                pass

            def is_calibrated(self):
                return True

            def sweep(self, config):
                return "RESULT"

            def close(self):
                pass

        seen: dict = {}

        def fake_get_vna_driver(simulate=None, **kwargs):
            seen.clear()
            seen["simulate"] = simulate
            seen.update(kwargs)
            return _RecordingDriver()

        monkeypatch.setattr(sessions, "get_vna_driver", fake_get_vna_driver)

        cal = r"C:\cal\myunit.cal"
        assert run_vna_capture(750.0, simulate=False, calibration_file=cal) == "RESULT"
        assert seen["calibration_file"] == cal
        assert seen["cable_length_mm"] == 750.0
        assert seen["simulate"] is False

        # No cal file -> the factory call omits it.
        run_vna_capture(750.0, simulate=True)
        assert "calibration_file" not in seen

    def test_vna_capture_and_save(self, test_repo: Path):
        result = run_vna_capture(750.0, simulate=True)
        ref = save_vna_session(
            test_repo,
            "test_cable",
            750.0,
            result,
            operator="Federico",
            notes="",
            vna_instrument="Sim VNA",
        )
        assert ref.measurement_type == "vna"
        assert (ref.path / "raw" / "sweep_01.s2p").exists()
