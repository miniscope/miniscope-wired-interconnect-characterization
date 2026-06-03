"""Typed access to config/wiki.yaml (publishing destinations, no secrets)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class WikiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_url: str = Field(description="MediaWiki api.php endpoint")
    main_page: str = Field(description="User-facing overview page title")
    profile_page_template: str = Field(
        description="Per-profile page title; {profile_id} is substituted"
    )
    image_prefix: str = Field(
        default="",
        description="Prefix for uploaded images to avoid wiki filename collisions",
    )

    def profile_page(self, profile_id: str) -> str:
        return self.profile_page_template.format(profile_id=profile_id)


def load_wiki_config(path: Path) -> WikiConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return WikiConfig.model_validate(raw)
