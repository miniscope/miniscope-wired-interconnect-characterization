"""Tests for wiki page rendering (offline, no network)."""

import json
from pathlib import Path

import pytest

from src.pipeline import run_full_pipeline
from src.wiki.config import load_wiki_config
from src.wiki.render import render_wiki


@pytest.fixture
def analyzed_repo(test_repo: Path) -> Path:
    summary = run_full_pipeline(test_repo)
    assert all(p["valid"] for p in summary["processed"])
    return test_repo


class TestWikiConfig:
    def test_loads_repo_config(self):
        config = load_wiki_config(Path("config/wiki.yaml"))
        assert config.api_url.endswith("api.php")
        assert "{profile_id}" in config.profile_page_template
        assert config.profile_page("foo").endswith("foo")


class TestRenderWiki:
    def test_outputs(self, analyzed_repo: Path):
        outputs = render_wiki(analyzed_repo)

        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        assert f"page_{config.main_page}" in outputs
        assert f"page_{config.profile_page('test_cable')}" in outputs
        assert "upload_manifest" in outputs
        for path in outputs.values():
            assert path.exists()

    def test_main_page_content(self, analyzed_repo: Path):
        outputs = render_wiki(analyzed_repo)
        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        text = outputs[f"page_{config.main_page}"].read_text(encoding="utf-8")

        assert "AUTO-GENERATED" in text
        assert "quality" in text.lower()
        assert "supply voltage" in text.lower()
        # Supply-window feasibility is surfaced so a min>max (empty) window is
        # not misread as a swapped reading.
        assert "Feasible?" in text
        # Links to the per-profile page
        assert config.profile_page("test_cable") in text
        # Quality plots embedded per rate
        assert "quality_vs_length_3g.png" in text
        assert "quality_vs_length_6g.png" in text
        # Wikitable rendered
        assert '{| class="wikitable"' in text

    def test_profile_page_content(self, analyzed_repo: Path):
        outputs = render_wiki(analyzed_repo)
        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        text = outputs[f"page_{config.profile_page('test_cable')}"].read_text(encoding="utf-8")

        assert "Cable specifications" in text
        assert "Round-trip resistivity" in text
        assert "SerDes signal integrity" in text
        assert "Eye diagrams" in text
        assert "RF attenuation" in text
        assert "Resistance measurements" in text
        assert f"[[{config.main_page}]]" in text

    def test_commutator_page_content(self, analyzed_repo: Path):
        outputs = render_wiki(analyzed_repo)
        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        text = outputs[f"page_{config.profile_page('test_commutator')}"].read_text(encoding="utf-8")

        assert "Commutator specifications" in text
        assert "Impact on your link" in text
        assert "Series resistance" in text
        assert "SerDes signal integrity" in text
        assert "RF insertion loss" in text
        # Standalone impact, not a cable x commutator matrix
        assert "Cable length budget" in text
        assert f"[[{config.main_page}]]" in text

    def test_main_page_commutator_section(self, analyzed_repo: Path):
        outputs = render_wiki(analyzed_repo)
        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        text = outputs[f"page_{config.main_page}"].read_text(encoding="utf-8")

        assert "What does a commutator cost?" in text
        assert config.profile_page("test_commutator") in text

    def test_upload_manifest(self, analyzed_repo: Path):
        outputs = render_wiki(analyzed_repo)
        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        with open(outputs["upload_manifest"]) as f:
            manifest = json.load(f)

        assert len(manifest["pages"]) == 3  # main + cable + commutator
        assert len(manifest["images"]) > 0
        for image in manifest["images"]:
            # Prefix comes from config/wiki.yaml, never hardcoded
            assert image["wiki_name"].startswith(config.image_prefix)
            assert (analyzed_repo / image["local_path"]).exists()

    def test_render_without_analysis_still_produces_pages(self, test_repo: Path):
        """Rendering an unanalyzed repo yields pages without plots, not a crash."""
        outputs = render_wiki(test_repo)
        assert "upload_manifest" in outputs

    def test_profile_page_explains_no_link(self, test_repo: Path):
        """A no-link length gets an explanatory note so it is not misread as a
        bad cable (the live 170 mm coax case)."""
        from datetime import date

        from src.core.session_writer import SessionMeta, write_serdes_session
        from src.instruments.types import FORWARD_6G, SerdesResult

        write_serdes_session(
            test_repo,
            "test_cable",
            1500.0,
            SerdesResult(no_link_lanes=[FORWARD_6G]),
            SessionMeta(
                operator="t", date=date.today(), notes="", type_fields={"serdes_device": "x"}
            ),
        )
        run_full_pipeline(test_repo)

        config = load_wiki_config(test_repo / "config" / "wiki.yaml")
        outputs = render_wiki(test_repo)
        text = outputs[f"page_{config.profile_page('test_cable')}"].read_text(encoding="utf-8")

        assert "Links? = False" in text
        assert "too clean" in text

    def test_profile_page_no_note_without_no_link(self, analyzed_repo: Path):
        """The all-linked fixture cable shows no no-link note."""
        outputs = render_wiki(analyzed_repo)
        config = load_wiki_config(analyzed_repo / "config" / "wiki.yaml")
        text = outputs[f"page_{config.profile_page('test_cable')}"].read_text(encoding="utf-8")

        assert "too clean" not in text
