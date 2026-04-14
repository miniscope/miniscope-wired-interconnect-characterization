"""Tests for CLI commands."""

import subprocess
import sys
from pathlib import Path


class TestCLI:
    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.cli.main", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "miniscope-char" in result.stdout

    def test_no_command_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.cli.main"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_validate_valid_experiment(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli.main",
                "validate",
                "experiments/EXP_2025_01_15_resistance_coax_40awg",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "VALID" in result.stdout

    def test_process_all(self, tmp_path: Path):
        """process-all should work (may have validation warnings but shouldn't crash)."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli.main",
                "process-all",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "experiments" in result.stdout.lower() or result.returncode == 0
