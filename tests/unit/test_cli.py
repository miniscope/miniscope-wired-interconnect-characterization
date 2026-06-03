"""Tests for CLI commands."""

import subprocess
import sys
from pathlib import Path

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
        assert "Processed 6 sessions" in result.stdout
