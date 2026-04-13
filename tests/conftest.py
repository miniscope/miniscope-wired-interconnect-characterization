from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def valid_definition_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "definitions" / "valid_minimal.yaml"


@pytest.fixture
def full_definition_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "definitions" / "valid_full.yaml"


@pytest.fixture
def valid_experiment_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "experiments" / "valid_experiment.yaml"


@pytest.fixture
def valid_cable_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "models" / "valid_cable.yaml"
