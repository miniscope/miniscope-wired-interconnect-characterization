import shutil
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent


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
def valid_session_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sessions" / "valid_session.yaml"


@pytest.fixture
def fixture_models_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "models"


@pytest.fixture
def fixture_profiles_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "profiles"


@pytest.fixture
def measurements_fixtures_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "measurements"


@pytest.fixture
def bad_measurements_fixtures_dir(fixtures_dir: Path) -> Path:
    return fixtures_dir / "measurements_bad"


@pytest.fixture
def resistance_session_dir(measurements_fixtures_dir: Path) -> Path:
    return measurements_fixtures_dir / "test_cable" / "500mm" / "resistance" / "20250115_01"


@pytest.fixture
def vna_session_dir(measurements_fixtures_dir: Path) -> Path:
    return measurements_fixtures_dir / "test_cable" / "1000mm" / "vna" / "20250301_01"


def build_test_repo(
    tmp_path: Path,
    include_measurements: bool = True,
    bad_measurements: bool = False,
) -> Path:
    """
    Assemble a self-contained repository tree in tmp_path from fixtures:
    real measurement_types/ definitions plus fixture profiles, models, and
    measurement sessions.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    shutil.copytree(REPO_ROOT / "measurement_types", repo / "measurement_types")
    shutil.copytree(REPO_ROOT / "config", repo / "config")
    shutil.copytree(FIXTURES_DIR / "profiles", repo / "profiles")
    shutil.copytree(FIXTURES_DIR / "models", repo / "models")

    if include_measurements:
        source = "measurements_bad" if bad_measurements else "measurements"
        shutil.copytree(FIXTURES_DIR / source, repo / "measurements")
    else:
        (repo / "measurements").mkdir()

    (repo / "derived").mkdir()
    return repo


@pytest.fixture
def test_repo(tmp_path: Path) -> Path:
    """A complete repo tree with valid fixture measurements."""
    return build_test_repo(tmp_path)
