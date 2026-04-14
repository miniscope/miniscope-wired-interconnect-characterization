"""Generate wiki-ready JSON payloads combining model metadata with characterization results."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.core.loading import load_experiment

logger = logging.getLogger(__name__)


def generate_wiki_payloads(repo_root: Path) -> dict[str, Path]:
    """
    Generate a wiki payload JSON for each cable model referenced by experiments.

    Each payload combines:
    - Model metadata from models/cable_models/
    - Aggregated characterization summaries from derived/normalized/

    Returns mapping of model_id -> payload file path.
    """
    output_dir = repo_root / "derived" / "wiki_payloads"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover all experiments and their cable model references
    model_experiments: dict[str, list[dict]] = {}
    experiments_dir = repo_root / "experiments"

    if experiments_dir.exists():
        for exp_dir in sorted(experiments_dir.iterdir()):
            if not exp_dir.is_dir():
                continue
            yaml_path = exp_dir / "experiment.yaml"
            if not yaml_path.exists():
                continue
            try:
                experiment = load_experiment(yaml_path)
                cable_model = experiment.type_fields.get("cable_model")
                if cable_model:
                    if cable_model not in model_experiments:
                        model_experiments[cable_model] = []

                    # Load the experiment's summary if it exists
                    summary = _load_experiment_summary(
                        repo_root, experiment.experiment_id, experiment.experiment_type
                    )
                    model_experiments[cable_model].append(
                        {
                            "experiment_id": experiment.experiment_id,
                            "experiment_type": experiment.experiment_type,
                            "date": str(experiment.date),
                            "description": experiment.description,
                            "summary": summary,
                        }
                    )
            except Exception as e:
                logger.warning("Failed to load %s: %s", yaml_path, e)

    outputs: dict[str, Path] = {}

    for model_id, experiments in model_experiments.items():
        payload = _build_payload(repo_root, model_id, experiments)
        payload_path = output_dir / f"{model_id}.json"
        with open(payload_path, "w") as f:
            json.dump(payload, f, indent=2)
        outputs[model_id] = payload_path
        logger.info("Generated wiki payload for %s", model_id)

    return outputs


def _load_experiment_summary(
    repo_root: Path, experiment_id: str, experiment_type: str
) -> dict | None:
    """Load the processed summary JSON for an experiment."""
    summary_names = {
        "resistance_characterization": "resistance_summary.json",
        "eye_diagram_characterization": "eye_summary.json",
        "vna_characterization": "vna_summary.json",
    }
    summary_name = summary_names.get(experiment_type)
    if not summary_name:
        return None

    summary_path = repo_root / "derived" / "normalized" / experiment_id / summary_name
    if not summary_path.exists():
        return None

    try:
        with open(summary_path) as f:
            return json.load(f)
    except Exception:
        return None


def _build_payload(repo_root: Path, model_id: str, experiments: list[dict]) -> dict:
    """Build a wiki payload for a cable model."""
    payload: dict = {
        "model_id": model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_metadata": None,
        "characterization": {
            "resistance": [],
            "eye_diagram": [],
            "vna": [],
        },
    }

    # Load model metadata
    model_path = repo_root / "models" / "cable_models" / f"{model_id}.yaml"
    if model_path.exists():
        try:
            with open(model_path) as f:
                payload["model_metadata"] = yaml.safe_load(f)
        except Exception as e:
            logger.warning("Failed to load model metadata for %s: %s", model_id, e)

    # Group experiments by type
    type_key_map = {
        "resistance_characterization": "resistance",
        "eye_diagram_characterization": "eye_diagram",
        "vna_characterization": "vna",
    }

    for exp in experiments:
        key = type_key_map.get(exp["experiment_type"])
        if key:
            payload["characterization"][key].append(
                {
                    "experiment_id": exp["experiment_id"],
                    "date": exp["date"],
                    "description": exp["description"],
                    "summary": exp["summary"],
                }
            )

    return payload
