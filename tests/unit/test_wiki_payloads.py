"""Tests for wiki payload generation."""

import json
from pathlib import Path

from src.pipeline import process_all
from src.wiki.payloads import generate_wiki_payloads


class TestGenerateWikiPayloads:
    def _process_repo(self, test_repo: Path) -> Path:
        results = process_all(test_repo / "measurements", test_repo)
        assert all(r.error is None for r in results)
        return test_repo

    def test_generates_payload_per_profile(self, test_repo: Path):
        self._process_repo(test_repo)
        outputs = generate_wiki_payloads(test_repo)

        assert "test_cable" in outputs
        assert outputs["test_cable"].exists()

    def test_payload_contains_profile(self, test_repo: Path):
        self._process_repo(test_repo)
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["test_cable"]) as f:
            payload = json.load(f)

        assert payload["profile_id"] == "test_cable"
        assert payload["profile"] is not None
        assert payload["profile"]["profile_id"] == "test_cable"

    def test_payload_contains_characterization_data(self, test_repo: Path):
        self._process_repo(test_repo)
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["test_cable"]) as f:
            payload = json.load(f)

        assert len(payload["characterization"]["resistance"]) == 2
        assert len(payload["characterization"]["vna"]) == 2

        entry = payload["characterization"]["resistance"][0]
        assert entry["session_ref"] == "test_cable/500mm/resistance/20250115_01"
        assert entry["cable_length_mm"] == 500.0
        assert entry["summary"] is not None

    def test_payload_has_generated_at(self, test_repo: Path):
        self._process_repo(test_repo)
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["test_cable"]) as f:
            payload = json.load(f)

        assert "generated_at" in payload

    def test_unprocessed_sessions_have_null_summary(self, test_repo: Path):
        """Payloads still list sessions even before processing has run."""
        outputs = generate_wiki_payloads(test_repo)

        with open(outputs["test_cable"]) as f:
            payload = json.load(f)

        assert len(payload["characterization"]["resistance"]) == 2
        assert all(e["summary"] is None for e in payload["characterization"]["resistance"])

    def test_no_profiles_no_payloads(self, tmp_path: Path):
        empty_repo = tmp_path / "empty_repo"
        (empty_repo / "measurements").mkdir(parents=True)
        (empty_repo / "derived").mkdir()

        outputs = generate_wiki_payloads(empty_repo)
        assert outputs == {}
