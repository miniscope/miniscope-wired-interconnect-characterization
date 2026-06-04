"""Generate wiki-ready JSON payloads combining cable profiles with characterization results."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.core.loading import load_session

logger = logging.getLogger(__name__)

# Summary JSON written by each measurement type's processor.
_SUMMARY_FILES: dict[str, str] = {
    "resistance": "resistance_summary.json",
    "serdes": "serdes_summary.json",
    "vna": "vna_summary.json",
}


def generate_wiki_payloads(repo_root: Path) -> dict[str, Path]:
    """
    Generate a wiki payload JSON for each cable profile.

    Each payload combines:
    - The profile specification from profiles/<profile_id>.yaml
    - Per-session characterization summaries from derived/sessions/

    Returns mapping of profile_id -> payload file path.
    """
    output_dir = repo_root / "derived" / "wiki" / "payloads"
    output_dir.mkdir(parents=True, exist_ok=True)

    profiles_dir = repo_root / "profiles"
    outputs: dict[str, Path] = {}

    if not profiles_dir.exists():
        return outputs

    for profile_path in sorted(profiles_dir.glob("*.yaml")):
        profile_id = profile_path.stem
        payload = _build_payload(repo_root, profile_id, profile_path)
        payload_path = output_dir / f"{profile_id}.json"
        with open(payload_path, "w") as f:
            json.dump(payload, f, indent=2)
        outputs[profile_id] = payload_path
        logger.info("Generated wiki payload for %s", profile_id)

    return outputs


def _build_payload(repo_root: Path, profile_id: str, profile_path: Path) -> dict:
    """Build a wiki payload for one cable profile."""
    payload: dict = {
        "profile_id": profile_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": None,
        "characterization": {key: [] for key in _SUMMARY_FILES},
    }

    try:
        with open(profile_path) as f:
            payload["profile"] = yaml.safe_load(f)
    except Exception as e:
        logger.warning("Failed to load profile %s: %s", profile_path, e)

    profile_measurements = repo_root / "measurements" / profile_id
    if not profile_measurements.exists():
        return payload

    for yaml_path in sorted(profile_measurements.glob("*/*/*/session.yaml")):
        try:
            session = load_session(yaml_path)
        except Exception as e:
            logger.warning("Failed to load %s: %s", yaml_path, e)
            continue

        summary_name = _SUMMARY_FILES.get(session.measurement_type)
        if summary_name is None:
            continue

        rel = Path(profile_id) / session.condition
        rel = rel / session.measurement_type / session.session_id
        summary_path = repo_root / "derived" / "sessions" / rel / summary_name
        summary = None
        if summary_path.exists():
            try:
                with open(summary_path) as f:
                    summary = json.load(f)
            except Exception:
                summary = None

        payload["characterization"][session.measurement_type].append(
            {
                "session_ref": str(rel).replace("\\", "/"),
                "condition": session.condition,
                "cable_length_mm": session.cable_length_mm,
                "date": str(session.date),
                "operator": session.operator,
                "notes": session.notes,
                "summary": summary,
            }
        )

    return payload
