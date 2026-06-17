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


def make_mass_session(
    base_dir: Path,
    *,
    session_id: str = "20250115_01",
    profile_id: str = "test_cable",
    length_mm: float | None = 500.0,
    condition: str | None = None,
    rows: list[tuple[float, float, str]] | None = None,
) -> Path:
    """
    Write a self-contained mass session under base_dir and return its dir.

    Mass has no committed fixtures (it would shift the session counts the
    other tests assert), so mass tests build their own sessions here.
    """
    if rows is None:
        rows = [(12.00, 4.00, "w1"), (12.05, 4.00, "w2"), (11.98, 4.02, "w3"), (12.02, 3.99, "w4")]
    cond = condition or (f"{length_mm:g}mm" if length_mm is not None else "static")
    session_dir = base_dir / profile_id / cond / "mass" / session_id
    session_dir.mkdir(parents=True)

    lines = [
        'schema_version: "1.0"',
        f'session_id: "{session_id}"',
        f"profile_id: {profile_id}",
    ]
    if length_mm is not None:
        lines.append(f"cable_length_mm: {length_mm:g}")
    else:
        lines.append(f"condition: {cond}")
    lines += [
        "measurement_type: mass",
        "measurement_type_version: 1",
        "date: 2025-01-15",
        "operator: Test Operator",
        'notes: "fixture mass session"',
        "type_fields:",
        '  measurement_instrument: "Test Balance"',
        "  measurement_method: digital_balance",
    ]
    (session_dir / "session.yaml").write_text("\n".join(lines) + "\n")

    csv_lines = ["assembly_mass_g,fixture_mass_g,notes"]
    csv_lines += [f"{a},{f},{n}" for a, f, n in rows]
    (session_dir / "mass.csv").write_text("\n".join(csv_lines) + "\n")
    return session_dir


@pytest.fixture
def mass_session_dir(tmp_path: Path) -> Path:
    """A self-contained 500 mm cable mass session (net ~8 g -> ~0.16 g/cm)."""
    return make_mass_session(tmp_path)


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
