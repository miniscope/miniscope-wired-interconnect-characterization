from __future__ import annotations

from pathlib import Path

from src.core.schemas import MeasurementDefinition
from src.measurement_types.loader import load_definition


class MeasurementTypeRegistry:
    """
    Discovers and caches measurement type definitions from the
    measurement_types/ directory tree.

    Directory convention:
        measurement_types/<type_name>/v<version>/definition.yaml
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path("measurement_types")
        self._cache: dict[tuple[str, int], MeasurementDefinition] = {}

    def discover(self) -> list[tuple[str, int]]:
        """Scan measurement_types/ and return list of (type_name, version) tuples."""
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

    def get(self, type_name: str, version: int) -> MeasurementDefinition:
        """Load a specific measurement type definition, with caching."""
        key = (type_name, version)
        if key not in self._cache:
            path = self._base_dir / type_name / f"v{version}" / "definition.yaml"
            if not path.exists():
                raise FileNotFoundError(f"No definition found for {type_name} v{version} at {path}")
            self._cache[key] = load_definition(path)
        return self._cache[key]

    def get_latest(self, type_name: str) -> MeasurementDefinition:
        """Get the highest-versioned definition for a type."""
        versions = [v for (t, v) in self.discover() if t == type_name]
        if not versions:
            raise FileNotFoundError(f"No definitions found for type: {type_name}")
        return self.get(type_name, max(versions))

    def load_all(self) -> dict[tuple[str, int], MeasurementDefinition]:
        """Load all discovered definitions into the cache and return them."""
        for key in self.discover():
            self.get(*key)
        return dict(self._cache)
