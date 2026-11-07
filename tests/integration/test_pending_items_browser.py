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

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl
import pytest
from django.apps import apps as django_apps
from django.contrib.auth.models import Group, User
from django.utils import timezone
from playwright.sync_api import (
    Browser,
    Locator,
    Page,
    ViewportSize,
    sync_playwright,
)

from apps.census.models import (
    BedStatus,
    CensusSnapshot,
    PatientMovement,
    Specialty,
)
from apps.patients.models import Admission, Patient
from apps.pending_items.catalog import load_pending_item_catalog
from apps.pending_items.models import (
    CATEGORY_SLUG_OUTRAS_PENDENCIAS,
    GROUP_NAME,
    OUTRO_NAME,
    OUTRO_SLUG,
    PROFILE_SIGNATURE,
    PROFILE_SIMPLE,
    PROFILE_TREATMENT,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemCategory,
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
                accept_downloads: bool = False,
            ) -> Page:
                if viewport is None:
                    viewport = {"width": 1280, "height": 800}
                page = browser.new_page(
                    viewport=viewport, accept_downloads=accept_downloads
                )
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
    ``Desospitalização`` group, the catalog categories and the ``Outro``
    type). The HTTP suite keeps proving the migration bootstrap with
    plain ``.get``; here the journeys only need the rows to exist, so
    recreate the fallback category and ``Outro`` with its full contract.
    """
    Group.objects.get_or_create(name=GROUP_NAME)
    category, _created = PendingItemCategory.objects.get_or_create(
        slug=CATEGORY_SLUG_OUTRAS_PENDENCIAS,
        defaults={"name": "Outras pendências"},
    )
    PendingItemType.objects.get_or_create(
        slug=OUTRO_SLUG,
        defaults={
            "name": OUTRO_NAME,
            "category": category,
            "profile": PROFILE_SIMPLE,
            "has_rnm_complements": False,
            "requires_description": True,
        },
    )


def _load_catalog() -> None:
    """Restore the whole canonical catalog after a transactional flush.

    Post-S1 journeys that need more than the fallback entry use the
    reapplication context of the catalog load, never a simulated legacy
    adoption.
    """
    _ensure_bootstrap()
    load_pending_item_catalog(django_apps, initial=False)


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


def _make_admin(username: str = "browser_catalog_admin") -> User:
    return User.objects.create_superuser(
        username=username, password="pw123456", email=""
    )


def _login_admin(page: Page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}/admin/login/", wait_until="domcontentloaded")
    page.fill("#id_username", username)
    page.fill("#id_password", "pw123456")
    page.click("input[type=submit]")
    page.wait_for_url("**/admin/**", timeout=15000)


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
class TestCatalogAdminJourney:
    """S1 verification: admin -> portal selection -> observed history."""

    def test_admin_maintains_catalog_and_portal_shows_context(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _served = routed_browser_page
        _make_writer()
        _make_admin()
        _load_catalog()
        admission = _make_eligible_admission("P_BROWSER_CATALOG")

        page = new_page()
        _login_admin(page, live_server.url, "browser_catalog_admin")

        page.goto(
            f"{live_server.url}/admin/pending_items/pendingitemcategory/add/",
            wait_until="domcontentloaded",
        )
        page.fill("#id_name", "Categoria Sintetica S1")
        page.fill("#id_slug", "categoria-sintetica-s1")
        page.click("input[type=submit]")
        page.wait_for_url("**/admin/pending_items/pendingitemcategory/")
        assert "Categoria Sintetica S1" in page.content()

        page.goto(
            f"{live_server.url}/admin/pending_items/pendingitemtype/add/",
            wait_until="domcontentloaded",
        )
        page.select_option("#id_category", label="Categoria Sintetica S1")
        page.fill("#id_name", "Tipo Alfa Sintetico")
        page.fill("#id_slug", "tipo-alfa-sintetico")
        page.select_option("#id_profile", "registro-simples")
        page.click("input[type=submit]")
        page.wait_for_url("**/admin/pending_items/pendingitemtype/")
        item_type = PendingItemType.objects.get(slug="tipo-alfa-sintetico")
        assert item_type.category.slug == "categoria-sintetica-s1"
        assert item_type.profile == "registro-simples"

        page.context.clear_cookies()
        _login(page, live_server.url, "browser_writer")
        page.goto(
            f"{live_server.url}/admissions/{admission.pk}/pending-items/",
            wait_until="domcontentloaded",
        )
        selector = page.locator("#id_item_type")
        labels = selector.locator("option").all_inner_texts()
        assert "Categoria Sintetica S1 > Tipo Alfa Sintetico" in labels
        assert "Exames de imagem > RNM" in labels
        assert "CHD (Centro de Hemorragia Digestiva) > RNM" in labels
        rnm_values = [
            option.get_attribute("value")
            for option in selector.locator("option").all()
            if option.inner_text()
            in {
                "Exames de imagem > RNM",
                "CHD (Centro de Hemorragia Digestiva) > RNM",
            }
        ]
        assert len(set(rnm_values)) == 2

        page.select_option("#id_item_type", str(item_type.pk))
        page.fill("#id_description", "pendencia sintetica do catalogo")
        page.click('[data-testid="pending-create"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        assert "Tipo Alfa Sintetico" in page.content()

        page.context.clear_cookies()
        _login_admin(page, live_server.url, "browser_catalog_admin")
        page.goto(
            f"{live_server.url}/admin/pending_items/pendingitemtype/"
            f"{item_type.pk}/change/",
            wait_until="domcontentloaded",
        )
        page.fill("#id_name", "Tipo Beta Sintetico")
        page.click("input[type=submit]")
        page.wait_for_url("**/admin/pending_items/pendingitemtype/")
        assert PendingItemType.objects.get(
            pk=item_type.pk
        ).name == "Tipo Beta Sintetico"

        page.context.clear_cookies()
        _login(page, live_server.url, "browser_writer")
        page.goto(
            f"{live_server.url}/admissions/{admission.pk}/pending-items/",
            wait_until="domcontentloaded",
        )
        listing = page.content()
        assert "Tipo Beta Sintetico" in listing
        assert "Tipo Alfa Sintetico" not in listing

        page.click('[data-testid^="pending-history-"]')
        page.wait_for_url("**/history/**")
        history = page.content()
        assert "Tipo Beta Sintetico" in history
        assert "Tipo Alfa Sintetico" in history
        assert "Categoria Sintetica S1" in history


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


EXPECTED_EXPORT_HEADERS = [
    "Registro",
    "Nome",
    "Unidade atual",
    "Leito",
    "Primeira unidade de internação",
    "Especialidade",
    "Tipo",
    "Descrição/observação",
    "Status",
    "Criado em",
    "Criado por",
    "Atualizado em",
    "Atualizado por",
]


def _make_export_scene() -> dict[str, list[str]]:
    """22 patients: 23 actives (one formula-like) plus one resolved."""
    _ensure_bootstrap()
    outro = PendingItemType.objects.get(slug=OUTRO_SLUG)

    def _admit(key: str, setor: str, leito: str) -> Admission:
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
            setor=setor,
            leito=leito,
            prontuario=key,
            nome="PACIENTE SINTETICO",
            bed_status=BedStatus.OCCUPIED,
        )
        return admission

    active: list[str] = []
    for index in range(21):
        key = f"P_EXP_DL{index:02d}"
        admission = _admit(key, "CLINICA MEDICA", f"L{index:02d}")
        description = f"exp-dl-{index:02d}"
        PendingItem.objects.create(
            admission=admission,
            item_type=outro,
            description=description,
            status=STATUS_ACTIVE,
            version=1,
        )
        active.append(description)
    uti = _admit("P_EXP_DL_U", "UTI GERAL", "U01")
    for description in ("exp-dl-uti-a", "=1+1-sintetico"):
        PendingItem.objects.create(
            admission=uti,
            item_type=outro,
            description=description,
            status=STATUS_ACTIVE,
            version=1,
        )
        active.append(description)
    PendingItem.objects.create(
        admission=uti,
        item_type=outro,
        description="exp-dl-uti-resolvida",
        status=STATUS_RESOLVED,
        version=2,
        finalized_at=_dt("2026-06-11T10:00:00"),
    )
    return {
        "active": active,
        "uti": ["exp-dl-uti-a", "=1+1-sintetico"],
    }


def _read_export_rows(path: Path) -> list[list]:
    workbook = openpyxl.load_workbook(path)
    sheet = workbook.active
    assert sheet is not None
    return [[cell.value for cell in row] for row in sheet.iter_rows()]


def _assert_literal_cell(path: Path, value: str) -> None:
    sheet = openpyxl.load_workbook(path).active
    assert sheet is not None
    found = [
        cell
        for row in sheet.iter_rows(min_row=2)
        for cell in row
        if cell.value == value
    ]
    assert found
    for cell in found:
        assert cell.data_type in ("s", "inlineStr")


@pytest.mark.django_db(transaction=True)
class TestExportJourney:
    """PEND-S4: reader downloads the filtered cut beyond the page."""

    def test_reader_filters_and_downloads_both_modes(
        self, live_server, routed_browser_page, tmp_path
    ) -> None:
        new_page, _served = routed_browser_page
        _make_reader(username="export_dl_reader")
        expected = _make_export_scene()

        page = new_page(accept_downloads=True)
        _login(page, live_server.url, "export_dl_reader")
        page.goto(
            f"{live_server.url}/pendencias/",
            wait_until="domcontentloaded",
        )
        assert page.locator('[data-testid="pagination"]').count() == 1

        with page.expect_download() as full_info:
            page.click('[data-testid="aggregate-export"]')
        full = full_info.value
        assert full.suggested_filename.startswith("pendencias-")
        assert full.suggested_filename.endswith(".xlsx")
        full_path = tmp_path / "full.xlsx"
        full.save_as(str(full_path))
        full_rows = _read_export_rows(full_path)
        assert full_rows[0] == EXPECTED_EXPORT_HEADERS
        assert len(full_rows) == 1 + len(expected["active"])
        assert {row[7] for row in full_rows[1:]} == set(
            expected["active"]
        )
        _assert_literal_cell(full_path, "=1+1-sintetico")

        page.select_option("#f_unidade", "UTI GERAL")
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        assert "exp-dl-uti-a" in page.content()
        assert "exp-dl-00" not in page.content()
        with page.expect_download() as unit_info:
            page.click('[data-testid="aggregate-export"]')
        unit_path = tmp_path / "uti.xlsx"
        unit_info.value.save_as(str(unit_path))
        unit_rows = _read_export_rows(unit_path)
        assert {row[7] for row in unit_rows[1:]} == set(expected["uti"])
        assert all(row[2] == "UTI GERAL" for row in unit_rows[1:])

        with page.expect_navigation():
            page.click('[data-testid="view-items"]')
        with page.expect_download() as items_info:
            page.click('[data-testid="aggregate-export"]')
        items_path = tmp_path / "uti-items.xlsx"
        items_info.value.save_as(str(items_path))
        assert _read_export_rows(items_path) == unit_rows


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


S2_SCHEDULED_DATE = date(2026, 11, 10)
S2_MODAL_DATE = date(2026, 11, 15)


def _option_hidden_flags(page: Page) -> list[list]:
    """Return ``[category_slug, hidden]`` for every catalog type option."""
    flags = page.evaluate(
        """() => Array.from(document.querySelectorAll('#id_item_type option'))
            .filter((option) => option.dataset.category)
            .map((option) => [option.dataset.category, option.hidden])"""
    )
    return flags


def _rnm_revision(rnm_type: PendingItemType, item: PendingItem, **details) -> None:
    PendingItemRevision.objects.create(
        item=item,
        version=1,
        action="created",
        item_type=rnm_type,
        type_name=rnm_type.name,
        category_name=rnm_type.category.name,
        category_slug=rnm_type.category.slug,
        type_slug=rnm_type.slug,
        profile=rnm_type.profile,
        has_rnm_complements=rnm_type.has_rnm_complements,
        requires_description=rnm_type.requires_description,
        description=item.description,
        status=STATUS_ACTIVE,
        **details,
    )


@pytest.mark.django_db(transaction=True)
class TestStructuredContextualJourney:
    """STRUCT-PEND-S2: progressive cadastro, search and Save-and-add-another."""

    def test_progressive_create_search_keyboard_and_add_another(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="s2_browser_writer")
        admission = _make_eligible_admission("P_S2_BROWSER_PROGRESSIVE")
        _load_catalog()
        tomografia = PendingItemType.objects.get(slug="imagem-tomografia")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")

        page = new_page()
        _login(page, live_server.url, "s2_browser_writer")
        page.goto(
            f"{live_server.url}/admissions/{admission.pk}/pending-items/",
            wait_until="domcontentloaded",
        )

        # Progressive: no profile fields before a type is chosen.
        assert page.locator("#pending-group-agendamento").is_visible() is False
        assert page.locator("#pending-group-tratamento").is_visible() is False
        assert page.locator("#pending-group-rnm").is_visible() is False

        # Category narrows the type options; nothing is deleted.
        image_category = str(tomografia.category_id)
        chd_category = str(chd_rnm.category_id)
        page.select_option("#id_category", label="Exames de imagem")
        flags = dict(_option_hidden_flags(page))
        assert flags[image_category] is False
        assert flags[chd_category] is True

        page.select_option("#id_item_type", str(tomografia.pk))
        assert page.locator("#pending-group-agendamento").is_visible() is True
        assert page.locator("#pending-group-tratamento").is_visible() is False
        assert page.locator("#pending-group-rnm").is_visible() is False

        # Agendada Não keeps the optional date hidden and needs no observation.
        page.select_option("#id_is_scheduled", "nao")
        assert page.locator("#pending-scheduled-date").is_visible() is False
        page.fill("#id_description", "")
        page.click('[data-testid="pending-create"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        created = PendingItem.objects.get(admission=admission)
        assert created.is_scheduled is False
        assert created.description == ""
        assert "Agendada: Não" in page.content()

        # Search shows both RNM entries and the chosen one sets the category.
        page.fill("#id_type_search", "rnm")
        visible = {
            category
            for category, hidden in _option_hidden_flags(page)
            if not hidden
        }
        assert image_category in visible
        assert chd_category in visible
        page.select_option("#id_item_type", str(chd_rnm.pk))
        assert page.locator("#id_category").input_value() == chd_category
        assert page.locator("#pending-group-rnm").is_visible() is True

        # Keyboard: arrow keys change Agendada and reveal the date control.
        page.select_option("#id_is_scheduled", "nao")
        assert page.locator("#pending-scheduled-date").is_visible() is False
        page.locator("#id_is_scheduled").focus()
        page.keyboard.press("ArrowUp")
        assert page.locator("#id_is_scheduled").input_value() == "sim"
        assert page.locator("#pending-scheduled-date").is_visible() is True

        page.fill("#id_scheduled_date", S2_SCHEDULED_DATE.isoformat())
        page.select_option("#id_contrast", "sim")
        page.select_option("#id_sedation", "nao")
        page.locator('[data-testid="pending-save-new"]').focus()
        assert page.evaluate("document.activeElement.dataset.testid") == (
            "pending-save-new"
        )
        with page.expect_navigation():
            page.keyboard.press("Enter")
        assert page.locator(".errorlist").count() == 0

        created_rows = list(
            PendingItem.objects.filter(admission=admission).values_list(
                "item_type__slug", "description", "is_scheduled",
                "scheduled_date", "contrast", "sedation",
            )
        )
        assert "chd-rnm" in [row[0] for row in created_rows], created_rows
        rnm = PendingItem.objects.get(admission=admission, item_type=chd_rnm)
        assert rnm.is_scheduled is True
        assert rnm.scheduled_date == S2_SCHEDULED_DATE
        assert rnm.contrast is True
        assert rnm.sedation is False
        content = page.content()
        assert "Data agendada: 10/11/2026" in content
        assert "Contraste: Sim" in content
        assert "Sedação: Não" in content

        # Save and add another returns an empty form, not copied details.
        assert page.locator("#id_scheduled_date").input_value() == ""
        assert page.locator("#id_description").input_value() == ""
        assert PendingItem.objects.filter(admission=admission).count() == 2
        page.reload(wait_until="domcontentloaded")
        assert PendingItem.objects.filter(admission=admission).count() == 2

        page.click(f'[data-testid="pending-history-{rnm.pk}"]')
        page.wait_for_url("**/history/**")
        history = page.content()
        assert "Contraste: Sim" in history
        assert "Data agendada: 10/11/2026" in history
        overflow = page.evaluate(
            "document.scrollingElement.scrollWidth - window.innerWidth"
        )
        assert overflow <= 1

    def test_mobile_viewport_creates_and_edits_details(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="s2_browser_mobile")
        admission = _make_eligible_admission("P_S2_BROWSER_MOBILE")
        _load_catalog()
        tomografia = PendingItemType.objects.get(slug="imagem-tomografia")

        page = new_page(viewport={"width": 390, "height": 844})
        _login(page, live_server.url, "s2_browser_mobile")
        page.goto(
            f"{live_server.url}/admissions/{admission.pk}/pending-items/",
            wait_until="domcontentloaded",
        )

        page.select_option("#id_item_type", str(tomografia.pk))
        assert page.locator("#pending-group-agendamento").is_visible() is True
        page.select_option("#id_is_scheduled", "nao")
        page.click('[data-testid="pending-create"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        item = PendingItem.objects.get(admission=admission)
        assert item.is_scheduled is False
        assert (
            page.evaluate(
                "document.scrollingElement.scrollWidth - window.innerWidth"
            )
            <= 1
        )

        page.click(f'[data-testid="pending-edit-{item.pk}"]')
        page.wait_for_url("**/edit/**")
        page.select_option("#id_is_scheduled", "sim")
        assert page.locator("#pending-scheduled-date").is_visible() is True
        page.fill("#id_scheduled_date", "2026-11-12")
        page.click('[data-testid="pending-save"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        item.refresh_from_db()
        assert item.is_scheduled is True
        assert item.scheduled_date.isoformat() == "2026-11-12"
        assert "Data agendada: 12/11/2026" in page.content()
        assert (
            page.evaluate(
                "document.scrollingElement.scrollWidth - window.innerWidth"
            )
            <= 1
        )


@pytest.mark.django_db(transaction=True)
class TestStructuredEditSurfaces:
    """STRUCT-PEND-S2: shared rules in the contextual page and the modal."""

    def test_quick_edit_modal_writes_details_and_keeps_other_values(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="s2_browser_modal")
        scene = _make_aggregate_scene()
        admission = scene["admission_a"]
        assert isinstance(admission, Admission)
        _load_catalog()
        rnm_type = PendingItemType.objects.get(slug="imagem-rnm")
        item = PendingItem.objects.create(
            admission=admission,
            item_type=rnm_type,
            description="rnm do modal sintetica",
            status=STATUS_ACTIVE,
            version=1,
            is_scheduled=True,
            contrast=True,
        )
        _rnm_revision(rnm_type, item, is_scheduled=True, contrast=True)

        page = new_page()
        _login(page, live_server.url, "s2_browser_modal")
        page.goto(f"{live_server.url}/pendencias/", wait_until="domcontentloaded")
        page.click(f'[data-testid="pending-edit-{item.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_scheduled_date",
            state="visible",
            timeout=15000,
        )
        modal_scheduled = page.locator(
            "#pending-modal-body #id_is_scheduled"
        ).input_value()
        assert modal_scheduled == "sim"
        page.fill(
            "#pending-modal-body #id_scheduled_date",
            S2_MODAL_DATE.isoformat(),
        )
        with page.expect_navigation():
            page.click("#pending-modal-body [data-testid='pending-save']")
        item.refresh_from_db()
        assert item.scheduled_date == S2_MODAL_DATE
        assert item.contrast is True
        assert item.description == "rnm do modal sintetica"
        assert "atualizada com sucesso" in page.content()

        # Conflict: another version lands while the modal stays open.
        page.click(f'[data-testid="pending-edit-{item.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_scheduled_date",
            state="visible",
            timeout=15000,
        )
        page.fill("#pending-modal-body #id_scheduled_date", "2026-11-20")
        PendingItem.objects.filter(pk=item.pk).update(version=item.version + 1)
        page.click("#pending-modal-body [data-testid='pending-save']")
        page.wait_for_selector(
            "#pending-modal-body .alert-danger",
            state="visible",
            timeout=15000,
        )
        conflict = page.locator("#pending-modal-body").inner_html()
        assert "alterada por outra pessoa" in conflict
        assert "20/11/2026" in conflict
        item.refresh_from_db()
        assert item.scheduled_date == S2_MODAL_DATE

    def test_confirmed_and_cancelled_detail_removal(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="s2_browser_removal")
        admission = _make_eligible_admission("P_S2_BROWSER_REMOVAL")
        _load_catalog()
        rnm_type = PendingItemType.objects.get(slug="imagem-rnm")
        tomografia = PendingItemType.objects.get(slug="imagem-tomografia")
        item = PendingItem.objects.create(
            admission=admission,
            item_type=rnm_type,
            description="",
            status=STATUS_ACTIVE,
            version=1,
            is_scheduled=True,
            scheduled_date=S2_SCHEDULED_DATE,
            contrast=True,
        )
        _rnm_revision(
            rnm_type,
            item,
            is_scheduled=True,
            scheduled_date=S2_SCHEDULED_DATE,
            contrast=True,
        )
        edit_url = (
            f"{live_server.url}/admissions/{admission.pk}/pending-items/"
            f"{item.pk}/edit/"
        )
        list_url = f"{live_server.url}/admissions/{admission.pk}/pending-items/"

        page = new_page()
        _login(page, live_server.url, "s2_browser_removal")
        page.goto(edit_url, wait_until="domcontentloaded")
        page.select_option("#id_item_type", str(tomografia.pk))
        assert page.locator("#pending-removal-box").is_visible() is True
        removal_text = page.locator("#pending-removal-box").inner_text()
        assert "Contraste" in removal_text
        assert "Sedação" not in removal_text
        page.goto(list_url, wait_until="domcontentloaded")
        item.refresh_from_db()
        assert item.item_type_id == rnm_type.pk
        assert item.contrast is True
        assert item.version == 1

        page.goto(edit_url, wait_until="domcontentloaded")
        page.select_option("#id_item_type", str(tomografia.pk))
        page.check("#id_confirm_detail_removal")
        page.click('[data-testid="pending-save"]')
        page.wait_for_url(f"**/admissions/{admission.pk}/pending-items/**")
        item.refresh_from_db()
        assert item.item_type_id == tomografia.pk
        assert item.contrast is None
        assert item.scheduled_date == S2_SCHEDULED_DATE

        page.click(f'[data-testid="pending-history-{item.pk}"]')
        page.wait_for_url("**/history/**")
        assert "Contraste: Sim" in page.content()


S2_TREATMENT_START = date(2026, 11, 1)
S2_TREATMENT_END = date(2026, 11, 10)
S2_SIGNATURE_FIRST = datetime(2026, 11, 12, 9, 30, tzinfo=TZ)
S2_SIGNATURE_SECOND = datetime(2026, 11, 14, 8, 0, tzinfo=TZ)


def _pending_item_card(page: Page, item_id: int) -> Locator:
    """The contextual card that owns one item's details and actions."""
    return page.locator(
        "div.card",
        has=page.locator(f'[data-testid="pending-history-{item_id}"]'),
    )


