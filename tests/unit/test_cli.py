"""Tests for CLI commands."""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import build_test_repo


def run_cli(*args: str, repo_root: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "src.cli.main"]
    if repo_root is not None:
        cmd += ["--repo-root", str(repo_root)]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


class TestCLI:
    def test_help(self):
        result = run_cli("--help")
        assert result.returncode == 0
        assert "miniscope-char" in result.stdout

    def test_no_command_shows_help(self):
        result = run_cli()
        assert result.returncode == 0

    def test_validate_valid_session(self, tmp_path: Path):
        repo = build_test_repo(tmp_path)
        session_dir = repo / "measurements" / "test_cable" / "500mm" / "resistance" / "20250115_01"
        result = run_cli("validate", str(session_dir), repo_root=repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "VALID" in result.stdout

    def test_validate_all(self, tmp_path: Path):
        repo = build_test_repo(tmp_path)
        result = run_cli("validate-all", repo_root=repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "0 failures" in result.stdout

    def test_validate_all_catches_bad_sessions(self, tmp_path: Path):
        repo = build_test_repo(tmp_path, bad_measurements=True)
        result = run_cli("validate-all", repo_root=repo)
        assert result.returncode == 1

    def test_process_all(self, tmp_path: Path):
        repo = build_test_repo(tmp_path)
        result = run_cli("process-all", repo_root=repo)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Processed 9 sessions" in result.stdout

    def test_acquire_help_lists_instrument_flags(self):
        result = run_cli("acquire", "--help")
        assert result.returncode == 0
        assert "--simulate" in result.stdout
        assert "--hardware" in result.stdout

    def test_acquire_simulate_and_hardware_are_mutually_exclusive(self):
        result = run_cli("acquire", "--simulate", "--hardware")
        assert result.returncode == 2
        assert "not allowed with argument" in result.stderr


class TestAcquireInstrumentSelection:
    """cmd_acquire maps the instrument flags to run_acquire's simulate kwarg."""

    def _simulate_for(self, monkeypatch, **flags) -> bool | None:
        pytest.importorskip("nicegui", reason="acquire extra not installed")
        import src.acquire.app as acquire_app
        from src.cli.main import cmd_acquire

        captured: dict = {}
        monkeypatch.setattr(acquire_app, "run_acquire", lambda **kw: captured.update(kw))
        ns = {
            "repo_root": ".",
            "host": "127.0.0.1",
            "port": 8081,
            "simulate": False,
            "hardware": False,
        }
        ns.update(flags)
        assert cmd_acquire(argparse.Namespace(**ns)) == 0
        return captured["simulate"]

    def test_hardware_flag_forces_real(self, monkeypatch):
        assert self._simulate_for(monkeypatch, hardware=True) is False

    def test_simulate_flag_forces_simulation(self, monkeypatch):
        assert self._simulate_for(monkeypatch, simulate=True) is True

    def test_no_flag_defers_to_env(self, monkeypatch):
        # None lets the registry consult MINISCOPE_ACQUIRE_HARDWARE.
        assert self._simulate_for(monkeypatch) is None
