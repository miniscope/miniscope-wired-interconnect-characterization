"""
MediaWiki publisher: pushes the rendered bundle (derived/wiki/) to the
live wiki via a bot account.

Credentials come ONLY from environment variables (set as GitHub Actions
secrets) -- never from files in this repo:
    MEDIAWIKI_BOT_USER
    MEDIAWIKI_BOT_PASSWORD

The endpoint and page titles come from config/wiki.yaml. The mwclient
import is kept inside connect() so the rest of the package works without
the dependency installed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from src.wiki.base import BaseWikiPublisher
from src.wiki.config import WikiConfig

logger = logging.getLogger(__name__)

EDIT_SUMMARY = "Automated update from miniscope-wired-interconnect-characterization"

# MediaWiki rejects re-uploading a byte-identical file with this API error code.
# It is benign -- the image on the wiki is already current -- so it must NOT
# abort the publish; otherwise an unchanged plot (common: only the page text /
# scores changed) would stop the far more important page-text update.
_UNCHANGED_UPLOAD_CODE = "fileexists-no-change"


def _is_unchanged_upload(exc: Exception) -> bool:
    """True if an upload 'failed' only because the file is already up to date."""
    if getattr(exc, "code", None) == _UNCHANGED_UPLOAD_CODE:
        return True
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == _UNCHANGED_UPLOAD_CODE


class MediaWikiPublisher(BaseWikiPublisher):
    """Publishes pages + images from a rendered bundle directory."""

    def __init__(self, config: WikiConfig, repo_root: Path) -> None:
        self._config = config
        self._repo_root = repo_root
        self._site = None

    def connect(self) -> None:
        """Log in with the bot account. Raises on missing credentials."""
        import mwclient  # lazy: only needed when actually publishing

        user = os.environ.get("MEDIAWIKI_BOT_USER")
        password = os.environ.get("MEDIAWIKI_BOT_PASSWORD")
        if not user or not password:
            raise RuntimeError(
                "MEDIAWIKI_BOT_USER and MEDIAWIKI_BOT_PASSWORD must be set "
                "(GitHub Actions secrets) to publish to the wiki"
            )

        parsed = urlparse(self._config.api_url)
        path = parsed.path.removesuffix("api.php")
        self._site = mwclient.Site(parsed.netloc, path=path, scheme=parsed.scheme or "https")
        self._site.login(user, password)
        logger.info("Logged in to %s as %s", parsed.netloc, user)

    def publish(self, payload_dir: Path) -> None:
        """Upload all images and save all pages from the bundle."""
        if self._site is None:
            self.connect()

        manifest_path = payload_dir / "upload_manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        for image in manifest.get("images", []):
            local_path = self._repo_root / image["local_path"]
            if not local_path.exists():
                logger.warning("Skipping missing image %s", local_path)
                continue
            try:
                with open(local_path, "rb") as f:
                    self._site.upload(
                        f,
                        filename=image["wiki_name"],
                        description=EDIT_SUMMARY,
                        ignore=True,  # overwrite existing versions
                    )
                logger.info("Uploaded %s", image["wiki_name"])
            except Exception as exc:
                # An unchanged image is already current -- don't let MediaWiki's
                # 'fileexists-no-change' error abort the page-text updates below.
                if _is_unchanged_upload(exc):
                    logger.info("Image %s already current (unchanged)", image["wiki_name"])
                else:
                    raise

        for page in manifest.get("pages", []):
            text = (payload_dir / page["file"]).read_text(encoding="utf-8")
            self._site.pages[page["title"]].save(text, summary=EDIT_SUMMARY)
            logger.info("Saved page %s", page["title"])

        # Re-uploaded plots keep their filename, so the wiki keeps serving the
        # previously cached thumbnail (the 640px image embedded on the page) and
        # the page looks unchanged even though the underlying File was overwritten.
        # Purge the File pages (drops their stale thumbnails) and the content pages
        # (forcelinkupdate re-renders them) so the new plots actually show up.
        self._purge(
            [f"File:{image['wiki_name']}" for image in manifest.get("images", [])]
            + [page["title"] for page in manifest.get("pages", [])]
        )

    def _purge(self, titles: list[str]) -> None:
        """Best-effort cache purge so re-uploaded images become visible.

        A purge failure must never abort an otherwise-successful publish, so
        every call is wrapped; titles are batched (the API caps a purge at 50
        titles per call for non-bot accounts).
        """
        unique = list(dict.fromkeys(t for t in titles if t))
        for start in range(0, len(unique), 50):
            chunk = unique[start : start + 50]
            try:
                self._site.api("purge", titles="|".join(chunk), forcelinkupdate="1")
                logger.info("Purged %d page(s)/file(s)", len(chunk))
            except Exception as exc:
                logger.warning("Cache purge failed for %s: %s", chunk, exc)