def _card_detail_text(page: Page, item_id: int) -> str:
    return _pending_item_card(page, item_id).locator(
        '[data-testid="pending-details"]'
    ).inner_text()


def _horizontal_overflow(page: Page) -> float:
    return page.evaluate(
        "document.scrollingElement.scrollWidth - window.innerWidth"
    )


@pytest.mark.django_db(transaction=True)
class TestStructuredTreatmentAndSignatureJourney:
    """STRUCT-PEND-S2 R4: browser create/edit for the two remaining profiles.

    The treatment-period (``Antibióticos``) and signature-document
    (``Assinatura do sumário de alta``) profiles are exercised through the
    real live_server form, their contextual edit page and the persisted
    history, including keyboard submission and the 390 px viewport.
    """

    def test_treatment_period_create_edit_history_and_keyboard(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="s2_browser_treatment")
        admission = _make_eligible_admission("P_S2_BROWSER_TREATMENT")
        _load_catalog()
        antibioticos = PendingItemType.objects.get(
            slug="infeccioso-antibioticos"
        )
        assert antibioticos.profile == PROFILE_TREATMENT
        patient_key = admission.patient.patient_source_key
        admission_date = admission.admission_date
        list_url = f"{live_server.url}/admissions/{admission.pk}/pending-items/"

        page = new_page()
        _login(page, live_server.url, "s2_browser_treatment")
        page.goto(list_url, wait_until="domcontentloaded")

        # Only the treatment-period group applies to this type.
        page.select_option("#id_item_type", str(antibioticos.pk))
        assert page.locator("#pending-group-tratamento").is_visible() is True
        assert page.locator("#pending-group-assinatura").is_visible() is False
        assert page.locator("#pending-group-agendamento").is_visible() is False
        assert page.locator("#pending-group-rnm").is_visible() is False

        # Partial period: only the start date, submitted by keyboard.
        page.fill("#id_treatment_start_date", S2_TREATMENT_START.isoformat())
        page.locator('[data-testid="pending-create"]').focus()
        assert (
            page.evaluate("document.activeElement.dataset.testid")
            == "pending-create"
        )
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_url(list_url)

        item = PendingItem.objects.get(admission=admission)
        assert item.treatment_start_date == S2_TREATMENT_START
        assert item.treatment_end_date is None
        assert item.signature_at is None
        assert item.is_scheduled is None
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert item.finalized_at is None
        details = _card_detail_text(page, item.pk)
        assert "Início do tratamento: 01/11/2026" in details
        assert "Previsão de término: Não informado" in details

        # Edit recovers the stored start date and adds the end date.
        page.click(f'[data-testid="pending-edit-{item.pk}"]')
        page.wait_for_url("**/edit/**")
        assert page.locator("#pending-group-tratamento").is_visible() is True
        assert page.locator("#id_treatment_start_date").input_value() == (
            "2026-11-01"
        )
        assert page.locator("#id_treatment_end_date").input_value() == ""
        page.fill("#id_treatment_end_date", S2_TREATMENT_END.isoformat())
        page.locator('[data-testid="pending-save"]').focus()
        assert (
            page.evaluate("document.activeElement.dataset.testid")
            == "pending-save"
        )
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_url(list_url)

        item.refresh_from_db()
        assert item.treatment_start_date == S2_TREATMENT_START
        assert item.treatment_end_date == S2_TREATMENT_END
        assert item.version == 2
        details = _card_detail_text(page, item.pk)
        assert "Início do tratamento: 01/11/2026" in details
        assert "Previsão de término: 10/11/2026" in details

        # History keeps both versions with their own details.
        page.click(f'[data-testid="pending-history-{item.pk}"]')
        page.wait_for_url("**/history/**")
        current = page.locator('[data-testid="pending-details"]').inner_text()
        assert "Início do tratamento: 01/11/2026" in current
        assert "Previsão de término: 10/11/2026" in current
        versions = page.locator("tbody tr")
        assert versions.count() == 2
        first = versions.nth(0).inner_text()
        second = versions.nth(1).inner_text()
        assert "v1" in first
        assert "Início do tratamento: 01/11/2026" in first
        assert "Previsão de término: Não informado" in first
        assert "v2" in second
        assert "Previsão de término: 10/11/2026" in second
        assert "Antibióticos" in page.content()

        # 390 px: the stored details still render without overflow.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(list_url, wait_until="domcontentloaded")
        assert "Previsão de término: 10/11/2026" in _card_detail_text(
            page, item.pk
        )
        assert _horizontal_overflow(page) <= 1

        # Creating and editing details neither finalizes nor moves the episode.
        admission.refresh_from_db()
        assert admission.discharge_date is None
        assert admission.admission_date == admission_date
        assert admission.patient.patient_source_key == patient_key
        item.refresh_from_db()
        assert item.status == STATUS_ACTIVE
        assert item.finalized_at is None
        assert set(item.revisions.values_list("action", flat=True)) == {
            "created",
            "updated",
        }

    def test_signature_document_create_edit_mobile_and_does_not_finalize(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _ = routed_browser_page
        _make_writer(username="s2_browser_signature")
        admission = _make_eligible_admission("P_S2_BROWSER_SIGNATURE")
        _load_catalog()
        sumario = PendingItemType.objects.get(slug="sumario-assinatura")
        assert sumario.profile == PROFILE_SIGNATURE
        patient_key = admission.patient.patient_source_key
        admission_date = admission.admission_date
        list_url = f"{live_server.url}/admissions/{admission.pk}/pending-items/"

        page = new_page(viewport={"width": 390, "height": 844})
        _login(page, live_server.url, "s2_browser_signature")
        page.goto(list_url, wait_until="domcontentloaded")

        page.select_option("#id_item_type", str(sumario.pk))
        assert page.locator("#pending-group-assinatura").is_visible() is True
        assert page.locator("#pending-group-tratamento").is_visible() is False
        assert page.locator("#pending-group-agendamento").is_visible() is False
        assert page.locator("#pending-group-rnm").is_visible() is False

        # Signature entered by keyboard at 390 px.
        page.fill("#id_signature_at", "2026-11-12T09:30")
        page.locator('[data-testid="pending-create"]').focus()
        assert (
            page.evaluate("document.activeElement.dataset.testid")
            == "pending-create"
        )
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_url(list_url)

        item = PendingItem.objects.get(admission=admission)
        assert item.signature_at == S2_SIGNATURE_FIRST
        assert item.treatment_start_date is None
        assert item.treatment_end_date is None
        assert item.is_scheduled is None
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert item.finalized_at is None
        details = _card_detail_text(page, item.pk)
        assert "Assinatura do sumário em: 12/11/2026 09:30" in details
        assert _horizontal_overflow(page) <= 1

        # Edit recovers the stored instant in local wall time and persists
        # the new one; the item stays active.
        page.click(f'[data-testid="pending-edit-{item.pk}"]')
        page.wait_for_url("**/edit/**")
        assert page.locator("#pending-group-assinatura").is_visible() is True
        assert page.locator("#id_signature_at").input_value() == (
            "2026-11-12T09:30"
        )
        page.fill("#id_signature_at", "2026-11-14T08:00")
        page.locator('[data-testid="pending-save"]').focus()
        with page.expect_navigation():
            page.keyboard.press("Enter")
        page.wait_for_url(list_url)
        item.refresh_from_db()
        assert item.signature_at == S2_SIGNATURE_SECOND
        assert item.status == STATUS_ACTIVE
        assert item.version == 2
        assert "Assinatura do sumário em: 14/11/2026 08:00" in (
            _card_detail_text(page, item.pk)
        )
        assert _horizontal_overflow(page) <= 1

        # A later edit of the observation alone keeps the stored instant.
        page.click(f'[data-testid="pending-edit-{item.pk}"]')
        page.wait_for_url("**/edit/**")
        page.fill("#id_description", "sumario assinado sintetico")
        page.click('[data-testid="pending-save"]')
        page.wait_for_url(list_url)
        item.refresh_from_db()
        assert item.signature_at == S2_SIGNATURE_SECOND
        assert item.description == "sumario assinado sintetico"
        assert item.version == 3

        # History shows the current value and each version's own value.
        page.click(f'[data-testid="pending-history-{item.pk}"]')
        page.wait_for_url("**/history/**")
        current = page.locator('[data-testid="pending-details"]').inner_text()
        assert "Assinatura do sumário em: 14/11/2026 08:00" in current
        versions = page.locator("tbody tr")
        assert versions.count() == 3
        assert "12/11/2026 09:30" in versions.nth(0).inner_text()
        assert "14/11/2026 08:00" in versions.nth(1).inner_text()
        assert "14/11/2026 08:00" in versions.nth(2).inner_text()
        assert "Assinatura do sumário de alta" in page.content()

        # Signing never finalizes the item nor changes the episode identity.
        admission.refresh_from_db()
        assert admission.discharge_date is None
        assert admission.admission_date == admission_date
        assert admission.patient.patient_source_key == patient_key
        assert item.finalized_at is None
        assert set(item.revisions.values_list("action", flat=True)) == {
            "created",
            "updated",
        }


S3_CHD_DATE = date(2026, 11, 10)
S3_CHD_EDITED = "2026-11-15"


def _make_s3_admission(key: str, setor: str, leito: str) -> Admission:
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
        setor=setor,
        leito=leito,
        prontuario=key,
        nome=f"PACIENTE SINTETICO {key}",
        bed_status=BedStatus.OCCUPIED,
    )
    return admission


