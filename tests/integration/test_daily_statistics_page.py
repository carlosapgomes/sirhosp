"""DSRS-S6 integration tests: authorized daily statistics page and navigation.

Covers the vertical slice requirements:

- R1: the canonical route ``/statistics/`` requires authentication and the
  dedicated view permission, and a denial renders no nominal identity;
- R2: without a date the page selects yesterday when it is ready, otherwise
  the latest ready date, never today, and an unavailable date has an explicit
  state;
- R3: the nominal response is served with a ``private, no-store`` policy;
- R4: every sector header shows the metrics persisted by the closing
  measurement without recalculating capacity, occupancy, balance or excess;
- R5: each sector collapse carries entries, exits, events with an unidentified
  origin or destination and closing patients, every list keeping a zero badge
  and an explicit empty state, while an event with both endpoints unknown is
  shown once in the report-level ``Setor não identificado`` section;
- R6: the collapse controls keep their labels and accessible state;
- R7: patients and events follow the shared natural bed ordering;
- R8: the ``Estatísticas`` item appears only with permission, between
  ``Leitos`` and ``Fluxo Hospitalar``, and is active on the report route;
- R9: the page query budget does not grow with sectors, patients or events.

Everything here uses synthetic runs, sectors, beds and patients; no real
extraction data, no production access and no backfill.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.census.models import (
    CapacityCatalogVersion,
    OccupancyAgeBand,
    OccupancyCalculationStatus,
)
from apps.deaths.models import DeathRecord
from apps.statistics_reports.materialization import materialize_daily_statistics
from apps.statistics_reports.models import (
    DailyStatisticsEventKind,
    DailyStatisticsReport,
    DailyStatisticsSector,
)
from apps.statistics_reports.presentation import build_daily_report_projection
from tests.integration.test_daily_statistics_materialization import (
    ACTIVATION,
    DAY,
    OBSTETRIC_CODE,
    OBSTETRIC_NAME,
    _accepted_census,
    _bahia,
    _base_lines,
    _build_catalog,
    _CensusLine,
    _closing_lines,
    _default_group_specs,
    _group_spec,
)

PREVIOUS_DAY = DAY - timedelta(days=1)
WIDE_DAY = DAY + timedelta(days=1)

PAGE_URL_NAME = "statistics_reports:daily_report"
VIEW_PERMISSION_CODENAME = "view_daily_statistics"
EXPORT_PERMISSION_CODENAME = "export_daily_statistics"

GERAL_KEY = "GERAL"
ADULT_KEY = "OBST-3A-ADULTO"
INFANT_KEY = "OBST-3A-INFANTIL"
UNRATED_KEY = "NAO-TARIFADO"
UNMAPPED_CODE_KEY = "UNMAPPED-CODE-990"
UNMAPPED_NAME_KEY = "UNMAPPED-NAME-SEM-CODIGO"

GERAL_CODE = "900"
GERAL_SECTOR = "SETOR SINTETICO 900"
UNRATED_CODE = "950"
UNRATED_SECTOR = "SETOR SINTETICO 950"

ORDERING_BEDS = ("2", "10", "101A", "UTI02", "UTI10")
ORDERING_RECORDS = ("9101", "9102", "9103", "9104", "9105")

# Two patients present in the anchor photograph of the unmapped-capacity
# grouping leave before the opening one: their beds prove that events, like
# patients, follow the shared natural ordering instead of a lexical one.
ANCHOR_PATIENT = "7001"
ANCHOR_BED = "10"
ANCHOR_NAME = "PACIENTE ANCORA"
EARLY_PATIENT = "7004"
EARLY_BED = "2"
EARLY_NAME = "PACIENTE LEITO DOIS"
MOVING_PATIENT = "7003"
MOVING_BED = "3A-09"
MOVING_NAME = "PACIENTE TRANSFERIDO"
UNATTRIBUTED_PATIENT = "8801"
UNATTRIBUTED_NAME = "PACIENTE SEM SETOR"
DEATH_PATIENT = "8802"
DEATH_BED = "777-B"
DEATH_NAME = "PACIENTE OBITO SEM SETOR"
UNMAPPED_SECTOR_CODE = "777"
UNMAPPED_SECTOR_NAME = "SETOR FORA DO MAPA"
NO_GROUPING_PATIENT = "9901"
NO_GROUPING_NAME = "PACIENTE SEM AGRUPAMENTO"
NO_GROUPING_CODE = "999"

# Closing census rows of the shared fixture, used by the header metric test.
CLOSING_NAMES = (
    "PACIENTE GERAL UM",
    "PACIENTE GERAL DOIS",
    "PACIENTE ADULTO 3A",
    "RN BEBE SINTETICO",
    "PACIENTE SEM IDADE",
    "PACIENTE NAO TARIFADO",
    "PACIENTE SEM CATALOGO",
)

UNKNOWN_SECTION_TITLE = "Setor não identificado"

_PAGE_MODULE = "apps.statistics_reports.presentation"


def page_url() -> str:
    return reverse(PAGE_URL_NAME)


def dashboard_url() -> str:
    return reverse("services_portal:dashboard")


def _group_block(html: str, key: str) -> str:
    """One rendered group block, delimited by its own collapse target id."""
    marker = f'id="statistics-group-{key}"'
    start = html.index(marker)
    next_marker = html.find('id="statistics-group-', start + len(marker))
    return html[start:] if next_marker < 0 else html[start:next_marker]


def _sector_block(html: str, sector: DailyStatisticsSector) -> str:
    return _group_block(html, str(sector.pk))


def _list_badges(block: str) -> list[int]:
    """The count badge of every inner list of one rendered group block."""
    return [
        int(value)
        for value in re.findall(
            r'<span class="badge bg-secondary">(\d+)</span>', block
        )
    ]


def _list_block(block: str, key: str) -> str:
    """Rendered rows of one inner list, cut at the end of its list group."""
    parts = block.split(f'id="statistics-list-{key}"')
    assert len(parts) == 2, f"list {key} not found exactly once"
    return parts[1].split("</ul>")[0]

# ---------------------------------------------------------------------------
# Synthetic census helpers
# ---------------------------------------------------------------------------


def _patient_line(
    *,
    code: str,
    sector: str,
    bed: str,
    record: str,
    name: str,
    age_band: str = OccupancyAgeBand.NOT_APPLICABLE,
) -> _CensusLine:
    """One synthetic occupied, identified census row."""
    return _CensusLine(
        code=code,
        sector=sector,
        bed=bed,
        record=record,
        name=name,
        specialty="CLI",
        age_band=age_band,
    )


def _ordering_lines() -> list[_CensusLine]:
    """Identified patients used only to prove the natural bed ordering.

    They occupy stable beds of the ``GERAL`` grouping in every photograph of
    the day, so they produce no movement and only appear in the closing list.
    """
    return [
        _patient_line(
            code=GERAL_CODE,
            sector=GERAL_SECTOR,
            bed=bed,
            record=record,
            name=f"PACIENTE ORDEM {bed}",
        )
        for bed, record in zip(ORDERING_BEDS, ORDERING_RECORDS, strict=True)
    ]


def _anchor_lines() -> list[_CensusLine]:
    return (
        _base_lines()
        + _ordering_lines()
        + [
            _patient_line(
                code=UNRATED_CODE,
                sector=UNRATED_SECTOR,
                bed=EARLY_BED,
                record=EARLY_PATIENT,
                name=EARLY_NAME,
            ),
            _patient_line(
                code=UNRATED_CODE,
                sector=UNRATED_SECTOR,
                bed=ANCHOR_BED,
                record=ANCHOR_PATIENT,
                name=ANCHOR_NAME,
            ),
            _patient_line(
                code=GERAL_CODE,
                sector=GERAL_SECTOR,
                bed="900-Z2",
                record=MOVING_PATIENT,
                name=MOVING_NAME,
            ),
            _patient_line(
                code=UNMAPPED_SECTOR_CODE,
                sector=UNMAPPED_SECTOR_NAME,
                bed="777-A",
                record=UNATTRIBUTED_PATIENT,
                name=UNATTRIBUTED_NAME,
            ),
        ]
    )


def _opening_lines() -> list[_CensusLine]:
    return (
        _base_lines()
        + _ordering_lines()
        + [
            _patient_line(
                code=OBSTETRIC_CODE,
                sector=OBSTETRIC_NAME,
                bed=MOVING_BED,
                record=MOVING_PATIENT,
                name=MOVING_NAME,
                age_band=OccupancyAgeBand.AGE_12_OR_OVER,
            ),
            _patient_line(
                code=UNMAPPED_SECTOR_CODE,
                sector=UNMAPPED_SECTOR_NAME,
                bed="777-A",
                record=UNATTRIBUTED_PATIENT,
                name=UNATTRIBUTED_NAME,
            ),
        ]
    )


def _closing_lines_with_ordering(
    *,
    without_grouping: bool = False,
) -> list[_CensusLine]:
    lines = (
        _base_lines()
        + _closing_lines()
        + _ordering_lines()
        + [
            _patient_line(
                code=OBSTETRIC_CODE,
                sector=OBSTETRIC_NAME,
                bed=MOVING_BED,
                record=MOVING_PATIENT,
                name=MOVING_NAME,
                age_band=OccupancyAgeBand.AGE_12_OR_OVER,
            )
        ]
    )
    if without_grouping:
        lines.append(
            _patient_line(
                code=NO_GROUPING_CODE,
                sector="SETOR FORA DO CATALOGO",
                bed="999-A",
                record=NO_GROUPING_PATIENT,
                name=NO_GROUPING_NAME,
            )
        )
    return lines


def _death_lines() -> list[_CensusLine]:
    """Anchor/opening rows with one extra patient of an unmapped grouping.

    The record is absent from the closing photograph and carries death
    evidence, so its exit is a confirmed death whose only prior census
    position never resolved to an official grouping.
    """
    return _anchor_lines() + [
        _patient_line(
            code=UNMAPPED_SECTOR_CODE,
            sector=UNMAPPED_SECTOR_NAME,
            bed=DEATH_BED,
            record=DEATH_PATIENT,
            name=DEATH_NAME,
        )
    ]


def _death_evidence(*, record: str, name: str) -> DeathRecord:
    """One synthetic death row matching an exit inside the day window."""
    return DeathRecord.objects.create(
        date=DAY,
        prontuario=record,
        nome=name,
        data_obito="15/09/2026 06:00:00",
        obito_em=_bahia(DAY, 6, 0),
    )


def _wide_extra_lines() -> list[_CensusLine]:
    """Identified patients of twelve extra remote groupings."""
    return [
        _patient_line(
            code=str(800 + index),
            sector=f"SETOR REMOTO {800 + index}",
            bed=f"{800 + index}-A",
            record=f"95{index:02d}1",
            name=f"PACIENTE REMOTO {index}",
        )
        for index in range(12)
    ]


def _extra_unmapped_groups(count: int) -> list[dict[str, object]]:
    """Extra synthetic official groups persisted by a wide measurement."""
    return [
        _group_spec(
            stable_key=f"UNMAPPED-CODE-{800 + index}",
            display_name=f"SETOR REMOTO {800 + index}",
            calculation_status=OccupancyCalculationStatus.UNMAPPED,
            official_capacity=None,
            occupied_count=None,
            occupancy_percentage=None,
            exceeded_by=None,
            official_availability=None,
            calculation_policy="",
            components=[
                {
                    "observed_code": str(800 + index),
                    "observed_name": f"SETOR REMOTO {800 + index}",
                }
            ],
        )
        for index in range(count)
    ]


def _materialize_day(
    *,
    catalog: CapacityCatalogVersion,
    local_date: date,
    lines: list[_CensusLine],
    closing_lines: list[_CensusLine] | None = None,
    groups: list[dict[str, object]] | None = None,
) -> DailyStatisticsReport:
    """Materialize one complete synthetic day with anchor/opening/closing runs."""
    previous = local_date - timedelta(days=1)
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(previous, 21, 30),
        finished_at=_bahia(previous, 22, 0),
        lines=lines,
        groups=groups,
    )
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(previous, 23, 30),
        finished_at=_bahia(local_date, 0, 30),
        lines=lines,
        groups=groups,
    )
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(local_date, 21, 0),
        finished_at=_bahia(local_date, 21, 30),
        lines=closing_lines if closing_lines is not None else lines,
        groups=groups,
    )
    outcome = materialize_daily_statistics(
        local_date=local_date,
        activation_date=ACTIVATION,
    )
    return outcome.report


def _wide_day_payload() -> tuple[list[_CensusLine], list[_CensusLine], dict]:
    """Lines and measurement groups of the deliberately wider synthetic day."""
    extra = _wide_extra_lines()
    wide_lines = _anchor_lines() + extra
    wide_closing = (
        _closing_lines_with_ordering()
        + extra
        + [
            _patient_line(
                code=GERAL_CODE,
                sector=GERAL_SECTOR,
                bed=f"900-W{index}",
                record=f"970{index}",
                name=f"PACIENTE EXTRA {index}",
            )
            for index in range(6)
        ]
    )
    return wide_lines, wide_closing, {"groups": _default_group_specs() + _extra_unmapped_groups(12)}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def catalog(db: None) -> CapacityCatalogVersion:
    """Synthetic historical catalog of the shared DSRS-S2 fixtures."""
    return _build_catalog(
        effective_from=date(2026, 1, 1),
        algorithm_version="occupancy-v5",
        source_reference="synthetic DSRS-S6 catalog",
        source_sha256="f" * 64,
    )


@pytest.fixture
def report(catalog: CapacityCatalogVersion) -> DailyStatisticsReport:
    """The rich synthetic day: movements, unknown endpoints and ordering beds."""
    return _materialize_day(
        catalog=catalog,
        local_date=DAY,
        lines=_anchor_lines(),
        closing_lines=_closing_lines_with_ordering(),
    )


@pytest.fixture
def previous_report(catalog: CapacityCatalogVersion) -> DailyStatisticsReport:
    """One earlier complete day, so the default-date rules are testable."""
    return _materialize_day(
        catalog=catalog,
        local_date=PREVIOUS_DAY,
        lines=_anchor_lines(),
        closing_lines=_closing_lines_with_ordering(),
    )


@pytest.fixture
def statistics_viewer(db: None) -> User:
    user = User.objects.create_user(
        username="estatistica", password="testpass123"
    )
    user.user_permissions.add(
        Permission.objects.get(
            codename=VIEW_PERMISSION_CODENAME,
            content_type__app_label="statistics_reports",
        )
    )
    return user


@pytest.fixture
def viewer_client(statistics_viewer: User, client: Client) -> Client:
    client.login(username="estatistica", password="testpass123")
    return client


@pytest.fixture
def plain_client(db: None) -> Client:
    """A separate client logged in as a user WITHOUT the view permission."""
    User.objects.create_user(username="comum", password="testpass123")
    client = Client()
    client.login(username="comum", password="testpass123")
    return client


def _projection(response: Any) -> Any:
    return response.context["projection"]


def _group_of(projection: Any, stable_key: str) -> Any:
    """One rendered official grouping of a projection, by its stable key."""
    for group in projection.groups:
        if group.stable_key == stable_key:
            return group
    raise AssertionError(f"group {stable_key} not rendered")


def _unknown_group(projection: Any) -> Any:
    """The conditional report-level section of a projection."""
    unknown = projection.unknown_section
    assert unknown is not None, "unknown sector section missing"
    return unknown


# ---------------------------------------------------------------------------
# R1 - dedicated authorization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthorization:
    def test_anonymous_request_redirects_to_login(self, client: Client) -> None:
        response = client.get(page_url())
        assert response.status_code == 302
        assert reverse("login") in response["Location"]

    def test_authenticated_user_without_permission_is_denied(
        self, plain_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = plain_client.get(page_url())
        assert response.status_code == 403
        body = response.content.decode()
        assert CLOSING_NAMES[0] not in body
        assert "111" not in body

    def test_authorized_user_sees_the_nominal_page(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        assert response.status_code == 200
        body = response.content.decode()
        assert CLOSING_NAMES[0] in body
        assert UNKNOWN_SECTION_TITLE in body

    def test_view_permission_is_created_with_the_export_permission(
        self, db: None
    ) -> None:
        codenames = set(
            Permission.objects.filter(
                content_type__app_label="statistics_reports"
            ).values_list("codename", flat=True)
        )
        assert VIEW_PERMISSION_CODENAME in codenames
        assert EXPORT_PERMISSION_CODENAME in codenames


# ---------------------------------------------------------------------------
# R2 - safe default date and explicit unavailable state
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDefaultDate:
    def test_yesterday_is_selected_when_it_is_ready(
        self, viewer_client: Client, report: DailyStatisticsReport,
        previous_report: DailyStatisticsReport,
    ) -> None:
        with patch(f"{_PAGE_MODULE}._bahia_today", return_value=DAY + timedelta(days=1)):
            response = viewer_client.get(page_url())
        assert response.status_code == 200
        assert response.context["selected_date"] == DAY

    def test_latest_ready_date_is_selected_when_yesterday_is_not_ready(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        with patch(f"{_PAGE_MODULE}._bahia_today", return_value=DAY + timedelta(days=5)):
            response = viewer_client.get(page_url())
        assert response.context["selected_date"] == DAY

    def test_today_is_never_selected(
        self, viewer_client: Client, report: DailyStatisticsReport,
        previous_report: DailyStatisticsReport,
    ) -> None:
        with patch(f"{_PAGE_MODULE}._bahia_today", return_value=DAY):
            response = viewer_client.get(page_url())
        assert response.context["selected_date"] == PREVIOUS_DAY

    def test_day_without_ready_report_has_an_explicit_state(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(
            page_url(), {"date": (DAY + timedelta(days=2)).isoformat()}
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert response.context["projection"] is None
        assert "Nenhum relatório materializado" in body
        assert CLOSING_NAMES[0] not in body

    def test_malformed_date_falls_back_to_the_safe_default(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        with patch(f"{_PAGE_MODULE}._bahia_today", return_value=DAY + timedelta(days=1)):
            response = viewer_client.get(page_url(), {"date": "ontem"})
        assert response.status_code == 200
        assert response.context["selected_date"] == DAY


# ---------------------------------------------------------------------------
# R3 - sensitive response policy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResponsePolicy:
    def test_nominal_response_is_private_and_not_stored(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        assert response["Cache-Control"] == "private, no-store"

    def test_unavailable_date_keeps_the_same_policy(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(
            page_url(), {"date": (DAY + timedelta(days=3)).isoformat()}
        )
        assert response["Cache-Control"] == "private, no-store"


# ---------------------------------------------------------------------------
# R4 - persisted sector metrics only
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorHeader:
    def test_header_shows_persisted_metrics_without_recalculating(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        sector = DailyStatisticsSector.objects.get(
            report=report, stable_key=GERAL_KEY
        )
        DailyStatisticsSector.objects.filter(pk=sector.pk).update(
            official_capacity=123,
            occupied_count=45,
            occupancy_percentage=Decimal("12.34"),
            official_availability=78,
            exceeded_by=0,
        )
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        block = _sector_block(response.content.decode(), sector)
        assert "Pacientes: 45" in block
        assert "Capacidade: 123" in block
        assert "Lotação: 12,34%" in block
        assert "Saldo: 78" in block

    def test_non_calculable_group_keeps_its_persisted_state(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        unrated = DailyStatisticsSector.objects.get(
            report=report, stable_key=UNRATED_KEY
        )
        unmapped = DailyStatisticsSector.objects.get(
            report=report, stable_key=UNMAPPED_CODE_KEY
        )
        assert unrated.calculation_status == OccupancyCalculationStatus.UNRATED
        assert "fora da taxa oficial" in _sector_block(html, unrated)
        assert "Lotação: " not in _sector_block(html, unrated)
        assert "sem mapeamento no catálogo" in _sector_block(html, unmapped)

    def test_excess_replaces_the_balance_badge(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        sector = DailyStatisticsSector.objects.get(
            report=report, stable_key=GERAL_KEY
        )
        DailyStatisticsSector.objects.filter(pk=sector.pk).update(
            official_capacity=10,
            occupied_count=12,
            exceeded_by=2,
            official_availability=0,
        )
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        block = _sector_block(response.content.decode(), sector)
        assert "Excedente: 2" in block
        assert "Saldo: " not in block


# ---------------------------------------------------------------------------
# R5 - sector lists, empty states and the unknown sector section
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorLists:
    def test_each_sector_carries_the_four_lists(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        block = _sector_block(
            response.content.decode(),
            DailyStatisticsSector.objects.get(report=report, stable_key=GERAL_KEY),
        )
        assert "Entradas" in block
        assert "Saídas" in block
        assert "Eventos com origem ou destino não identificado" in block
        assert "Pacientes do fechamento" in block

    def test_list_counts_come_from_the_materialized_revision(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        projection = _projection(response)
        geral = _group_of(projection, GERAL_KEY)
        assert len(geral.entries) == 0
        assert len(geral.exits) == 1
        assert [row.event.record for row in geral.exits] == [MOVING_PATIENT]
        assert len(geral.unidentified) == 2
        assert len(geral.patients) == 7
        block = _sector_block(
            response.content.decode(),
            DailyStatisticsSector.objects.get(report=report, stable_key=GERAL_KEY),
        )
        assert _list_badges(block) == [0, 1, 2, 7]

    def test_transfer_is_rendered_as_an_exit_and_as_an_entry(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        projection = _projection(response)
        adult = _group_of(projection, ADULT_KEY)
        assert [row.event.record for row in adult.entries] == [MOVING_PATIENT]
        assert len(adult.exits) == 0

    def test_empty_list_keeps_a_zero_badge_and_an_explicit_state(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        sector = DailyStatisticsSector.objects.get(
            report=report, stable_key=UNMAPPED_NAME_KEY
        )
        block = _sector_block(response.content.decode(), sector)
        assert _list_badges(block) == [0, 0, 0, 0]
        assert "Nenhuma entrada detectada neste setor." in block
        assert "Nenhum paciente do fechamento neste setor." in block

    def test_unidentified_event_uses_its_descriptive_label(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        geral = _sector_block(
            html,
            DailyStatisticsSector.objects.get(report=report, stable_key=GERAL_KEY),
        )
        unrated = _sector_block(
            html,
            DailyStatisticsSector.objects.get(
                report=report, stable_key=UNRATED_KEY
            ),
        )
        assert "Entrada no setor — origem não identificada" in geral
        assert "Transferência interna" in geral
        assert "Saída do setor — destino não identificado" in unrated
        assert "Óbito" not in unrated

    def test_clinical_moment_and_detection_stay_separate(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        block = _sector_block(
            response.content.decode(),
            DailyStatisticsSector.objects.get(report=report, stable_key=GERAL_KEY),
        )
        assert "Momento clínico não informado" in block
        assert "Detecção:" in block

    def test_event_with_both_endpoints_unknown_is_shown_once(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        projection = _projection(response)
        unknown = _unknown_group(projection)
        assert [row.event.record for row in unknown.unidentified] == [
            UNATTRIBUTED_PATIENT
        ]
        block = _group_block(html, "unknown")
        assert UNKNOWN_SECTION_TITLE in block
        assert UNATTRIBUTED_NAME in block
        assert html.count(UNATTRIBUTED_NAME) == 1
        for group in projection.groups:
            if group.key == "unknown":
                continue
            assert UNATTRIBUTED_NAME not in _group_block(html, group.key)

    def test_death_without_resolvable_sector_is_shown_once(
        self, viewer_client: Client, catalog: CapacityCatalogVersion
    ) -> None:
        _death_evidence(record=DEATH_PATIENT, name=DEATH_NAME)
        report = _materialize_day(
            catalog=catalog,
            local_date=DAY,
            lines=_death_lines(),
            closing_lines=_closing_lines_with_ordering(),
        )
        events = list(report.events.filter(record=DEATH_PATIENT))
        assert [event.kind for event in events] == [
            DailyStatisticsEventKind.DEATH
        ]
        assert events[0].origin_sector_id is None
        assert events[0].destination_sector_id is None

        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        projection = _projection(response)
        unknown = _unknown_group(projection)
        unknown_deaths = [
            row
            for row in unknown.unidentified
            if row.event.record == DEATH_PATIENT
        ]
        assert len(unknown_deaths) == 1
        assert unknown_deaths[0].event.kind == DailyStatisticsEventKind.DEATH
        block = _group_block(html, "unknown")
        assert DEATH_NAME in block
        assert "Óbito" in block
        assert html.count(DEATH_NAME) == 1
        for group in projection.groups:
            if group.key == "unknown":
                continue
            assert DEATH_NAME not in _group_block(html, group.key)

    def test_closing_patient_without_grouping_is_not_omitted(
        self, viewer_client: Client, catalog: CapacityCatalogVersion
    ) -> None:
        report = _materialize_day(
            catalog=catalog,
            local_date=DAY,
            lines=_anchor_lines(),
            closing_lines=_closing_lines_with_ordering(without_grouping=True),
        )
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        unknown = _unknown_group(_projection(response))
        assert [patient.record for patient in unknown.patients] == [
            NO_GROUPING_PATIENT
        ]
        block = _group_block(html, "unknown")
        assert NO_GROUPING_NAME in block
        assert report.quality_warnings_json


# ---------------------------------------------------------------------------
# R6 - accessible collapse controls
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollapseAccessibility:
    def test_sector_control_keeps_label_target_and_state(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        sector = DailyStatisticsSector.objects.get(
            report=report, stable_key=GERAL_KEY
        )
        target = f"#statistics-sector-{sector.pk}"
        assert f'data-bs-target="{target}"' in html
        assert f'aria-controls="statistics-sector-{sector.pk}"' in html
        assert 'aria-expanded="false"' in html
        assert f'id="statistics-group-{sector.pk}"' in html
        assert sector.display_name in _sector_block(html, sector)

    def test_sector_control_is_a_native_keyboard_button(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        sector = DailyStatisticsSector.objects.get(
            report=report, stable_key=GERAL_KEY
        )
        target = f"statistics-sector-{sector.pk}"
        start = html.index(f'data-bs-target="#{target}"')
        tag_start = html.rindex("<button", 0, start)
        tag_end = html.index(">", start)
        trigger = html[tag_start:tag_end + 1]
        assert trigger.startswith('<button type="button"')
        assert 'role="button"' not in trigger
        assert 'aria-expanded="false"' in trigger
        assert f'aria-controls="{target}"' in trigger
        assert f'id="{target}"' in html
        assert sector.display_name in _sector_block(html, sector)

    def test_every_control_targets_an_existing_collapse(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        targets = re.findall(r'data-bs-target="#([^"]+)"', html)
        assert targets
        for target in targets:
            assert f'id="{target}"' in html


# ---------------------------------------------------------------------------
# R7 - shared natural ordering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNaturalOrdering:
    def test_patients_follow_the_natural_bed_order(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        sector = DailyStatisticsSector.objects.get(
            report=report, stable_key=GERAL_KEY
        )
        block = _sector_block(response.content.decode(), sector)
        patients = _list_block(block, f"{sector.pk}-patients")
        expected = [
            "PACIENTE ORDEM 2",
            "PACIENTE ORDEM 10",
            "PACIENTE ORDEM 101A",
            "PACIENTE GERAL UM",
            "PACIENTE GERAL DOIS",
            "PACIENTE ORDEM UTI02",
            "PACIENTE ORDEM UTI10",
        ]
        positions = [patients.index(f">{name}</span>") for name in expected]
        assert positions == sorted(positions)

    def test_events_follow_the_natural_bed_order(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        projection = _projection(response)
        unrated = _group_of(projection, UNRATED_KEY)
        assert [row.event.record for row in unrated.unidentified] == [
            EARLY_PATIENT,
            ANCHOR_PATIENT,
            "5001",
        ]
        assert [row.event.bed for row in unrated.unidentified] == [
            EARLY_BED,
            ANCHOR_BED,
            "950-A",
        ]


# ---------------------------------------------------------------------------
# R8 - authorized navigation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNavigation:
    def test_item_appears_between_beds_and_hospital_flow(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(dashboard_url())
        html = response.content.decode()
        assert "Estatísticas" in html
        assert html.index("Leitos") < html.index("Estatísticas")
        assert html.index("Estatísticas") < html.index("Fluxo Hospitalar")
        assert f'href="{page_url()}"' in html

    def test_item_is_hidden_without_permission(
        self, plain_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = plain_client.get(dashboard_url())
        assert response.status_code == 200
        assert "Estatísticas" not in response.content.decode()

    def test_item_is_active_on_the_report_route(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        assert (
            f'href="{page_url()}" class="sirhosp-sidebar-link active"' in html
        )


# ---------------------------------------------------------------------------
# R9 - bounded query budget
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestQueryBudget:
    def test_query_count_does_not_grow_with_sectors_patients_or_events(
        self, viewer_client: Client, catalog: CapacityCatalogVersion,
        report: DailyStatisticsReport,
    ) -> None:
        wide_lines, wide_closing, payload = _wide_day_payload()
        wide_report = _materialize_day(
            catalog=catalog,
            local_date=WIDE_DAY,
            lines=wide_lines,
            closing_lines=wide_closing,
            groups=payload["groups"],
        )
        with CaptureQueriesContext(connection) as small_ctx:
            small = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        with CaptureQueriesContext(connection) as big_ctx:
            big = viewer_client.get(page_url(), {"date": WIDE_DAY.isoformat()})
        assert small.status_code == 200
        assert big.status_code == 200

        small_projection = _projection(small)
        big_projection = _projection(big)
        assert len(big_projection.groups) > len(small_projection.groups)
        assert (
            sum(len(group.patients) for group in big_projection.groups)
            > sum(len(group.patients) for group in small_projection.groups)
        )
        assert wide_report.events.count() > report.events.count()
        assert len(big_ctx) == len(small_ctx)

    def test_projection_uses_the_same_bounded_queries_at_any_volume(
        self, catalog: CapacityCatalogVersion, report: DailyStatisticsReport
    ) -> None:
        wide_lines, wide_closing, payload = _wide_day_payload()
        wide_report = _materialize_day(
            catalog=catalog,
            local_date=WIDE_DAY,
            lines=wide_lines,
            closing_lines=wide_closing,
            groups=payload["groups"],
        )
        with CaptureQueriesContext(connection) as small_ctx:
            small = build_daily_report_projection(report)
        with CaptureQueriesContext(connection) as big_ctx:
            big = build_daily_report_projection(wide_report)
        assert len(small.groups) < len(big.groups)
        assert small.report.events.count() < big.report.events.count()
        assert len(small_ctx) == 3
        assert len(big_ctx) == len(small_ctx)


# ---------------------------------------------------------------------------
# Read-only surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReadOnlySurface:
    def test_page_offers_no_manual_correction(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        content = html[
            html.index('<main class="sirhosp-content">') :
            html.index("</main>")
        ]
        assert 'method="post"' not in content
        for affordance in ("Corrigir", "Reclassificar", "Excluir evento"):
            assert affordance not in content

    def test_page_states_the_selected_period_and_quality(
        self, viewer_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = viewer_client.get(page_url(), {"date": DAY.isoformat()})
        html = response.content.decode()
        assert "Revisão: 1" in html
        assert "Período:" in html
        assert "não são observáveis" in html
        assert "ambiguous_sector_mapping" in html