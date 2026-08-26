"""Regression tests for browser tab titles (app name first).

Business rule: every page must render ``<title>Prisma — <Página></title>``.
The app name ("Prisma") must appear FIRST in the tab, controlled in a single
place (``templates/base.html``); child templates only override the
``page_title`` block with the page name (never the legacy ``title`` block,
which used to invert the order and even drop the app name on some pages).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.urls import reverse

BASE_DIR = Path(__file__).resolve().parents[2]

#: Root template dirs (project-level and per-app).
TEMPLATE_ROOTS = [
    BASE_DIR / "templates",
    *(p for p in sorted((BASE_DIR / "apps").glob("*/templates"))),
]

LEGACY_TITLE_RE = re.compile(r"\{%\s*block\s+title\s*%\}")


def _iter_html_templates() -> list[Path]:
    """All project .html templates (excludes .venv and admin overrides)."""
    files: list[Path] = []
    for root in TEMPLATE_ROOTS:
        files.extend(sorted(root.rglob("*.html")))
    return files


def _is_full_page(path: Path) -> bool:
    """Full-page template: not a partial (``_*.html``) nor an include."""
    if path.name.startswith("_"):
        return False
    return "includes" not in path.parts


def _iter_child_templates() -> list[tuple[Path, str]]:
    """Full-page templates that extend a base layout."""
    extended = {
        match.group(1)
        for path in _iter_html_templates()
        for match in re.finditer(
            r"\{%\s*extends\s+[\"']([^\"']+)[\"']\s*%\}",
            path.read_text(encoding="utf-8"),
        )
    }
    result: list[tuple[Path, str]] = []
    for path in _iter_html_templates():
        if not _is_full_page(path) or path.name == "base.html":
            continue
        text = path.read_text(encoding="utf-8")
        if "{% extends" in text:
            # Leaf pages only: intermediate layouts (e.g. base_sidebar.html)
            # are extended by others and may legitimately skip page_title.
            template_name = f"{path.parent.name}/{path.name}"
            if template_name in extended or path.name in extended:
                continue
            result.append((path, text))
    return result


class TestBaseTemplateTitle:
    """base.html owns the app name, page-first order is inverted."""

    def test_title_tag_starts_with_app_name(self) -> None:
        """<title> in base.html starts with the app name 'Prisma'."""
        text = (BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
        assert "<title>Prisma" in text

    def test_base_defines_page_title_block(self) -> None:
        """base.html exposes a 'page_title' block for child pages."""
        text = (BASE_DIR / "templates" / "base.html").read_text(encoding="utf-8")
        assert "{% block page_title %}" in text


class TestChildTemplatesUsePageTitle:
    """Every full-page template overrides only 'page_title'."""

    def test_every_child_defines_page_title_block(self) -> None:
        """All children extending a base define {% block page_title %}."""
        missing = [
            str(p.relative_to(BASE_DIR))
            for p, text in _iter_child_templates()
            if "{% block page_title %}" not in text
        ]
        assert not missing, f"Templates missing page_title block: {missing}"

    def test_no_template_uses_legacy_title_block(self) -> None:
        """No project template overrides {% block title %} anymore."""
        offenders = [
            str(p.relative_to(BASE_DIR))
            for p in _iter_html_templates()
            if LEGACY_TITLE_RE.search(p.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"Templates still using legacy title block: {offenders}"


@pytest.mark.django_db
class TestRenderedTitles:
    """Rendered pages keep the app name first in the <title> tag."""

    def test_hospital_flow_title(self, admin_client) -> None:
        response = admin_client.get(reverse("census:hospital_flow"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<title>Prisma — Fluxo Hospitalar</title>" in content

    def test_login_title(self, client) -> None:
        response = client.get("/login/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "<title>Prisma — Login</title>" in content

    def test_home_title(self, admin_client) -> None:
        response = admin_client.get("/")
        assert response.status_code == 200
        content = response.content.decode()
        assert (
            "<title>Prisma — Sistema de Relatórios Hospitalares</title>" in content
        )
