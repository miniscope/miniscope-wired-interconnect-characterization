from __future__ import annotations

from pathlib import Path

from src.core.schemas import ExperimentDefinition
from src.experiment_types.loader import load_definition


class ExperimentTypeRegistry:
    """
    Discovers and caches experiment type definitions from the
    experiment_types/ directory tree.

    Directory convention:
        experiment_types/<type_name>/v<version>/definition.yaml
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path("experiment_types")
        self._cache: dict[tuple[str, int], ExperimentDefinition] = {}

    def discover(self) -> list[tuple[str, int]]:
        """Scan experiment_types/ and return list of (type_name, version) tuples."""
        found: list[tuple[str, int]] = []
        if not self._base_dir.exists():
            return found
        for type_dir in sorted(self._base_dir.iterdir()):
            if not type_dir.is_dir() or type_dir.name.startswith("."):
                continue
            for version_dir in sorted(type_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                if not version_dir.name.startswith("v"):
                    continue
                definition_file = version_dir / "definition.yaml"
                if definition_file.exists():
                    version_num = int(version_dir.name[1:])
                    found.append((type_dir.name, version_num))
        return found

    def get(self, type_name: str, version: int) -> ExperimentDefinition:
        """Load a specific experiment type definition, with caching."""
        key = (type_name, version)
        if key not in self._cache:
            path = self._base_dir / type_name / f"v{version}" / "definition.yaml"
            if not path.exists():
                raise FileNotFoundError(f"No definition found for {type_name} v{version} at {path}")
            self._cache[key] = load_definition(path)
        return self._cache[key]

    def get_latest(self, type_name: str) -> ExperimentDefinition:
        """Get the highest-versioned definition for a type."""
        versions = [v for (t, v) in self.discover() if t == type_name]
        if not versions:
            raise FileNotFoundError(f"No definitions found for type: {type_name}")
        return self.get(type_name, max(versions))

    def load_all(self) -> dict[tuple[str, int], ExperimentDefinition]:
        """Load all discovered definitions into the cache and return them."""
        for key in self.discover():
            self.get(*key)
        return dict(self._cache)
