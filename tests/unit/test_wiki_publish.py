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


class _ApiError(Exception):
    """Mimics mwclient's APIError: args[0] is the code, plus a .code attribute."""

    def __init__(self, code: str, info: str = "") -> None:
        super().__init__(code, info)
        self.code = code


class _FakeSite:
    """Records uploads + page saves; can be told to fail every upload."""

    def __init__(self, upload_error: Exception | None = None) -> None:
        self.uploaded: list[str] = []
        self.saved: list[tuple[str, str]] = []
        self._upload_error = upload_error
        self.pages = self._Pages(self.saved)

    def upload(self, f, filename, description="", ignore=False):
        self.uploaded.append(filename)
        if self._upload_error is not None:
            raise self._upload_error

    class _Pages:
        def __init__(self, saved: list) -> None:
            self._saved = saved

        def __getitem__(self, title: str):
            saved = self._saved

            class _Page:
                def save(self, text: str, summary: str = "") -> None:
                    saved.append((title, text))

            return _Page()


class TestMediaWikiPublisherUploads:
    """The upload step must tolerate unchanged images (the bug that left the live
    wiki's scores stale: an unchanged plot's 'fileexists-no-change' aborted the
    publish before the page text was updated)."""

    @pytest.fixture
    def analyzed_repo(self, test_repo: Path) -> Path:
        run_full_pipeline(test_repo)
        return test_repo

    def _publisher(self, repo: Path, site: _FakeSite):
        from src.wiki.config import load_wiki_config
        from src.wiki.mediawiki_client import MediaWikiPublisher

        pub = MediaWikiPublisher(load_wiki_config(repo / "config" / "wiki.yaml"), repo)
        pub._site = site  # inject the fake so connect()/network is skipped
        return pub

    def test_unchanged_image_does_not_abort_page_save(self, analyzed_repo: Path):
        site = _FakeSite(upload_error=_ApiError("fileexists-no-change", "exact duplicate"))
        pub = self._publisher(analyzed_repo, site)

        pub.publish(analyzed_repo / "derived" / "wiki")

        assert site.uploaded  # it attempted the image uploads
        assert site.saved  # ...and STILL saved the page text despite the "errors"

    def test_genuine_upload_error_still_raises(self, analyzed_repo: Path):
        site = _FakeSite(upload_error=_ApiError("badtoken", "auth failed"))
        pub = self._publisher(analyzed_repo, site)

        with pytest.raises(Exception, match="badtoken"):
            pub.publish(analyzed_repo / "derived" / "wiki")


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
