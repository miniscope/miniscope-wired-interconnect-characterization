"""Load the embedded measurement protocols (docs/protocols/<type>.md)."""

from __future__ import annotations

from pathlib import Path

PROTOCOLS_DIR = Path(__file__).resolve().parents[3] / "docs" / "protocols"


def load_protocol_markdown(measurement_type: str, protocols_dir: Path | None = None) -> str:
    """
    Return the protocol document for a measurement type.

    Raises FileNotFoundError for unknown types -- every measurement type
    MUST ship a protocol; that is the point of this repo.
    """
    base = protocols_dir or PROTOCOLS_DIR
    path = base / f"{measurement_type}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"No protocol document for measurement type '{measurement_type}' at {path}"
        )
    return path.read_text(encoding="utf-8")
