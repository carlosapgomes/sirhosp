"""PEND-S1: D9 browser harness and contextual pending-items journey.

Harness: pytest-django ``live_server`` + PostgreSQL test database + real
login through the site form. Every CDN URL from the shell is intercepted
by ``page.route`` and fulfilled with the pinned local fixtures in
``tests/fixtures/browser_assets/`` (correct MIME, versions preserved);
any other external request is aborted, so there is no silent fallback
to the network or simulated JS.

When a fixture is absent the suite fails closed with infrastructure
instructions (run ``fetch_pinned_assets.py`` with network access). A
browser/asset/login failure is an infrastructure block, never product
evidence and never a skip.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from playwright.sync_api import Browser, Page, ViewportSize, sync_playwright

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    GROUP_NAME,
    OUTRO_SLUG,
    PendingItemType,
)

TZ = ZoneInfo("America/Bahia")
ASSETS_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "browser_assets"
)

# Shell CDN URL -> (fixture filename, MIME type). URLs are verbatim from
# templates/base.html; the theme CSS is served from the pinned local copy.
PINNED_ROUTES: tuple[tuple[str, str, str], ...] = (
    (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        "bootstrap-5.3.3.min.css",
        "text/css",
    ),
    (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
        "bootstrap-icons-1.11.3.css",
        "text/css",
    ),
    (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
        "bootstrap-5.3.3.bundle.min.js",
        "text/javascript",
    ),
    ("https://unpkg.com/htmx.org@2.0.4", "htmx-2.0.4.js", "text/javascript"),
    ("**/static/css/sirhosp.css", "sirhosp-theme.css", "text/css"),
)

# Icon font binaries referenced (with a cache-busting query) by the pinned
# icons CSS. Trailing ``*`` absorbs the query string. The woff route is
# registered first: ``bootstrap-icons.woff*`` also matches ``.woff2`` URLs,
# and later routes take precedence, so woff2 must win for its own URLs.
# Fonts load lazily, so they stay out of the harness-minimum assertion;
# the journey forces and proves the woff2 load instead.
FONT_ROUTES: tuple[tuple[str, str, str], ...] = (
    (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff*",
        "bootstrap-icons.woff",
        "font/woff",
    ),
    (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2*",
        "bootstrap-icons.woff2",
        "font/woff2",
    ),
)

ALL_ROUTES: tuple[tuple[str, str, str], ...] = PINNED_ROUTES + FONT_ROUTES


class BrowserInfrastructureBlocked(RuntimeError):
    """Pinned browser fixtures are unavailable in this environment."""


def _load_fixtures() -> dict[str, tuple[bytes, str]]:
    """Read every pinned fixture or fail closed with instructions."""
    missing = [
        filename
        for _, filename, _ in ALL_ROUTES
        if not (ASSETS_DIR / filename).is_file()
    ]
    if missing:
        raise BrowserInfrastructureBlocked(
            "Browser fixtures ausentes: "
            + ", ".join(missing)
            + ". Rode com acesso a rede: "
            "python tests/fixtures/browser_assets/fetch_pinned_assets.py"
        )
    payloads: dict[str, tuple[bytes, str]] = {}
    for _, filename, mime in ALL_ROUTES:
        payloads[filename] = ((ASSETS_DIR / filename).read_bytes(), mime)
    return payloads


@pytest.fixture(autouse=True)
def _allow_sync_django_under_playwright_loop(monkeypatch):
    """Scope DJANGO_ALLOW_ASYNC_UNSAFE to this module's tests.

    ``sync_playwright`` runs an asyncio loop on the test thread for the
    whole journey, so Django's async-unsafe detector would reject the
    sequential, single-threaded ORM setup calls these tests make from
    the body. This is the Django-documented test escape, restricted to
    this module; the detector stays enabled everywhere else.
    """
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "1")


@pytest.fixture
def routed_browser_page():
    """Yield a (page, served) factory bound to one Chromium instance.

    The ``with sync_playwright()`` block keeps the driver loop confined
    to this fixture: it starts at setup and stops at teardown, so no
    running loop leaks into other tests in the same session.
    """
    payloads = _load_fixtures()
    served: list[str] = []
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch()
        try:

            def _new_page(
                viewport: ViewportSize | None = None,
            ) -> Page:
                if viewport is None:
                    viewport = {"width": 1280, "height": 800}
                page = browser.new_page(viewport=viewport)
                # Abort-all first: later specific routes take precedence,
                # so anything not pinned fails loudly instead of hitting
                # the network. Plain http stays allowed for live_server.
                page.route("https://**", lambda route: route.abort())
                for url, filename, mime in ALL_ROUTES:
                    body, _ = payloads[filename]

                    def _fulfill(route, *rest, _body=body, _mime=mime, _url=url):
                        # ``*rest`` absorbs the optional second handler
                        # argument (``route.request``): a second positional
                        # parameter would otherwise bind the Request object
                        # to ``_body`` and break fulfillment serialization.
                        served.append(_url)
                        route.fulfill(
                            status=200, body=_body, content_type=_mime
                        )

                    page.route(url, _fulfill)
                return page

            yield _new_page, served
        finally:
            browser.close()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _ensure_bootstrap() -> None:
    """Recreate the migration-bootstrapped rows these journeys need.

    ``django_db(transaction=True)`` flushes the database between tests,
    which also removes rows created by data migrations (the
    ``Desospitalização`` group and the ``Outro`` type). The HTTP suite
    keeps proving the migration bootstrap with plain ``.get``; here the
    journeys only need the rows to exist, so recreate them idempotently.
    """
    Group.objects.get_or_create(name=GROUP_NAME)
    PendingItemType.objects.get_or_create(
        slug=OUTRO_SLUG, defaults={"name": "Outro"}
    )


def _make_writer(username: str = "browser_writer") -> User:
    _ensure_bootstrap()
    user = User.objects.create_user(username=username, password="pw123456")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    return user


def _make_reader(username: str = "browser_reader") -> User:
    return User.objects.create_user(username=username, password="pw123456")


def _make_eligible_admission(key: str = "P_BROWSER_1") -> Admission:
    patient = Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )
    admission = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM_{key}",
        admission_date=_dt("2026-06-01T08:00:00"),
    )
    CensusSnapshot.objects.create(
        captured_at=_dt("2026-06-10T08:00:00"),
        setor="CLINICA MEDICA",
        leito="L01",
        prontuario=key,
        nome="PACIENTE SINTETICO",
        bed_status=BedStatus.OCCUPIED,
    )
    return admission


def _login(page: Page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}/login/", wait_until="domcontentloaded")
    page.fill("#id_username", username)
    page.fill("#id_password", "pw123456")
    page.click("button[type=submit]")
    page.wait_for_url("**/painel/**", timeout=15000)


@pytest.mark.django_db(transaction=True)
class TestBrowserHarnessMinimum:
    def test_live_server_assets_and_login_on_existing_page(
        self, live_server, routed_browser_page
    ) -> None:
        """Harness minimum: server + pinned assets + real login."""
        new_page, served = routed_browser_page
        _make_reader()
        page = new_page()
        _login(page, live_server.url, "browser_reader")
        assert "/login/" not in page.url
        for url, _, _ in PINNED_ROUTES:
            if url.startswith("**"):
                continue
            assert url in served


@pytest.mark.django_db(transaction=True)
class TestContextualJourney:
    def test_create_edit_history_finalize_and_reader(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, served = routed_browser_page
        _make_writer()
        _make_reader()
        admission = _make_eligible_admission()
        _ensure_bootstrap()
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)

        page = new_page()
        _login(page, live_server.url, "browser_writer")

        page.goto(
            f"{live_server.url}/patients/{admission.patient_id}/admissions/"
            f"?admission_id={admission.pk}",
            wait_until="domcontentloaded",
        )
        page.click(f'a[href="/admissions/{admission.pk}/pending-items/"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")

        page.select_option("#id_item_type", str(outro.pk))
        page.fill("#id_description", "pendencia contextual sintetica")
        page.click('[data-testid="pending-create"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        assert "pendencia contextual sintetica" in page.content()

        page.click('[data-testid^="pending-edit-"]')
        page.fill("#id_description", "pendencia contextual editada")
        page.click('[data-testid="pending-save"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        assert "pendencia contextual editada" in page.content()

        page.click('[data-testid^="pending-history-"]')
        page.wait_for_url("**/history/**")
        history = page.content()
        assert "pendencia contextual sintetica" in history
        assert "pendencia contextual editada" in history
        page.go_back()

        page.click('[data-testid^="pending-finalize-"]')
        page.select_option("#id_target_status", "resolved")
        page.click('[data-testid="pending-finalize-confirm"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        assert "Resolvida" in page.content()

        # Fonts: force the icon-font load through interception and prove
        # the pinned woff2 was served (no network fallback exists).
        loaded = page.evaluate(
            'document.fonts.load(\'16px "bootstrap-icons"\')'
            ".then(faces => faces.length)"
        )
        assert loaded >= 1
        assert FONT_ROUTES[1][0] in served

        page.context.clear_cookies()
        _login(page, live_server.url, "browser_reader")
        page.goto(
            f"{live_server.url}/admissions/{admission.pk}/pending-items/",
            wait_until="domcontentloaded",
        )
        assert "pendencia contextual editada" in page.content()
        assert page.locator('[data-testid="pending-create"]').count() == 0

    def test_mobile_viewport_journey(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="browser_mobile_writer")
        admission = _make_eligible_admission("P_BROWSER_MOBILE")
        _ensure_bootstrap()
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)

        page = new_page(viewport={"width": 390, "height": 844})
        _login(page, live_server.url, "browser_mobile_writer")
        page.goto(
            f"{live_server.url}/admissions/{admission.pk}/pending-items/",
            wait_until="domcontentloaded",
        )
        page.select_option("#id_item_type", str(outro.pk))
        page.fill("#id_description", "pendencia movel sintetica")
        page.click('[data-testid="pending-create"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        assert "pendencia movel sintetica" in page.content()
        overflow = page.evaluate(
            "document.scrollingElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1