def _s3_item(
    admission: Admission,
    item_type: PendingItemType,
    description: str,
    *,
    legacy_first: bool = False,
    **details,
) -> PendingItem:
    """Active item with its revision snapshot; optionally a pre-S1 legacy v1."""
    version = 2 if legacy_first else 1
    item = PendingItem.objects.create(
        admission=admission,
        item_type=item_type,
        description=description,
        status=STATUS_ACTIVE,
        version=version,
        **details,
    )
    if legacy_first:
        PendingItemRevision.objects.create(
            item=item,
            version=1,
            action="created",
            item_type=item_type,
            type_name=item_type.name,
            description=description,
            status=STATUS_ACTIVE,
        )
    PendingItemRevision.objects.create(
        item=item,
        version=version,
        action="created" if version == 1 else "updated",
        item_type=item_type,
        type_name=item_type.name,
        category_name=item_type.category.name,
        category_slug=item_type.category.slug,
        type_slug=item_type.slug,
        profile=item_type.profile,
        has_rnm_complements=item_type.has_rnm_complements,
        requires_description=item_type.requires_description,
        description=description,
        status=STATUS_ACTIVE,
        is_scheduled=details.get("is_scheduled"),
        scheduled_date=details.get("scheduled_date"),
        contrast=details.get("contrast"),
        sedation=details.get("sedation"),
    )
    return item


