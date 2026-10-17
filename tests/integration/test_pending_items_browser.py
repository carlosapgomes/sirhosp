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

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.utils import timezone
from playwright.sync_api import Browser, Page, ViewportSize, sync_playwright

from apps.census.models import (
    BedStatus,
    CensusSnapshot,
    PatientMovement,
    Specialty,
)
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    GROUP_NAME,
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemRevision,
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


def _make_agg_movement(
    patient: Patient, sector: str, movement_date: str, sequence: int = 0
) -> PatientMovement:
    day = datetime.strptime(movement_date, "%Y-%m-%d").date()
    return PatientMovement.objects.create(
        patient=patient,
        admission=None,
        movement_date=day,
        sector=sector,
        sequence=sequence,
        first_seen_at=_dt("2026-06-01T08:00:00"),
        last_seen_at=_dt("2026-06-01T08:00:00"),
    )


def _make_agg_item(
    admission: Admission,
    description: str,
    *,
    age_days: int,
    status: str = STATUS_ACTIVE,
    finalized_days_ago: int | None = None,
) -> PendingItem:
    outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
    finalized_at = None
    version = 1
    if status != STATUS_ACTIVE:
        assert finalized_days_ago is not None
        finalized_at = timezone.now() - timedelta(days=finalized_days_ago)
        version = 2
    item = PendingItem.objects.create(
        admission=admission,
        item_type=outro,
        description=description,
        status=status,
        version=version,
        finalized_at=finalized_at,
    )
    PendingItem.objects.filter(pk=item.pk).update(
        created_at=timezone.now() - timedelta(days=age_days)
    )
    item.refresh_from_db()
    PendingItemRevision.objects.create(
        item=item,
        version=1,
        action="created",
        item_type=outro,
        type_name=outro.name,
        description=description,
        status=STATUS_ACTIVE,
    )
    if version == 2:
        assert finalized_at is not None
        PendingItemRevision.objects.create(
            item=item,
            version=2,
            action="finalized",
            item_type=outro,
            type_name=outro.name,
            description=description,
            status=status,
        )
    return item


def _make_aggregate_scene() -> dict[str, Admission | PendingItem]:
    """Two-patient scene: PS pathway, ages 2/8/5 plus one resolved."""
    _ensure_bootstrap()
    Specialty.objects.get_or_create(
        code="CIV", defaults={"name": "CIRURGIA VASCULAR"}
    )
    patient_a = Patient.objects.create(
        patient_source_key="P_AGG_A",
        source_system="tasy",
        name="PACIENTE SINTETICO P_AGG_A",
    )
    admission_a = Admission.objects.create(
        patient=patient_a,
        source_system="tasy",
        source_admission_key="ADM_P_AGG_A",
        admission_date=_dt("2026-06-01T08:00:00"),
    )
    CensusSnapshot.objects.create(
        captured_at=_dt("2026-06-10T08:00:00"),
        setor="CLINICA MEDICA",
        leito="L01",
        prontuario="P_AGG_A",
        nome="PACIENTE SINTETICO P_AGG_A",
        especialidade="CIV",
        bed_status=BedStatus.OCCUPIED,
    )
    _make_agg_movement(patient_a, "PRONTO SOCORRO", "2026-06-01")
    _make_agg_movement(patient_a, "UTI GERAL", "2026-06-03")
    _make_agg_movement(patient_a, "ENFERMARIA 1", "2026-06-05")
    patient_b = Patient.objects.create(
        patient_source_key="P_AGG_B",
        source_system="tasy",
        name="PACIENTE SINTETICO P_AGG_B",
    )
    admission_b = Admission.objects.create(
        patient=patient_b,
        source_system="tasy",
        source_admission_key="ADM_P_AGG_B",
        admission_date=_dt("2026-06-02T08:00:00"),
    )
    CensusSnapshot.objects.create(
        captured_at=_dt("2026-06-10T08:00:00"),
        setor="UTI GERAL",
        leito="U02",
        prontuario="P_AGG_B",
        nome="PACIENTE SINTETICO P_AGG_B",
        bed_status=BedStatus.OCCUPIED,
    )
    return {
        "admission_a": admission_a,
        "admission_b": admission_b,
        "a1": _make_agg_item(admission_a, "agg-a1-sintetica", age_days=2),
        "a2": _make_agg_item(admission_a, "agg-a2-sintetica", age_days=8),
        "a0": _make_agg_item(
            admission_a,
            "agg-a0-resolvida",
            age_days=10,
            status=STATUS_RESOLVED,
            finalized_days_ago=3,
        ),
        "b1": _make_agg_item(admission_b, "agg-b1-sintetica", age_days=5),
    }


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


