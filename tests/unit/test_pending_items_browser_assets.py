"""PEND-S1: browser asset fixture parity (no browser needed).

The theme CSS served by page.route interception must stay byte-identical
to the project stylesheet; refresh the pinned copy (or re-run
fetch_pinned_assets.py) whenever the theme changes.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = REPO_ROOT / "tests" / "fixtures" / "browser_assets"


def test_theme_fixture_matches_project_css() -> None:
    assert (ASSETS_DIR / "sirhosp-theme.css").read_bytes() == (
        REPO_ROOT / "static" / "css" / "sirhosp.css"
    ).read_bytes()
