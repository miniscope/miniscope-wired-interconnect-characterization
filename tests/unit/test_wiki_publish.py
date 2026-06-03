"""Tests for wiki publishing orchestration (mock publisher, no network)."""

import json
from pathlib import Path

import pytest

from src.pipeline import run_full_pipeline
from src.wiki.base import BaseWikiPublisher
from src.wiki.publish import publish_wiki


class MockPublisher(BaseWikiPublisher):
    """Records what would be published."""

    def __init__(self) -> None:
        self.published_dirs: list[Path] = []

    def publish(self, payload_dir: Path) -> None:
        self.published_dirs.append(payload_dir)


class TestPublishWiki:
    @pytest.fixture
    def analyzed_repo(self, test_repo: Path) -> Path:
        run_full_pipeline(test_repo)
        return test_repo

    def test_renders_then_publishes(self, analyzed_repo: Path):
        publisher = MockPublisher()
        bundle_dir = publish_wiki(analyzed_repo, publisher=publisher)

        assert publisher.published_dirs == [bundle_dir]
        assert (bundle_dir / "upload_manifest.json").exists()
        with open(bundle_dir / "upload_manifest.json") as f:
            manifest = json.load(f)
        assert manifest["pages"]

    def test_skip_render(self, analyzed_repo: Path):
        """publish_wiki(render=False) reuses an existing bundle."""
        publish_wiki(analyzed_repo, publisher=MockPublisher())  # initial render
        publisher = MockPublisher()
        publish_wiki(analyzed_repo, publisher=publisher, render=False)
        assert len(publisher.published_dirs) == 1


class TestMediaWikiPublisherCredentials:
    def test_missing_credentials_raise(self, test_repo: Path, monkeypatch):
        pytest.importorskip("mwclient", reason="publish extra not installed")
        from src.wiki.config import load_wiki_config
        from src.wiki.mediawiki_client import MediaWikiPublisher

        monkeypatch.delenv("MEDIAWIKI_BOT_USER", raising=False)
        monkeypatch.delenv("MEDIAWIKI_BOT_PASSWORD", raising=False)

        config = load_wiki_config(test_repo / "config" / "wiki.yaml")
        publisher = MediaWikiPublisher(config, test_repo)
        with pytest.raises(RuntimeError, match="MEDIAWIKI_BOT_USER"):
            publisher.connect()