@pytest.mark.django_db(transaction=True)
class TestAggregateJourney:
    """PEND-S3 desktop: menu, views, filters, history, modal, reader."""

    def test_panel_views_filters_history_modal_and_reader(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, served = routed_browser_page
        _make_writer()
        _make_reader()
        scene = _make_aggregate_scene()
        admission_a = scene["admission_a"]
        admission_b = scene["admission_b"]
        assert isinstance(admission_a, Admission)
        assert isinstance(admission_b, Admission)
        a1 = scene["a1"]
        b1 = scene["b1"]
        assert isinstance(a1, PendingItem)
        assert isinstance(b1, PendingItem)

        page = new_page()
        _login(page, live_server.url, "browser_writer")
        menu = page.locator('[data-testid="nav-pendencias"]')
        assert menu.count() == 1
        with page.expect_navigation():
            menu.click()
        assert "/pendencias/" in page.url
        content = page.content()
        assert "5,0 dias" in content
        assert "8,0 dias" in content
        assert "P_AGG_A" in content
        assert "P_AGG_B" in content
        assert "PRONTO SOCORRO" in content
        assert "CIRURGIA VASCULAR" in content
        assert "Primeira unidade não identificada" in content

        with page.expect_navigation():
            page.click('[data-testid="view-items"]')
        assert "view=items" in page.url
        assert "agg-a1-sintetica" in page.content()
        with page.expect_navigation():
            page.click('[data-testid="view-patients"]')
        assert "agg-b1-sintetica" in page.content()

        page.select_option("#f_status", "resolved")
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        filtered = page.content()
        assert "agg-a0-resolvida" in filtered
        assert "agg-a1-sintetica" not in filtered
        assert "5,0 dias" in filtered
        assert "8,0 dias" in filtered
        page.select_option("#f_status", "active")
        page.fill("#f_min_dias", "6")
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        aged = page.content()
        assert "agg-a2-sintetica" in aged
        assert "agg-a1-sintetica" not in aged
        assert "agg-b1-sintetica" not in aged
        with page.expect_navigation():
            page.click('[data-testid="nav-pendencias"]')

        page.click(f'[data-testid="pending-history-{a1.pk}"]')
        page.wait_for_selector(
            f"#history-body-{a1.pk} >> text=agg-a1-sintetica", timeout=15000
        )
        assert "P_AGG_A" in page.content()

        page.click(f'[data-testid="pending-edit-{a1.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_description",
            state="visible",
            timeout=15000,
        )
        page.fill("#pending-modal-body #id_description", "agg-a1-editada")
        with page.expect_navigation():
            page.click('[data-testid="pending-save"]')
        edited = page.content()
        assert "agg-a1-editada" in edited
        assert "atualizada com sucesso" in edited
        page.click(f'[data-testid="pending-history-{a1.pk}"]')
        page.wait_for_selector(
            f"#history-body-{a1.pk} >> text=agg-a1-editada", timeout=15000
        )
        assert "agg-a1-sintetica" in page.content()

        page.click(f'[data-testid="pending-finalize-{b1.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_target_status",
            state="visible",
            timeout=15000,
        )
        page.select_option(
            "#pending-modal-body #id_target_status",
            STATUS_CLOSED_UNRESOLVED,
        )
        with page.expect_navigation():
            page.click('[data-testid="pending-finalize-confirm"]')
        finalized = page.content()
        assert "agg-b1-sintetica" not in finalized
        assert (
            page.locator(
                f'[data-testid="patient-group-{admission_b.pk}"]'
            ).count()
            == 0
        )
        assert (
            page.locator(
                f'[data-testid="patient-group-{admission_a.pk}"]'
            ).count()
            == 1
        )
        assert (
            page.locator('[data-testid="indicators-patients"]').inner_text()
            == "1"
        )

        for url, _, _ in PINNED_ROUTES:
            if url.startswith("**"):
                continue
            assert url in served

        page.context.clear_cookies()
        _login(page, live_server.url, "browser_reader")
        page.goto(
            f"{live_server.url}/pendencias/",
            wait_until="domcontentloaded",
        )
        assert "agg-a1-editada" in page.content()
        assert page.locator('[data-testid^="pending-edit-"]').count() == 0
        assert (
            page.locator('[data-testid^="pending-finalize-"]').count() == 0
        )
        page.click(f'[data-testid="pending-history-{a1.pk}"]')
        page.wait_for_selector(
            f"#history-body-{a1.pk} >> text=agg-a1-editada", timeout=15000
        )


@pytest.mark.django_db(transaction=True)
class TestAggregateMobileJourney:
    """PEND-S3 mobile: sidebar menu, views, history, modal, no overflow."""

    def test_mobile_panel_parity(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _served = routed_browser_page
        _make_writer(username="browser_agg_mobile_writer")
        scene = _make_aggregate_scene()
        a1 = scene["a1"]
        assert isinstance(a1, PendingItem)

        page = new_page(viewport={"width": 390, "height": 844})
        _login(page, live_server.url, "browser_agg_mobile_writer")
        page.click("#sidebarToggle")
        page.locator('[data-testid="nav-pendencias"]').wait_for(
            state="visible", timeout=15000
        )
        with page.expect_navigation():
            page.locator('[data-testid="nav-pendencias"]').click()
        assert "agg-a1-sintetica" in page.content()
        assert "PRONTO SOCORRO" in page.content()

        with page.expect_navigation():
            page.click('[data-testid="view-items"]')
        assert "agg-b1-sintetica" in page.content()
        with page.expect_navigation():
            page.click('[data-testid="view-patients"]')

        page.click(f'[data-testid="pending-history-{a1.pk}"]')
        page.wait_for_selector(
            f"#history-body-{a1.pk} >> text=agg-a1-sintetica", timeout=15000
        )
        assert "P_AGG_A" in page.content()

        page.click(f'[data-testid="pending-edit-{a1.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_description",
            state="visible",
            timeout=15000,
        )
        page.click('#pending-modal-body button[data-bs-dismiss="modal"]')
        page.wait_for_selector(
            "#pending-modal-body #id_description", state="hidden", timeout=15000
        )

        overflow = page.evaluate(
            "document.scrollingElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1
