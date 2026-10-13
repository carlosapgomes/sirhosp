#!/usr/bin/env python3
"""SCAF-S1 D4 scenario: statistics collapse affordance browser verification.

Renders the real ``daily_report.html`` template with an entirely synthetic
in-memory projection (no database, no clinical systems, no PHI/PII) and
exercises the sector/category collapsibles in Chromium with the repository
CSS plus the Bootstrap/Icons versions pinned by ``base.html``.

Exit status: 0 when every check passes, 1 on a behavioral failure, 2 when
the browser or a required asset is unavailable (BLOCKED, never a skip).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent

import sys  # noqa: E402

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.template import loader  # noqa: E402
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ALLOWED_CDN_HOSTS = frozenset({"cdn.jsdelivr.net", "unpkg.com"})

DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
MOBILE_VIEWPORT = {"width": 375, "height": 812}

BAHIA = ZoneInfo("America/Bahia")


# ---------------------------------------------------------------------------
# Synthetic projection (in-memory only, no database, no real patient data)
# ---------------------------------------------------------------------------


def _synthetic_patient(suffix: str, *, record: str, patient_id: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        bed=f"SYN-{suffix}",
        name=f"PACIENTE SINTETICO {suffix}",
        record=record,
        specialty="CLI",
        patient_id=patient_id,
    )


def _synthetic_event(suffix: str) -> SimpleNamespace:
    return SimpleNamespace(
        event=SimpleNamespace(
            bed=f"SYN-{suffix}",
            name=f"PACIENTE SINTETICO {suffix}",
            record=f"SYN-{suffix}",
        ),
        patient_id=None,
        label="Transferência interna",
        origin_display="SETOR SINTETICO NORTE",
        destination_display="SETOR SINTETICO SUL",
        clinical_display="Momento clínico não informado",
        detection_display="01/09/2026 21:00 a 01/09/2026 21:30",
    )


def _synthetic_list(
    key: str, title: str, empty_label: str, *, events: int, patients: int, tag: str
) -> SimpleNamespace:
    rows = [_synthetic_event(f"{tag}-{index}") for index in range(events)]
    people = [
        _synthetic_patient(f"{tag}-{index}", record=f"SYN-{tag}-{index}")
        for index in range(patients)
    ]
    return SimpleNamespace(
        key=key,
        title=title,
        empty_label=empty_label,
        events=tuple(rows),
        patients=tuple(people),
        badge_count=len(rows) + len(people),
    )


def build_projection() -> SimpleNamespace:
    """Two sectors with the four usual lists plus the unknown section."""
    first_lists = (
        _synthetic_list(
            "entries",
            "Entradas",
            "Nenhuma entrada detectada neste setor.",
            events=0,
            patients=0,
            tag="E1",
        ),
        _synthetic_list(
            "exits",
            "Saídas",
            "Nenhuma saída detectada neste setor.",
            events=1,
            patients=0,
            tag="X1",
        ),
        _synthetic_list(
            "unidentified",
            "Eventos com origem ou destino não identificado",
            "Nenhum evento com origem ou destino não identificado neste setor.",
            events=2,
            patients=0,
            tag="U1",
        ),
        _synthetic_list(
            "patients",
            "Pacientes do fechamento",
            "Nenhum paciente do fechamento neste setor.",
            events=0,
            patients=2,
            tag="P1",
        ),
    )
    second_lists = (
        _synthetic_list(
            "entries",
            "Entradas",
            "Nenhuma entrada detectada neste setor.",
            events=1,
            patients=0,
            tag="E2",
        ),
        _synthetic_list(
            "exits",
            "Saídas",
            "Nenhuma saída detectada neste setor.",
            events=0,
            patients=0,
            tag="X2",
        ),
        _synthetic_list(
            "unidentified",
            "Eventos com origem ou destino não identificado",
            "Nenhum evento com origem ou destino não identificado neste setor.",
            events=0,
            patients=0,
            tag="U2",
        ),
        _synthetic_list(
            "patients",
            "Pacientes do fechamento",
            "Nenhum paciente do fechamento neste setor.",
            events=0,
            patients=1,
            tag="P2",
        ),
    )
    groups = (
        SimpleNamespace(
            key="north",
            stable_key="SYN-NORTH",
            title="SETOR SINTETICO NORTE",
            is_unknown_section=False,
            header_badges=(
                SimpleNamespace(label="Pacientes: 2", css="bg-primary"),
                SimpleNamespace(label="Capacidade: 10", css="bg-light text-dark border"),
            ),
            lists=first_lists,
        ),
        SimpleNamespace(
            key="south",
            stable_key="SYN-SOUTH",
            title="SETOR SINTETICO SUL",
            is_unknown_section=False,
            header_badges=(
                SimpleNamespace(label="Pacientes: 1", css="bg-primary"),
                SimpleNamespace(label="Capacidade: 8", css="bg-light text-dark border"),
            ),
            lists=second_lists,
        ),
        SimpleNamespace(
            key="unknown",
            stable_key="",
            title="Setor não identificado",
            is_unknown_section=True,
            header_badges=(
                SimpleNamespace(label="Eventos: 1", css="bg-secondary"),
                SimpleNamespace(label="Pacientes: 1", css="bg-primary"),
            ),
            lists=(
                SimpleNamespace(
                    key="unidentified",
                    title="Eventos sem setor identificado",
                    empty_label="Nenhum evento sem setor identificado.",
                    events=tuple([_synthetic_event("UU")]),
                    patients=tuple(),
                    badge_count=1,
                ),
                SimpleNamespace(
                    key="patients",
                    title="Pacientes sem setor identificado",
                    empty_label="Nenhum paciente sem setor identificado.",
                    events=tuple(),
                    patients=tuple(
                        [_synthetic_patient("UU", record="SYN-UU", patient_id=None)]
                    ),
                    badge_count=1,
                ),
            ),
        ),
    )
    report = SimpleNamespace(
        local_date=date(2026, 9, 1),
        revision=1,
        opening_run=SimpleNamespace(
            finished_at=datetime(2026, 9, 1, 0, 30, tzinfo=BAHIA)
        ),
        closing_run=SimpleNamespace(
            finished_at=datetime(2026, 9, 1, 21, 30, tzinfo=BAHIA)
        ),
        closing_run_id=7,
        catalog=SimpleNamespace(effective_from=date(2026, 1, 1)),
        algorithm_version="synthetic-scaf-s1",
    )
    return SimpleNamespace(
        report=report,
        groups=groups,
        quality_warnings=("synthetic_warning",),
    )


def render_page() -> str:
    template = loader.get_template("statistics_reports/daily_report.html")
    return template.render(
        {"projection": build_projection(), "selected_date": date(2026, 9, 1)}
    )


# ---------------------------------------------------------------------------
# Local server: repository statics only; everything else 204/404
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    page: bytes = b""

    def log_message(self, *args: Any) -> None:  # noqa: ANN002, ANN003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = type(self).page
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/static/"):
            target = (REPO_ROOT / self.path.lstrip("/")).resolve()
            statics = (REPO_ROOT / "static").resolve()
            if target.is_file() and target.is_relative_to(statics):
                body = target.read_bytes()
                self.send_response(200)
                if target.suffix == ".css":
                    self.send_header("Content-Type", "text/css; charset=utf-8")
                elif target.suffix == ".svg":
                    self.send_header("Content-Type", "image/svg+xml")
                else:
                    self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        self.send_response(204)
        self.end_headers()


# ---------------------------------------------------------------------------
# Check bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    output_dir: Path
    checks: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def check(
        self, check_id: str, viewport: str, description: str, ok: bool, detail: str = ""
    ) -> bool:
        self.checks.append(
            {
                "id": check_id,
                "viewport": viewport,
                "description": description,
                "status": "pass" if ok else "fail",
                "detail": detail,
            }
        )
        return ok


ANGLE_JS = """el => {
  const t = getComputedStyle(el).transform;
  if (!t || t === 'none') return 0.0;
  const m = t.match(/matrix\\(([^)]+)\\)/);
  if (!m) return 0.0;
  const v = m[1].split(',').map(Number);
  return Math.atan2(v[1], v[0]) * 180 / Math.PI;
}"""

FREE_POINT_JS = """el => {
  const r = el.getBoundingClientRect();
  const kids = [...el.querySelectorAll(':scope > span, :scope > i')].map(k => {
    const b = k.getBoundingClientRect();
    return {left: b.left - r.left, right: b.right - r.left};
  }).filter(b => b.right > b.left).sort((a, b) => a.left - b.left);
  const edges = [0].concat(kids.flatMap(b => [b.left, b.right])).concat([r.width]);
  let best = null;
  for (let i = 0; i + 1 < edges.length; i += 2) {
    const a = edges[i], b = edges[i + 1];
    if (b - a >= 6 && (!best || b - a > best.w)) best = {x: (a + b) / 2, w: b - a};
  }
  if (best) return {x: r.left + best.x, y: r.top + r.height / 2, free: true};
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, free: false};
}"""

NEUTRAL_JS = """() => { if (document.activeElement) document.activeElement.blur(); }"""


def _norm_angle(value: float) -> float:
    while value > 180:
        value -= 360
    while value <= -180:
        value += 360
    return value


def _is_closed_angle(value: float) -> bool:
    return abs(_norm_angle(value)) <= 6


def _is_open_angle(value: float) -> bool:
    return 80 <= _norm_angle(value) <= 100


def _icon_angle(page: Any, target: str) -> float | None:
    """Computed rotation of one toggle chevron, or None when absent."""
    icon = page.locator(f"button[data-bs-target='#{target}'] i.bi-chevron-right")
    if icon.count() != 1:
        return None
    return icon.evaluate(ANGLE_JS)


# ---------------------------------------------------------------------------
# Viewport run
# ---------------------------------------------------------------------------


def run_viewport(  # noqa: PLR0915
    scenario: Scenario,
    browser: Any,
    base_url: str,
    viewport: dict[str, int],
    name: str,
    *,
    reduced_motion: bool,
    guard: Any,
) -> bool:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    context = browser.new_context(
        viewport=viewport, reduced_motion="reduce" if reduced_motion else None
    )
    context.route("**/*", guard)
    page = context.new_page()
    ok = True

    def record(check_id: str, description: str, passed: bool, detail: str = "") -> bool:
        nonlocal ok
        ok = scenario.check(check_id, name, description, passed, detail) and ok
        return passed

    try:
        page.goto(base_url, wait_until="load")
        page.wait_for_function("typeof bootstrap !== 'undefined'", timeout=15000)
        page.wait_for_function(
            "document.fonts.check('16px \"bootstrap-icons\"')", timeout=15000
        )
        page.wait_for_selector("button[data-bs-target^='#statistics-']", timeout=15000)

        toggles = page.locator("button[data-bs-target^='#statistics-']")
        toggle_count = toggles.count()
        expected_toggles = sum(
            1 + len(group.lists) for group in build_projection().groups
        )
        record(
            "controls-present",
            "statistics toggles are rendered",
            toggle_count == expected_toggles,
            f"count={toggle_count} expected={expected_toggles}",
        )
        sector_targets = [
            "statistics-sector-north",
            "statistics-sector-south",
            "statistics-sector-unknown",
        ]
        first_list = "statistics-list-north-exits"

        # -- R1/R5: initial state is collapsed ------------------------------
        initial = True
        for target in sector_targets:
            expanded = page.locator(
                f"button[data-bs-target='#{target}']"
            ).get_attribute("aria-expanded")
            shown = page.locator(f"#{target}.show").count()
            if expanded != "false" or shown != 0:
                initial = False
        record(
            "initial-collapsed",
            "every sector starts collapsed",
            initial,
            "",
        )

        # -- asset: icon font really applied ---------------------------------
        font_ok = page.evaluate(
            "() => { const el = document.querySelector("
            "'button[data-bs-target] i.bi-chevron-right');"
            " if (!el) return false;"
            " const fam = getComputedStyle(el, '::before').fontFamily || '';"
            " return fam.includes('bootstrap-icons'); }"
        )
        if not font_ok:
            scenario.blocked_reason = "bootstrap-icons font not applied"
            return False

        # -- R1: closed chevrons point right --------------------------------
        for target in sector_targets:
            angle = _icon_angle(page, target)
            record(
                "chevron-closed",
                f"closed chevron points right on {target}",
                angle is not None and _is_closed_angle(angle),
                f"angle={angle}",
            )

        # Icons inside a collapsed sector have no box; open every sector now
        # (their own lists stay collapsed) before measuring every control.
        for target in sector_targets:
            _open_target(page, target)

        # -- R1: every control shows a visible decorative chevron -----------
        for index in range(toggle_count):
            toggle = toggles.nth(index)
            target = toggle.get_attribute("data-bs-target")
            icon = toggle.locator("i.bi-chevron-right")
            present = icon.count() == 1
            box = icon.bounding_box() if present else None
            visible = bool(box and box["width"] > 0 and box["height"] > 0)
            hidden = icon.get_attribute("aria-hidden") == "true" if present else False
            record(
                "chevron-present",
                f"chevron is visible and decorative on {target}",
                present and visible and hidden,
                f"target={target} present={present} visible={visible} "
                f"aria-hidden-ok={hidden}",
            )

        projection = build_projection()
        category_targets = [
            (
                f"statistics-sector-{group.key}",
                f"statistics-list-{group.key}-{section.key}",
            )
            for group in projection.groups
            for section in group.lists
        ]

        # -- R1: sector cycles right -> down -> right (every sector) --------
        for target in sector_targets:
            if not _cycle(scenario, page, name, target, record):
                ok = False

        # -- R1: an open parent must not rotate closed-child icons ---------
        # Every sector, including the unknown group: open the parent with
        # all children closed, then prove each closed child still points
        # right.
        for group in projection.groups:
            sector_target = f"statistics-sector-{group.key}"
            _open_target(page, sector_target)
            for section in group.lists:
                _close_target(page, f"statistics-list-{group.key}-{section.key}")
            _open_target(page, sector_target)
            for section in group.lists:
                child = f"statistics-list-{group.key}-{section.key}"
                child_angle = _icon_angle(page, child)
                record(
                    "child-stable",
                    f"opening the sector keeps closed child {child} pointing right",
                    child_angle is not None and _is_closed_angle(child_angle),
                    f"angle={child_angle}",
                )

        # -- R1: category cycles right -> down -> right (every category) ---
        # The unknown group is included; each parent is opened first so the
        # child toggle is laid out and clickable.
        for sector_target, category_target in category_targets:
            _open_target(page, sector_target)
            if not _cycle(scenario, page, name, category_target, record):
                ok = False

        # -- R5: independence -----------------------------------------------
        _open_target(page, "statistics-sector-north")
        _open_target(page, first_list)
        _open_target(page, "statistics-sector-south")
        north_open = _is_open(page, "statistics-sector-north")
        child_open = _is_open(page, first_list)
        record(
            "independent-sectors",
            "opening a second sector keeps the first sector and child open",
            north_open and child_open,
            f"north={north_open} child={child_open}",
        )
        _open_target(page, "statistics-list-north-unidentified")
        both_open = _is_open(page, first_list) and _is_open(
            page, "statistics-list-north-unidentified"
        )
        record(
            "independent-categories",
            "two categories of one sector stay open together",
            both_open,
            "",
        )

        # -- R5: collapsing and reopening the parent preserves the child ---
        _close_target(page, "statistics-sector-north")
        _open_target(page, "statistics-sector-north")
        preserved = _is_open(page, first_list)
        preserved_angle = _icon_angle(page, first_list)
        record(
            "child-preserved",
            "reopening the sector preserves the open child and its chevron",
            preserved
            and preserved_angle is not None
            and _is_open_angle(preserved_angle),
            f"open={preserved} angle={preserved_angle}",
        )

        # -- R3: keyboard + visible focus + free-area click (both levels) --
        _keyboard_and_pointer_checks(
            scenario,
            page,
            "statistics-sector-south",
            "statistics-sector-north",
            "sector",
            record,
        )
        _keyboard_and_pointer_checks(
            scenario,
            page,
            first_list,
            "statistics-sector-north",
            "category",
            record,
            parent_target="statistics-sector-north",
        )

        # -- R3: minimum 44px height -----------------------------------------
        # Every sector is open here, so every list toggle is laid out.
        for target in sector_targets:
            _open_target(page, target)
        heights_ok = True
        measured = 0
        for index in range(toggle_count):
            candidate = toggles.nth(index)
            if not candidate.is_visible():
                heights_ok = False
                record(
                    "min-height",
                    "control height is at least 44px",
                    False,
                    f"index={index} not visible after opening all sectors",
                )
                continue
            box = candidate.bounding_box()
            height = box["height"] if box else 0
            measured += 1
            if height < 44:
                heights_ok = False
                record(
                    "min-height",
                    "control height is at least 44px",
                    False,
                    f"index={index} height={height:.1f}",
                )
        if heights_ok:
            record(
                "min-height",
                "every control is at least 44px tall",
                True,
                f"measured={measured}",
            )

        # -- R2: neutral backgrounds without hover/focus ---------------------
        _close_target(page, first_list)
        page.mouse.move(4, 4)
        page.evaluate(NEUTRAL_JS)
        page.wait_for_timeout(150)
        cat_style = page.locator(
            f"button[data-bs-target='#{first_list}']"
        ).evaluate(
            """el => { const s = getComputedStyle(el);
               return {bg: s.backgroundColor, border: s.borderTopColor,
                       borderW: s.borderTopWidth}; }"""
        )
        neutral_bg = cat_style["bg"] not in ("rgba(0, 0, 0, 0)", "transparent")
        neutral_border = cat_style["borderW"] not in ("0px", "")
        record(
            "category-neutral",
            "categories show background and border without hover",
            neutral_bg and neutral_border,
            f"{cat_style}",
        )
        sector_bg = page.locator(
            "button[data-bs-target='#statistics-sector-north']"
        ).evaluate("el => getComputedStyle(el).backgroundColor")
        record(
            "hierarchy",
            "sector header keeps a distinct background from categories",
            sector_bg != cat_style["bg"],
            f"sector={sector_bg} category={cat_style['bg']}",
        )
        _open_target(page, first_list)
        page.mouse.move(4, 4)
        page.evaluate(NEUTRAL_JS)
        page.wait_for_timeout(300)
        open_bg = page.locator(
            f"button[data-bs-target='#{first_list}']"
        ).evaluate("el => getComputedStyle(el).backgroundColor")
        record(
            "open-distinct",
            "an open category differs neutrally from its closed state",
            open_bg != cat_style["bg"],
            f"closed={cat_style['bg']} open={open_bg}",
        )

        # -- R4: long title geometry on every viewport -----------------------
        long_target = "statistics-list-north-unidentified"
        geo = page.locator(f"button[data-bs-target='#{long_target}']").evaluate(
            """el => {
              const r = el.getBoundingClientRect();
              const icon = el.querySelector('i.bi-chevron-right');
              const badge = el.querySelector(':scope > span.badge, :scope span.badge:last-child');
              const out = {button: {left: r.left, right: r.right, top: r.top,
                                    bottom: r.bottom, width: r.width},
                           scrollW: el.scrollWidth, clientW: el.clientWidth};
              if (icon) { const b = icon.getBoundingClientRect();
                out.icon = {left: b.left, right: b.right, top: b.top,
                            bottom: b.bottom, width: b.width}; }
              if (badge) { const b = badge.getBoundingClientRect();
                out.badge = {left: b.left, right: b.right, top: b.top,
                             bottom: b.bottom, width: b.width}; }
              return out; }"""
        )
        icon_ok = bool(geo.get("icon") and geo["icon"]["width"] > 0)
        badge_ok = bool(geo.get("badge") and geo["badge"]["width"] > 0)
        no_overlap = True
        if icon_ok and badge_ok:
            no_overlap = geo["icon"]["right"] <= geo["badge"]["left"] + 1
        no_overflow = geo["scrollW"] <= geo["clientW"] + 1
        page_overflow = page.evaluate(
            "() => document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 1"
        )
        record(
            "long-title-geometry",
            "long title keeps icon and badge intact without overflow",
            icon_ok and badge_ok and no_overlap and no_overflow and page_overflow,
            f"{geo} page_overflow_ok={page_overflow}",
        )

        # -- R5: statistics styles do not reach the sidebar ------------------
        sidebar_icon = page.locator("a[href='#sidebar-setores'] i.bi-chevron-down")
        sidebar_transform = sidebar_icon.evaluate(
            "el => getComputedStyle(el).transform"
        )
        sidebar_clean = page.evaluate(
            "() => { const link = document.querySelector("
            "\"a[href='#sidebar-setores']\");"
            " return link && !link.classList.contains('sirhosp-stats-toggle')"
            "  && !link.querySelector('.collapse-icon'); }"
        )
        record(
            "sidebar-isolated",
            "statistics styles do not alter the sidebar collapse",
            sidebar_transform in ("none", "")
            and bool(sidebar_clean),
            f"transform={sidebar_transform}",
        )

        shot = scenario.output_dir / f"screenshot-{name}.png"
        page.screenshot(path=str(shot), full_page=True)
        scenario.screenshots.append(shot.name)
    except PlaywrightTimeoutError as exc:
        scenario.check(
            "harness-timeout", name, "scenario step completed", False, str(exc)[:300]
        )
        ok = False
    finally:
        context.close()
    return ok


def _is_open(page: Any, target: str) -> bool:
    button = page.locator(f"button[data-bs-target='#{target}']")
    expanded = button.get_attribute("aria-expanded") == "true"
    shown = page.locator(f"#{target}.show").count() == 1
    visible = page.locator(f"#{target}").is_visible()
    return expanded and shown and visible


def _neutralize(page: Any) -> None:
    page.mouse.move(4, 4)
    page.evaluate(NEUTRAL_JS)
    page.wait_for_timeout(350)


def _open_target(page: Any, target: str) -> None:
    if _is_open(page, target):
        return
    page.locator(f"button[data-bs-target='#{target}']").click()
    page.wait_for_function(
        f"document.querySelector('#{target}').classList.contains('show')", timeout=5000
    )
    _wait_stable(page, target)
    _neutralize(page)


def _close_target(page: Any, target: str) -> None:
    if not _is_open(page, target):
        return
    page.locator(f"button[data-bs-target='#{target}']").click()
    page.wait_for_function(
        f"!document.querySelector('#{target}').classList.contains('show')", timeout=5000
    )
    _wait_stable(page, target)
    _neutralize(page)


def _wait_stable(page: Any, target: str) -> None:
    """Wait until Bootstrap finishes the collapse transition of one target.

    Toggling again while ``.collapsing`` is present is swallowed, so the
    next click must only happen after the transition settles.
    """
    page.wait_for_function(
        f"!document.querySelector('#{target}.collapsing')", timeout=5000
    )


def _cycle(
    scenario: Scenario,
    page: Any,
    name: str,
    target: str,
    record: Any,
) -> bool:
    _close_target(page, target)
    _open_target(page, target)
    opened = _is_open(page, target)
    angle = _icon_angle(page, target)
    opened_ok = record(
        "chevron-open",
        f"open chevron points down on {target}",
        opened and angle is not None and _is_open_angle(angle),
        f"open={opened} angle={angle}",
    )
    _close_target(page, target)
    closed = not _is_open(page, target)
    back_angle = _icon_angle(page, target)
    closed_ok = record(
        "chevron-reclose",
        f"reclosed chevron points right again on {target}",
        closed and back_angle is not None and _is_closed_angle(back_angle),
        f"closed={closed} angle={back_angle}",
    )
    return opened_ok and closed_ok


def _has_visible_focus(focus_style: dict[str, str]) -> bool:
    """Whether a computed focus style is actually perceivable."""
    outline = focus_style.get("outline", "none/0px")
    parts = outline.split("/")
    if parts[0] not in ("none", "") and len(parts) > 1 and parts[1] != "0px":
        return True
    shadow = (focus_style.get("shadow") or "").strip()
    if shadow in ("", "none"):
        return False
    transparent_zero = re.fullmatch(
        r"(rgba\(0,\s*0,\s*0,\s*0\)|transparent)(\s+0px)+", shadow
    )
    return transparent_zero is None


HIT_JS = """([x, y]) => {
  const el = document.elementFromPoint(x, y);
  const btn = el && el.closest
    ? el.closest("button[data-bs-target^='#statistics-']")
    : null;
  return btn ? btn.getAttribute('data-bs-target') : null;
}"""


def _ensure_hittable(
    page: Any, button: Any, target: str, point: dict[str, Any]
) -> dict[str, Any]:
    """Re-query a free-area point that really lands on the button.

    A sticky topbar can cover a button scrolled to the viewport edge; in
    that case center the button first and recompute the point.
    """
    wanted = f"#{target}"
    if page.evaluate(HIT_JS, [point["x"], point["y"]]) == wanted:
        return point
    button.evaluate("el => el.scrollIntoView({block: 'center'})")
    fresh = button.evaluate(FREE_POINT_JS)
    if page.evaluate(HIT_JS, [fresh["x"], fresh["y"]]) == wanted:
        return fresh
    fresh["free"] = False
    return fresh


def _keyboard_and_pointer_checks(
    scenario: Scenario,
    page: Any,
    target: str,
    from_target: str,
    kind: str,
    record: Any,
    *,
    parent_target: str | None = None,
) -> None:
    """Visible focus, Enter/Space toggle and free-area click for one control.

    ``kind`` is only a human label ("sector"/"category") used in the check
    descriptions; ``parent_target`` is opened first for category controls
    so the child toggle is laid out and clickable.
    """
    if parent_target is not None:
        _open_target(page, parent_target)
    _close_target(page, target)
    if parent_target is not None:
        _open_target(page, parent_target)
    button = page.locator(f"button[data-bs-target='#{target}']")
    focused = _focus_for_keyboard(page, from_target, button)
    # The focus ring itself transitions in; read it only after settling.
    page.wait_for_timeout(400)
    focus_style = button.evaluate(
        """el => { const s = getComputedStyle(el);
           return {outline: s.outlineStyle + '/' + s.outlineWidth,
                   shadow: s.boxShadow}; }"""
    )
    focus_visible = _has_visible_focus(focus_style)
    record(
        "focus-visible",
        f"keyboard focus is visible on a {kind} control ({target})",
        focused and focus_visible,
        f"{focus_style}",
    )
    before = _is_open(page, target)
    page.keyboard.press("Enter")
    page.wait_for_function(
        f"document.querySelector('#{target}').classList.contains('show')",
        timeout=5000,
    )
    _wait_stable(page, target)
    after_enter = _is_open(page, target)
    page.keyboard.press(" ")
    page.wait_for_function(
        f"!document.querySelector('#{target}').classList.contains('show')",
        timeout=5000,
    )
    _wait_stable(page, target)
    after_space = _is_open(page, target)
    record(
        "keyboard-toggle",
        f"Enter opens and Space closes the focused {kind} ({target})",
        (not before) and after_enter and (not after_space),
        f"before={before} enter={after_enter} space={after_space}",
    )
    point = button.evaluate(FREE_POINT_JS)
    page.mouse.move(4, 4)
    page.evaluate(NEUTRAL_JS)
    button.scroll_into_view_if_needed()
    point = button.evaluate(FREE_POINT_JS)
    point = _ensure_hittable(page, button, target, point)
    page.mouse.click(point["x"], point["y"])
    page.wait_for_function(
        f"document.querySelector('#{target}').classList.contains('show')",
        timeout=5000,
    )
    free_clicked = _is_open(page, target)
    record(
        "free-area-click",
        f"clicking the free area of the {kind} button toggles it ({target})",
        free_clicked,
        f"free={point['free']}",
    )


def _focus_for_keyboard(page: Any, from_target: str, button: Any) -> bool:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    button.scroll_into_view_if_needed()
    # Start from the nearby sector toggle so keyboard navigation is short
    # and deterministic; Tab keeps :focus-visible applied to the target.
    # Each Tab is followed by an explicit wait: reading activeElement
    # immediately races key processing and yields a stale element.
    page.locator(f"button[data-bs-target='#{from_target}']").focus()
    wanted = button.get_attribute("data-bs-target")
    for _ in range(8):
        current = page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute("
            "'data-bs-target')"
        )
        page.keyboard.press("Tab")
        try:
            page.wait_for_function(
                "prev => document.activeElement && document.activeElement."
                "getAttribute('data-bs-target') !== prev",
                arg=current,
                timeout=3000,
            )
        except PlaywrightTimeoutError:
            continue
        focused = page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute("
            "'data-bs-target')"
        )
        if focused == wanted:
            return True
    try:
        button.focus(timeout=2000)
    except PlaywrightTimeoutError:
        return False
    return (
        page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute("
            "'data-bs-target')"
        )
        == wanted
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "SCAF-S1 D4: verify statistics collapse affordance with the real "
            "template and assets (synthetic data only)."
        )
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory receiving screenshots and result.json (created if needed).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scenario = Scenario(output_dir=output_dir)

    try:
        html = render_page()
    except Exception as exc:  # noqa: BLE001
        scenario.blocked_reason = f"template render failed: {exc}"
        _write_result(scenario, status="blocked", commands=[f"render: {exc}"])
        print(f"BLOCKED: {scenario.blocked_reason}")
        return 2

    _Handler.page = html.encode("utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}/"
    requested: list[dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except PlaywrightError as exc:
                scenario.blocked_reason = f"browser launch failed: {exc}"
                _write_result(scenario, status="blocked", commands=[str(exc)[:300]])
                print(f"BLOCKED: {scenario.blocked_reason}")
                return 2

            try:
                browser.new_page().close()
            except PlaywrightError as exc:  # noqa: BLE001
                scenario.blocked_reason = f"browser unavailable: {exc}"
                _write_result(scenario, status="blocked", commands=[str(exc)[:300]])
                print(f"BLOCKED: {scenario.blocked_reason}")
                try:
                    browser.close()
                except PlaywrightError:
                    pass
                return 2

            # Route guard: repository page plus pinned CDNs only. Clinical
            # navigation, HTMX polling targets and any other origin are
            # blocked; the scenario never leaves this allowlist.
            def _guard(route: Any) -> None:
                url = route.request.url
                host = route.request.url.split("/")[2] if "://" in url else ""
                if url.startswith(base_url):
                    requested.append({"url": url, "action": "served-locally"})
                    route.continue_()
                elif host in ALLOWED_CDN_HOSTS:
                    requested.append({"url": url, "action": "allowed-cdn"})
                    route.continue_()
                else:
                    requested.append({"url": url, "action": "blocked"})
                    route.abort()

            desktop_ok = run_viewport(
                scenario, browser, base_url, DESKTOP_VIEWPORT, "desktop",
                reduced_motion=False, guard=_guard,
            )
            mobile_ok = run_viewport(
                scenario, browser, base_url, MOBILE_VIEWPORT, "mobile",
                reduced_motion=True, guard=_guard,
            )
            # Attach the guard report: prove real assets were used.
            scenario.assets = requested
            try:
                browser.close()
            except PlaywrightError:
                pass
            void_ok = desktop_ok and mobile_ok
    finally:
        server.shutdown()
        thread.join(timeout=5)

    if scenario.blocked_reason:
        _write_result(scenario, status="blocked", commands=[scenario.blocked_reason])
        print(f"BLOCKED: {scenario.blocked_reason}")
        return 2

    urls = [entry["url"] for entry in requested]
    cdn_urls = [url for url in urls if "cdn.jsdelivr.net" in url or "unpkg.com" in url]
    saw_bootstrap_css = any("bootstrap@5.3.3" in url and url.endswith(".css") for url in cdn_urls)
    saw_bootstrap_js = any("bootstrap@5.3.3" in url and url.endswith(".js") for url in cdn_urls)
    saw_icons = any("bootstrap-icons@1.11.3" in url for url in cdn_urls)
    saw_local_css = any(url.endswith("/static/css/sirhosp.css") for url in urls)
    assets_ok = saw_bootstrap_css and saw_bootstrap_js and saw_icons and saw_local_css
    if not assets_ok:
        _write_result(
            scenario,
            status="blocked",
            commands=[f"missing real assets: {requested}"],
        )
        print("BLOCKED: required real assets were not all loaded")
        return 2

    failures = [check for check in scenario.checks if check["status"] != "pass"]
    status = "pass" if (void_ok and not failures) else "behavioral-failure"
    invocation = f"{sys.executable} {' '.join(sys.argv)}"
    _write_result(scenario, status=status, commands=[invocation])
    print(
        f"checks={len(scenario.checks)} failures={len(failures)} "
        f"screenshots={scenario.screenshots} status={status}"
    )
    return 0 if status == "pass" else 1


def _write_result(scenario: Scenario, *, status: str, commands: list[str]) -> None:
    payload = {
        "scenario": "SCAF-S1 D4 statistics collapse affordance",
        "data": "synthetic-only",
        "status": status,
        "viewports": {"desktop": DESKTOP_VIEWPORT, "mobile": MOBILE_VIEWPORT},
        "commands": commands,
        "checks": scenario.checks,
        "assets": scenario.assets,
        "screenshots": scenario.screenshots,
        "blocked_reason": scenario.blocked_reason,
        "generated_at_epoch": math.floor(time.time()),
    }
    (scenario.output_dir / "result.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
