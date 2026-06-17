"""
Acquisition app entry point.

Run via `miniscope-char acquire` (or `python -m src.acquire.app`).
Pages register themselves on import; STATE carries the repo root and
operator name.
"""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from src.acquire.state import STATE


def build_app(repo_root: Path, simulate: bool | None = None) -> None:
    """Configure state and register all pages."""
    STATE.repo_root = repo_root.resolve()
    STATE.simulate = simulate

    # Importing the page modules registers their @ui.page routes.
    from src.acquire.pages import (  # noqa: F401
        landing,
        mass,
        miniscopes,
        profile,
        resistance,
        serdes,
        vna,
    )


def run_acquire(
    repo_root: Path,
    host: str = "127.0.0.1",
    port: int = 8081,  # 8080 is a frequent conflict on Windows; see cli.main
    simulate: bool | None = None,
) -> None:
    """Build and launch the app (blocking)."""
    build_app(repo_root, simulate=simulate)
    ui.run(
        host=host,
        port=port,
        title="Miniscope Cable Characterization",
        reload=False,
        show=True,
    )


if __name__ == "__main__":
    run_acquire(Path("."))