@pytest.mark.django_db(transaction=True)
class TestCategorizedAggregateJourney:
    """STRUCT-PEND-S3: categorized follow-up in both aggregate views."""

    def _scene(self) -> dict[str, object]:
        _load_catalog()
        admission_a = _make_s3_admission("P_S3_CAT_A", "UTI GERAL", "U01")
        admission_b = _make_s3_admission("P_S3_CAT_B", "ENFERMARIA 1", "E02")
        chd_rnm = PendingItemType.objects.get(slug="chd-rnm")
        imagem_rnm = PendingItemType.objects.get(slug="imagem-rnm")
        chd_a = _s3_item(
            admission_a,
            chd_rnm,
            "marcador-chd-a",
            legacy_first=True,
            is_scheduled=True,
            scheduled_date=S3_CHD_DATE,
            contrast=True,
        )
        imagem_a = _s3_item(
            admission_a,
            imagem_rnm,
            "marcador-imagem-a",
            is_scheduled=False,
            contrast=False,
            sedation=False,
        )
        chd_b = _s3_item(
            admission_b, chd_rnm, "marcador-chd-b", is_scheduled=False
        )
        return {
            "admission_a": admission_a,
            "admission_b": admission_b,
            "chd_rnm": chd_rnm,
            "imagem_rnm": imagem_rnm,
            "chd_a": chd_a,
            "imagem_a": imagem_a,
            "chd_b": chd_b,
        }

    def test_categorized_filters_details_and_refresh(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _served = routed_browser_page
        _make_writer(username="s3_browser_writer")
        scene = self._scene()
        chd_rnm = scene["chd_rnm"]
        imagem_rnm = scene["imagem_rnm"]
        chd_a = scene["chd_a"]
        chd_b = scene["chd_b"]
        assert isinstance(chd_rnm, PendingItemType)
        assert isinstance(imagem_rnm, PendingItemType)
        assert isinstance(chd_a, PendingItem)
        assert isinstance(chd_b, PendingItem)
        admission_a = scene["admission_a"]
        admission_b = scene["admission_b"]
        assert isinstance(admission_a, Admission)
        assert isinstance(admission_b, Admission)

        page = new_page()
        _login(page, live_server.url, "s3_browser_writer")
        page.goto(
            f"{live_server.url}/pendencias/", wait_until="domcontentloaded"
        )
        unfiltered = page.content()
        assert "CHD (Centro de Hemorragia Digestiva)" in unfiltered
        assert "Exames de imagem" in unfiltered
        assert "Data agendada: 10/11/2026" in unfiltered
        assert "Contraste: Sim" in unfiltered
        assert "Sedação: Não informado" in unfiltered
        assert "Sedação: Não" in unfiltered

        page.select_option("#f_categoria", str(chd_rnm.category_id))
        page.select_option("#f_tipo", str(chd_rnm.pk))
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        filtered = page.content()
        assert f"categoria={chd_rnm.category_id}" in page.url
        assert "marcador-chd-a" in filtered
        assert "marcador-chd-b" in filtered
        assert "marcador-imagem-a" not in filtered
        assert (
            page.locator('[data-testid="indicators-patients"]').inner_text()
            == "2"
        )

        page.click(f'[data-testid="pending-history-{chd_a.pk}"]')
        page.wait_for_selector(
            f"#history-body-{chd_a.pk} >> text=Data agendada: 10/11/2026",
            timeout=15000,
        )
        fragment = page.locator(f"#history-body-{chd_a.pk}").inner_text()
        assert "Detalhes não registrados nesta versão" in fragment
        assert "Classificação não registrada nesta versão" in fragment

        page.select_option("#f_tipo", str(imagem_rnm.pk))
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        incompatible = page.content()
        assert "Nenhuma pendência corresponde aos filtros." in incompatible
        assert "não se combinam" in incompatible

        page.select_option("#f_categoria", str(imagem_rnm.category_id))
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        imagem_view = page.content()
        assert "marcador-imagem-a" in imagem_view
        assert "marcador-chd-a" not in imagem_view
        assert "Contraste: Não" in imagem_view

        page.select_option("#f_categoria", str(chd_rnm.category_id))
        page.select_option("#f_tipo", str(chd_rnm.pk))
        with page.expect_navigation():
            page.click('[data-testid="filters-apply"]')
        with page.expect_navigation():
            page.click('[data-testid="view-items"]')
        assert "view=items" in page.url
        assert f"categoria={chd_rnm.category_id}" in page.url
        items_view = page.content()
        assert "marcador-chd-a" in items_view
        assert "marcador-imagem-a" not in items_view
        assert "Data agendada: 10/11/2026" in items_view

        page.click(f'[data-testid="pending-edit-{chd_a.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_scheduled_date",
            state="visible",
            timeout=15000,
        )
        page.fill("#pending-modal-body #id_scheduled_date", S3_CHD_EDITED)
        with page.expect_navigation():
            page.click("#pending-modal-body [data-testid='pending-save']")
        assert "view=items" in page.url
        assert f"categoria={chd_rnm.category_id}" in page.url
        assert f"tipo={chd_rnm.pk}" in page.url
        edited = page.content()
        assert "Data agendada: 15/11/2026" in edited
        assert "atualizada com sucesso" in edited
        page.click(f'[data-testid="pending-history-{chd_a.pk}"]')
        page.wait_for_selector(
            f"#history-body-{chd_a.pk} >> text=Data agendada: 15/11/2026",
            timeout=15000,
        )
        versions = page.locator(f"#history-body-{chd_a.pk}").inner_text()
        assert "v2" in versions
        assert "Contraste: Sim" in versions

        page.click(f'[data-testid="pending-finalize-{chd_b.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_target_status",
            state="visible",
            timeout=15000,
        )
        page.select_option(
            "#pending-modal-body #id_target_status", STATUS_CLOSED_UNRESOLVED
        )
        with page.expect_navigation():
            page.click('[data-testid="pending-finalize-confirm"]')
        assert f"categoria={chd_rnm.category_id}" in page.url
        finalized = page.content()
        assert "marcador-chd-b" not in finalized
        assert "marcador-chd-a" in finalized
        assert (
            page.locator(f'[data-testid="pending-row-{chd_b.pk}"]').count()
            == 0
        )
        assert (
            page.locator('[data-testid="indicators-patients"]').inner_text()
            == "1"
        )
        with page.expect_navigation():
            page.click('[data-testid="view-patients"]')
        assert "view=patients" in page.url
        assert f"categoria={chd_rnm.category_id}" in page.url
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
        page.goto(
            f"{live_server.url}/pendencias/?status=all"
            f"&categoria={chd_rnm.category_id}",
            wait_until="domcontentloaded",
        )
        assert "marcador-chd-b" in page.content()

    def test_mobile_categorized_panel(
        self, live_server, routed_browser_page
    ) -> None:
        new_page, _served = routed_browser_page
        _make_writer(username="s3_browser_mobile")
        scene = self._scene()
        chd_rnm = scene["chd_rnm"]
        chd_a = scene["chd_a"]
        assert isinstance(chd_rnm, PendingItemType)
        assert isinstance(chd_a, PendingItem)

        page = new_page(viewport={"width": 390, "height": 844})
        _login(page, live_server.url, "s3_browser_mobile")
        page.goto(
            f"{live_server.url}/pendencias/?view=items"
            f"&categoria={chd_rnm.category_id}&tipo={chd_rnm.pk}",
            wait_until="domcontentloaded",
        )
        content = page.content()
        assert "marcador-chd-a" in content
        assert "marcador-imagem-a" not in content
        assert "Data agendada: 10/11/2026" in content
        assert "Contraste: Sim" in content

        page.click(f'[data-testid="pending-history-{chd_a.pk}"]')
        page.wait_for_selector(
            f"#history-body-{chd_a.pk} >> text=Data agendada: 10/11/2026",
            timeout=15000,
        )
        assert "Detalhes não registrados nesta versão" in page.locator(
            f"#history-body-{chd_a.pk}"
        ).inner_text()

        page.click(f'[data-testid="pending-edit-{chd_a.pk}"]')
        page.wait_for_selector(
            "#pending-modal-body #id_scheduled_date",
            state="visible",
            timeout=15000,
        )
        page.click('#pending-modal-body button[data-bs-dismiss="modal"]')
        page.wait_for_selector(
            "#pending-modal-body #id_scheduled_date",
            state="hidden",
            timeout=15000,
        )
        assert _horizontal_overflow(page) <= 1
