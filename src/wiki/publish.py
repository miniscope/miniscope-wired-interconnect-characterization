"""Orchestrate wiki publishing: render the bundle, then push it."""

from __future__ import annotations

import logging
from pathlib import Path

from src.wiki.base import BaseWikiPublisher
from src.wiki.config import load_wiki_config
from src.wiki.render import render_wiki

logger = logging.getLogger(__name__)


def publish_wiki(
    repo_root: Path,
    publisher: BaseWikiPublisher | None = None,
    render: bool = True,
) -> Path:
    """
    Render (optionally) and publish the wiki bundle.

    A custom publisher can be injected for testing; by default the real
    MediaWikiPublisher is constructed from config/wiki.yaml + env secrets.
    Returns the bundle directory.
    """
    if render:
        render_wiki(repo_root)

    bundle_dir = repo_root / "derived" / "wiki"
    if publisher is None:
        from src.wiki.mediawiki_client import MediaWikiPublisher

        config = load_wiki_config(repo_root / "config" / "wiki.yaml")
        publisher = MediaWikiPublisher(config, repo_root)

    publisher.publish(bundle_dir)
    return bundle_dir
