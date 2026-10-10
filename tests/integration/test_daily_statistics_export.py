"""ZIP-per-sector export integration tests: archive and served-export audit.

Covers the statistics-export-zip-per-sector slice requirements:

- R1: the export endpoint serves a ZIP with one XLSX per rendered grouping, in
  the order the page renders it, including the conditional ``setor_nao_``
  ``identificado`` file whenever the revision carries events with neither
  endpoint or closing patients without an attributable sector, neither of which
  is ever omitted;
- R2: the archive and its files carry the date and the revision, and each file
  uses a unique ``snake_case`` ASCII slug of its grouping title;
- R3: every file keeps the fixed sections in order -- admissions, transfer
  arrivals, deaths, transfer departures, hospital discharges, events with an
  unidentified endpoint and the closing patients -- with counts, fields and
  the natural ordering of the page, and formula-significant text stays text;
- R4: the export endpoint requires ``export_daily_statistics`` independently
  of the consultation permission and serves a ``private, no-store`` archive;
- R5: a served archive records user, instant, selected date, revision,
  ``file_count`` and aggregate row counts, while a failure before the prepared
  response records nothing, and legacy audit rows read back with
  ``file_count=1``;
- R6: the archive is built in memory, no file is persisted and the query budget
  does not grow with the revision;
- R7: the page offers a single ``Exportar ZIP por setor`` action and no second
  format or endpoint exists.

Everything here uses synthetic runs, sectors, beds and patients; no real
extraction data, no production access and no persisted archive.
"""

from __future__ import annotations

import time
import zipfile
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from apps.census.models import CapacityCatalogVersion
from apps.patients.models import Patient
from apps.statistics_reports.export import (
    MAX_FILENAME_CHARS,
    ZIP_CONTENT_TYPE,
    build_sector_zip,
    build_single_group_workbook,
    sector_file_slugs,
    sector_slug,
    sector_xlsx_filename,
)
from apps.statistics_reports.models import DailyStatisticsReport, StatisticsExportLog
from apps.statistics_reports.presentation import (
    DailyReportProjection,
    ReportGroup,
    build_daily_report_projection,
)
from tests.integration.test_daily_statistics_materialization import (
    _base_lines,
    _build_catalog,
    _closing_lines,
)
from tests.integration.test_daily_statistics_page import (
    DAY,
    DEATH_NAME,
    DEATH_PATIENT,
    EXPORT_PERMISSION_CODENAME,
    GERAL_CODE,
    GERAL_KEY,
    GERAL_SECTOR,
    LSPA_RESOLVED_RECORD,
    MOVING_NAME,
    NO_GROUPING_CODE,
    NO_GROUPING_NAME,
    NO_GROUPING_PATIENT,
    UNATTRIBUTED_NAME,
    UNATTRIBUTED_PATIENT,
    UNKNOWN_SECTION_TITLE,
    VIEW_PERMISSION_CODENAME,
    WIDE_DAY,
    _anchor_lines,
    _closing_lines_with_ordering,
    _death_evidence,
    _death_lines,
    _group_of,
    _materialize_day,
    _patient_line,
    _wide_day_payload,
    page_url,
)

EXPORT_URL_NAME = "statistics_reports:daily_report_export"

EXPECTED_SECTIONS = (
    "Internações",
    "Transferências de entrada",
    "Óbitos",
    "Transferências de saída",
    "Altas hospitalares",
    "Eventos com origem ou destino não identificado",
    "Pacientes do fechamento",
)

EVENT_HEADERS = [
    "Leito",
    "Nome",
    "Prontuário",
    "Tipo",
    "Momento clínico",
    "Origem",
    "Destino",
    "Detecção",
]

PATIENT_HEADERS = ["Leito", "Nome", "Prontuário", "Especialidade"]

GERAL_SHEET = "Gerais"

FORBIDDEN_FILENAME_CHARS = set('<>:"/\\|?*')


def export_url() -> str:
    return reverse(EXPORT_URL_NAME)


def _archive_files(response: Any) -> dict[str, Workbook]:
    """Every XLSX of the served ZIP, reopened by file name."""
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        return {
            name: load_workbook(BytesIO(archive.read(name)))
            for name in archive.namelist()
        }


def _expected_filenames(projection: DailyReportProjection) -> list[str]:
    """Archive file names the projection must produce, in page order."""
    slugs = sector_file_slugs(
        projection.report, [group.title for group in projection.groups]
    )
    return [
        sector_xlsx_filename(projection.report, slug) for slug in slugs
    ]


def _section(worksheet: Worksheet, title: str) -> tuple[int, list[object], list[list[object]]]:
    """Count cell, header row and data rows of one fixed section of a sheet."""
    for row_index in range(1, worksheet.max_row + 1):
        if worksheet.cell(row=row_index, column=1).value != title:
            continue
        count = worksheet.cell(row=row_index, column=2).value
        header = [
            worksheet.cell(row=row_index + 1, column=column).value
            for column in range(1, worksheet.max_column + 1)
        ]
        width = len([value for value in header if value is not None])
        rows: list[list[object]] = []
        cursor = row_index + 2
        while cursor <= worksheet.max_row:
            first = worksheet.cell(row=cursor, column=1).value
            if first is None or first in EXPECTED_SECTIONS:
                break
            rows.append(
                [worksheet.cell(row=cursor, column=column).value for column in range(1, width + 1)]
            )
            cursor += 1
        return int(count), header[:width], rows
    raise AssertionError(f"section {title!r} not found in {worksheet.title!r}")


def _sheet_sections(worksheet: Worksheet) -> list[str]:
    """Every section title of one sheet, in the order it is written."""
    return [
        worksheet.cell(row=row, column=1).value
        for row in range(1, worksheet.max_row + 1)
        if worksheet.cell(row=row, column=1).value in EXPECTED_SECTIONS
    ]


def _data_row_count(workbook: Workbook) -> int:
    """Aggregate data rows of one single-sheet XLSX, section titles excluded."""
    total = 0
    for name in workbook.sheetnames:
        worksheet = workbook[name]
        for title in EXPECTED_SECTIONS:
            total += len(_section(worksheet, title)[2])
    return total


def _single_sheet(files: dict[str, Workbook]) -> Worksheet:
    """The only worksheet of a one-file archive entry."""
    assert len(files) == 1
    workbook = next(iter(files.values()))
    assert len(workbook.sheetnames) == 1
    return workbook[workbook.sheetnames[0]]


def archive_filenames(content: bytes) -> list[str]:
    """File names of a ZIP archive built in memory."""
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return archive.namelist()


NO_GROUPING_SECTOR = "SETOR FORA DO CATALOGO"
NO_GROUPING_BED = "999-A"


def _patient_only_unattributable_report(
    catalog: CapacityCatalogVersion,
) -> DailyStatisticsReport:
    """A day whose only unattributable row is one ungrouped closing patient.

    The both-endpoint-null anchor patient is removed and the ungrouped patient
    is present in the opening and the closing photograph, so the revision has
    no event whose endpoints are both null and its sole unattributable row is
    that closing patient.
    """
    ungrouped = _patient_line(
        code=NO_GROUPING_CODE,
        sector=NO_GROUPING_SECTOR,
        bed=NO_GROUPING_BED,
        record=NO_GROUPING_PATIENT,
        name=NO_GROUPING_NAME,
    )
    opening = [
        line for line in _anchor_lines() if line.record != UNATTRIBUTED_PATIENT
    ]
    opening.append(ungrouped)
    return _materialize_day(
        catalog=catalog,
        local_date=DAY,
        lines=opening,
        closing_lines=_closing_lines_with_ordering(without_grouping=True),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog(db: None) -> CapacityCatalogVersion:
    """Synthetic historical catalog of the shared DSRS-S2 fixtures."""
    return _build_catalog(
        effective_from=date(2026, 1, 1),
        algorithm_version="occupancy-v5",
        source_reference="synthetic DSRS-S7 catalog",
        source_sha256="e" * 64,
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


def _permission(codename: str) -> Permission:
    return Permission.objects.get(
        codename=codename,
        content_type__app_label="statistics_reports",
    )


def _logged_in_client(*, username: str, codenames: tuple[str, ...]) -> Client:
    user = User.objects.create_user(username=username, password="testpass123")
    user.user_permissions.add(*[_permission(name) for name in codenames])
    client = Client()
    client.login(username=username, password="testpass123")
    return client


@pytest.fixture
def export_client(db: None) -> Client:
    """A client holding both the consultation and the export permission."""
    return _logged_in_client(
        username="exportador",
        codenames=(VIEW_PERMISSION_CODENAME, EXPORT_PERMISSION_CODENAME),
    )


@pytest.fixture
def export_only_client(db: None) -> Client:
    """A client holding only the export permission, without consultation."""
    return _logged_in_client(
        username="somente-exportacao",
        codenames=(EXPORT_PERMISSION_CODENAME,),
    )


@pytest.fixture
def view_only_client(db: None) -> Client:
    """A client holding only the consultation permission."""
    return _logged_in_client(
        username="somente-consulta",
        codenames=(VIEW_PERMISSION_CODENAME,),
    )


@pytest.fixture
def plain_client(db: None) -> Client:
    """A separate client logged in as a user WITHOUT any report permission."""
    return _logged_in_client(username="comum", codenames=())


# ---------------------------------------------------------------------------
# R4 - independent authorization and sensitive response policy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportAuthorization:
    def test_anonymous_request_redirects_to_login(
        self, client: Client, report: DailyStatisticsReport
    ) -> None:
        response = client.get(export_url())
        assert response.status_code == 302
        assert reverse("login") in response["Location"]

    def test_view_permission_alone_is_not_enough(
        self, view_only_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = view_only_client.get(export_url(), {"date": DAY.isoformat()})
        assert response.status_code == 403
        assert StatisticsExportLog.objects.count() == 0

    def test_user_without_any_permission_is_denied(
        self, plain_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = plain_client.get(export_url(), {"date": DAY.isoformat()})
        assert response.status_code == 403
        assert StatisticsExportLog.objects.count() == 0

    def test_export_permission_alone_allows_the_download(
        self, export_only_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = export_only_client.get(export_url(), {"date": DAY.isoformat()})
        assert response.status_code == 200
        assert response["Content-Type"] == ZIP_CONTENT_TYPE

    def test_served_archive_is_private_and_not_stored(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, no-store"

    def test_unavailable_date_serves_no_archive_and_logs_nothing(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = export_client.get(export_url(), {"date": (DAY + timedelta(days=2)).isoformat()})
        assert response.status_code == 404
        assert StatisticsExportLog.objects.count() == 0

    def test_page_offers_the_zip_export_link_with_the_export_permission(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = export_client.get(page_url(), {"date": DAY.isoformat()})
        body = response.content.decode()
        assert response.status_code == 200
        assert f'href="{export_url()}?date={DAY.isoformat()}"' in body
        assert "Exportar ZIP por setor" in body
        assert "Exportar XLSX" not in body

    def test_page_hides_the_export_link_without_the_export_permission(
        self, view_only_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = view_only_client.get(page_url(), {"date": DAY.isoformat()})
        body = response.content.decode()
        assert response.status_code == 200
        assert "Exportar ZIP por setor" not in body
        assert "Exportar XLSX" not in body
        assert export_url() not in body


# ---------------------------------------------------------------------------
# R6 - in-memory archive and safe filenames (R2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestZipDelivery:
    def test_workbooks_are_built_in_memory_only(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        saved: list[Any] = []
        real_save = Workbook.save

        def spy(*args: Any, **kwargs: Any) -> None:
            target = args[1] if len(args) > 1 else kwargs.get("filename")
            saved.append(target)
            real_save(*args, **kwargs)

        with patch.object(Workbook, "save", new=spy):
            response = export_client.get(export_url(), {"date": DAY.isoformat()})
        assert response.status_code == 200
        assert saved
        assert all(isinstance(target, BytesIO) for target in saved)

    def test_archive_filename_depends_only_on_date_and_revision(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        expected = (
            f'attachment; filename="estatisticas-diarias-{DAY.isoformat()}-r{report.revision}.zip"'
        )
        assert response["Content-Disposition"] == expected
        assert MOVING_NAME not in response["Content-Disposition"]

    def test_no_export_file_is_left_behind(
        self, export_client: Client, report: DailyStatisticsReport, tmp_path: Path
    ) -> None:
        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        filename = response["Content-Disposition"].split('filename="')[1][:-1]
        assert response.status_code == 200
        assert filename.endswith(".zip")
        assert not (tmp_path / filename).exists()
        assert not (Path.cwd() / filename).exists()

    def test_internal_filenames_carry_date_revision_and_unique_slugs(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            names = archive.namelist()
        stem = f"estatisticas-diarias-{DAY.isoformat()}-r{report.revision}"
        assert names == _expected_filenames(projection)
        assert len(names) == len(projection.groups)
        assert len(set(names)) == len(names)
        for name in names:
            assert name.startswith(f"{stem}-")
            assert name.endswith(".xlsx")
            assert len(name) <= MAX_FILENAME_CHARS
            assert name == name.encode("ascii").decode("ascii")
            assert not name.startswith(".")
            assert not FORBIDDEN_FILENAME_CHARS & set(name)


# ---------------------------------------------------------------------------
# R1 - one XLSX per grouping plus the conditional unknown file
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestZipFiles:
    def test_one_file_per_rendered_grouping_in_page_order(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        files = _archive_files(response)
        assert list(files) == _expected_filenames(projection)
        assert len(files) == len(projection.groups)

    def test_each_file_identifies_its_full_grouping_name(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        for group, name in zip(projection.groups, files, strict=True):
            workbook = files[name]
            assert len(workbook.sheetnames) == 1
            worksheet = workbook[workbook.sheetnames[0]]
            assert worksheet.cell(row=1, column=1).value == group.title
            expected_key = group.stable_key or "sem agrupamento oficial"
            assert worksheet.cell(row=1, column=2).value == expected_key
            assert (
                worksheet.cell(row=2, column=1).value
                == f"Data do relatório: {report.local_date.isoformat()}"
            )
            assert (
                worksheet.cell(row=2, column=2).value
                == f"Revisão: {report.revision}"
            )

    def test_sheet_names_are_valid_and_keep_the_full_name(
        self, report: DailyStatisticsReport
    ) -> None:
        long_title = "SETOR " + "MUITO LONGO " * 4
        titles = [
            "SETOR COLIDE:1",
            "SETOR COLIDE/1",
            long_title,
            "SETOR [INVALIDO]?",
        ]
        slugs = sector_file_slugs(report, titles)
        assert len(set(slugs)) == len(titles)
        groups = tuple(
            ReportGroup(
                key=key,
                stable_key=key,
                title=title,
                is_unknown_section=False,
                header_badges=(),
            )
            for key, title in zip(("a", "b", "c", "d"), titles, strict=True)
        )
        # Each archived file holds a single sheet, so sheets never collide
        # with each other: uniqueness across files lives in the slugs while
        # each sheet only needs a valid name and the full title inside.
        for group, slug in zip(groups, slugs, strict=True):
            single = build_single_group_workbook(group, report, slug)
            assert single.filename == sector_xlsx_filename(report, slug)
            workbook = load_workbook(BytesIO(single.content))
            assert len(workbook.sheetnames) == 1
            sheet = workbook[workbook.sheetnames[0]]
            assert len(sheet.title) <= 31
            assert not set(sheet.title) & set("[]:*?/\\")
            assert sheet.cell(row=1, column=1).value == group.title
        assert slugs[0] == "setor_colide_1"
        assert slugs[1] == "setor_colide_1_2"

    def test_unknown_section_becomes_a_conditional_file(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        assert projection.unknown_section is not None
        unknown_name = sector_xlsx_filename(
            report, sector_slug(UNKNOWN_SECTION_TITLE)
        )
        assert unknown_name == _expected_filenames(projection)[0]
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        unknown = _single_sheet({unknown_name: files[unknown_name]})
        values = [cell.value for row in unknown.iter_rows() for cell in row]
        assert UNATTRIBUTED_NAME in values
        for name, workbook in files.items():
            if name == unknown_name:
                continue
            other = workbook[workbook.sheetnames[0]]
            assert UNATTRIBUTED_NAME not in [
                cell.value for row in other.iter_rows() for cell in row
            ]

    def test_unattributable_patient_alone_creates_the_conditional_file(
        self, export_client: Client, catalog: CapacityCatalogVersion
    ) -> None:
        report = _patient_only_unattributable_report(catalog)
        assert not report.events.filter(
            origin_sector__isnull=True, destination_sector__isnull=True
        ).exists()
        projection = build_daily_report_projection(report)
        assert projection.unknown_section is not None
        assert projection.unknown_section.unidentified == ()
        assert [
            patient.record for patient in projection.unknown_section.patients
        ] == [NO_GROUPING_PATIENT]

        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        assert list(files) == _expected_filenames(projection)
        assert len(files) == len(projection.groups)
        unknown_name = sector_xlsx_filename(
            report, sector_slug(UNKNOWN_SECTION_TITLE)
        )
        unknown = _single_sheet({unknown_name: files[unknown_name]})
        values = [cell.value for row in unknown.iter_rows() for cell in row]
        assert NO_GROUPING_NAME in values
        for name, workbook in files.items():
            if name == unknown_name:
                continue
            other = workbook[workbook.sheetnames[0]]
            assert NO_GROUPING_NAME not in [
                cell.value for row in other.iter_rows() for cell in row
            ]

    def test_unknown_file_is_absent_without_unattributable_rows(
        self, catalog: CapacityCatalogVersion
    ) -> None:
        report = _materialize_day(
            catalog=catalog,
            local_date=DAY,
            lines=_base_lines(),
            closing_lines=_base_lines() + _closing_lines(),
        )
        assert not report.events.filter(
            origin_sector__isnull=True, destination_sector__isnull=True
        ).exists()
        assert not report.patients.filter(sector__isnull=True).exists()
        projection = build_daily_report_projection(report)
        assert projection.unknown_section is None
        archive = build_sector_zip(projection)
        assert (
            sector_xlsx_filename(report, sector_slug(UNKNOWN_SECTION_TITLE))
            not in archive_filenames(archive.content)
        )

    def test_event_without_any_endpoint_is_never_omitted(
        self, export_client: Client, catalog: CapacityCatalogVersion
    ) -> None:
        _death_evidence(record=DEATH_PATIENT, name=DEATH_NAME)
        made = _materialize_day(
            catalog=catalog,
            local_date=DAY,
            lines=_death_lines(),
            closing_lines=_closing_lines_with_ordering(),
        )
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        unknown_name = sector_xlsx_filename(
            made,
            sector_slug(UNKNOWN_SECTION_TITLE),
        )
        unknown = _single_sheet({unknown_name: files[unknown_name]})
        values = [cell.value for row in unknown.iter_rows() for cell in row]
        assert DEATH_NAME in values
        assert DEATH_PATIENT in values


# ---------------------------------------------------------------------------
# R3 - fixed sections, counts, fields and natural ordering per file
# ---------------------------------------------------------------------------


def _geral_file(
    files: dict[str, Workbook], projection: DailyReportProjection
) -> Workbook:
    """The archived XLSX of the official ``GERAL`` grouping."""
    group = _group_of(projection, GERAL_KEY)
    name = sector_xlsx_filename(
        projection.report, sector_slug(group.title)
    )
    return files[name]


@pytest.mark.django_db
class TestFileSections:
    def test_every_file_keeps_the_fixed_sections_in_order(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        assert files
        for workbook in files.values():
            assert len(workbook.sheetnames) == 1
            worksheet = workbook[workbook.sheetnames[0]]
            assert tuple(_sheet_sections(worksheet)) == EXPECTED_SECTIONS

    def test_empty_sections_stay_present_with_a_zero_count(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        worksheet = _geral_file(files, projection)[GERAL_SHEET]
        count, headers, rows = _section(worksheet, "Internações")
        assert count == 0
        assert rows == []
        assert headers == EVENT_HEADERS

    def test_section_counts_match_the_page_projection(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        for group, name in zip(projection.groups, files, strict=True):
            worksheet = files[name][files[name].sheetnames[0]]
            assert _section(worksheet, "Internações")[0] == len(group.admissions)
            assert _section(worksheet, "Transferências de entrada")[0] == len(
                group.transfer_entries
            )
            assert _section(worksheet, "Óbitos")[0] == len(group.deaths)
            assert _section(worksheet, "Transferências de saída")[0] == len(group.transfer_exits)
            assert _section(worksheet, "Altas hospitalares")[0] == len(group.discharges)
            assert _section(worksheet, "Eventos com origem ou destino não identificado")[0] == len(
                group.unidentified
            )
            assert _section(worksheet, "Pacientes do fechamento")[0] == len(group.patients)

    def test_closing_patients_keep_the_page_fields_and_order(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        group = _group_of(projection, GERAL_KEY)
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        worksheet = _geral_file(files, projection)[GERAL_SHEET]
        _, headers, rows = _section(worksheet, "Pacientes do fechamento")
        assert headers == PATIENT_HEADERS
        assert [row[1] for row in rows] == [patient.name for patient in group.patients]
        assert [row[0] for row in rows] == [patient.bed for patient in group.patients]
        assert [row[2] for row in rows] == [patient.record for patient in group.patients]
        assert [row[3] for row in rows] == [patient.specialty for patient in group.patients]

    def test_event_rows_keep_the_page_fields_and_order(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        group = _group_of(projection, GERAL_KEY)
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        worksheet = _geral_file(files, projection)[GERAL_SHEET]
        _, headers, rows = _section(
            worksheet,
            "Eventos com origem ou destino não identificado",
        )
        assert headers == EVENT_HEADERS
        assert rows
        assert [row[0] for row in rows] == [row.event.bed for row in group.unidentified]
        assert [row[1] for row in rows] == [row.event.name for row in group.unidentified]
        assert [row[2] for row in rows] == [row.event.record for row in group.unidentified]
        assert [row[3] for row in rows] == [rendered.label for rendered in group.unidentified]
        assert [row[4] for row in rows] == [
            rendered.clinical_display for rendered in group.unidentified
        ]
        assert [row[5] for row in rows] == [
            rendered.origin_display for rendered in group.unidentified
        ]
        assert [row[6] for row in rows] == [
            rendered.destination_display for rendered in group.unidentified
        ]
        assert [row[7] for row in rows] == [
            rendered.detection_display for rendered in group.unidentified
        ]


# ---------------------------------------------------------------------------
# R3 - formula-significant text is written as safe text
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFormulaSafety:
    def test_formula_like_text_is_stored_as_text(
        self, export_client: Client, catalog: CapacityCatalogVersion
    ) -> None:
        dangerous = ("=1+1", "+1+1", "-1+1", "@SUM(A1)")
        extra = [
            _patient_line(
                code=GERAL_CODE,
                sector=GERAL_SECTOR,
                bed=f"D{index}",
                record=f"770{index}",
                name=name,
            )
            for index, name in enumerate(dangerous)
        ]
        _materialize_day(
            catalog=catalog,
            local_date=DAY,
            lines=_anchor_lines() + extra,
            closing_lines=_closing_lines_with_ordering() + extra,
        )
        made = DailyStatisticsReport.objects.get(local_date=DAY, status="ready")
        projection = build_daily_report_projection(made)
        files = _archive_files(
            export_client.get(export_url(), {"date": DAY.isoformat()})
        )
        found: dict[str, str] = {}
        worksheet = _geral_file(files, projection)[GERAL_SHEET]
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.value in dangerous:
                    found[cell.value] = cell.data_type
        assert set(found) == set(dangerous)
        assert all(data_type == "s" for data_type in found.values())


# ---------------------------------------------------------------------------
# R5 - served-export audit log
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportAudit:
    def test_success_logs_user_date_revision_and_aggregate_counts(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        projection = build_daily_report_projection(report)
        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        files = _archive_files(response)
        logs = list(StatisticsExportLog.objects.all())
        assert len(logs) == 1
        log = logs[0]
        assert log.user == User.objects.get(username="exportador")
        assert log.report == report
        assert log.report.local_date == DAY
        assert log.report.revision == report.revision
        assert log.file_count == len(files) == len(projection.groups)
        assert log.sheet_count == log.file_count
        assert log.row_count == sum(
            _data_row_count(workbook) for workbook in files.values()
        )
        assert log.row_count > 0
        assert log.served_at is not None

    def test_failure_before_the_response_logs_no_success(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        with patch(
            "apps.statistics_reports.views.build_sector_zip",
            side_effect=RuntimeError("archive generation failed"),
        ):
            with pytest.raises(RuntimeError):
                export_client.get(export_url(), {"date": DAY.isoformat()})
        assert StatisticsExportLog.objects.count() == 0

    def test_failure_constructing_the_response_logs_no_success(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        with patch(
            "apps.statistics_reports.views.HttpResponse",
            side_effect=RuntimeError("response construction failed"),
        ):
            with pytest.raises(RuntimeError):
                export_client.get(export_url(), {"date": DAY.isoformat()})
        assert StatisticsExportLog.objects.count() == 0

    def test_failure_configuring_the_response_headers_logs_no_success(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        with patch("apps.statistics_reports.views.HttpResponse") as response_cls:
            response_cls.return_value.__setitem__.side_effect = RuntimeError(
                "response header configuration failed"
            )
            with pytest.raises(RuntimeError):
                export_client.get(export_url(), {"date": DAY.isoformat()})
        assert StatisticsExportLog.objects.count() == 0

    def test_audit_model_carries_no_nominal_payload(self) -> None:
        field_names = {field.name for field in StatisticsExportLog._meta.concrete_fields}
        assert field_names == {
            "id",
            "user",
            "report",
            "served_at",
            "file_count",
            "sheet_count",
            "row_count",
        }

    def test_new_rows_require_an_explicit_file_count(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        user = User.objects.get(username="exportador")
        with pytest.raises(IntegrityError):
            StatisticsExportLog.objects.create(
                user=user,
                report=report,
                sheet_count=1,
                row_count=1,
            )

    @pytest.mark.django_db(transaction=True)
    def test_legacy_rows_are_backfilled_with_file_count_one(
        self, catalog: CapacityCatalogVersion
    ) -> None:
        report = _materialize_day(
            catalog=catalog,
            local_date=DAY,
            lines=_anchor_lines(),
            closing_lines=_closing_lines_with_ordering(),
        )
        user = User.objects.create_user(username="legado", password="testpass123")
        call_command(
            "migrate", "statistics_reports", "0005", verbosity=0, interactive=False
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO statistics_reports_statisticsexportlog
                    (served_at, sheet_count, row_count, report_id, user_id)
                VALUES (NOW(), 3, 10, %s, %s)
                """,
                [report.pk, user.pk],
            )
        call_command("migrate", "statistics_reports", verbosity=0, interactive=False)
        log = StatisticsExportLog.objects.get(report=report, user=user)
        assert log.sheet_count == 3
        assert log.row_count == 10
        assert log.file_count == 1


# ---------------------------------------------------------------------------
# R6 - bounded read of the same projection as the page, plus load evidence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportQueryBudget:
    def test_query_count_does_not_grow_with_the_revision(
        self, export_client: Client, catalog: CapacityCatalogVersion, report: DailyStatisticsReport
    ) -> None:
        wide_lines, wide_closing, payload = _wide_day_payload()
        _materialize_day(
            catalog=catalog,
            local_date=WIDE_DAY,
            lines=wide_lines,
            closing_lines=wide_closing,
            groups=payload["groups"],
        )
        with CaptureQueriesContext(connection) as small_ctx:
            small = export_client.get(export_url(), {"date": DAY.isoformat()})
        with CaptureQueriesContext(connection) as big_ctx:
            big = export_client.get(export_url(), {"date": WIDE_DAY.isoformat()})
        assert small.status_code == 200
        assert big.status_code == 200
        assert len(_archive_files(big)) > len(_archive_files(small))
        assert len(big_ctx) == len(small_ctx)

    def test_amplified_wide_day_zip_reports_size_and_time(
        self, export_client: Client, catalog: CapacityCatalogVersion
    ) -> None:
        wide_lines, wide_closing, payload = _wide_day_payload()
        heavy_extra = [
            _patient_line(
                code=GERAL_CODE,
                sector=GERAL_SECTOR,
                bed=f"990-H{index}",
                record=f"9810{index:03d}",
                name=f"PACIENTE CARGA {index:03d}",
            )
            for index in range(300)
        ]
        _materialize_day(
            catalog=catalog,
            local_date=WIDE_DAY,
            lines=wide_lines + heavy_extra,
            closing_lines=wide_closing + heavy_extra,
            groups=payload["groups"],
        )
        started = time.perf_counter()
        response = export_client.get(export_url(), {"date": WIDE_DAY.isoformat()})
        elapsed = time.perf_counter() - started
        assert response.status_code == 200
        assert response["Content-Type"] == ZIP_CONTENT_TYPE
        files = _archive_files(response)
        assert files
        for workbook in files.values():
            assert len(workbook.sheetnames) == 1
        print(
            f"\n[zip-load] files={len(files)} "
            f"bytes={len(response.content)} "
            f"seconds={elapsed:.2f}"
        )


# ---------------------------------------------------------------------------
# LSPA-S1 - the archive never carries the read-time navigation
# ---------------------------------------------------------------------------

REGISTERED_PATIENT_PK = 908172
"""Identifier no count, label or revision of the archive can carry."""


def _archive_cell_values(
    files: dict[str, Workbook],
) -> dict[tuple[str, str, int, int], object]:
    """Every written cell of one archive, keyed by file, sheet, row, column."""
    return {
        (name, sheet, cell.row, cell.column): cell.value
        for name, workbook in files.items()
        for sheet in workbook.sheetnames
        for row in workbook[sheet].iter_rows()
        for cell in row
    }


@pytest.mark.django_db
class TestArchiveWithoutNominalNavigation:
    def test_archive_is_unchanged_while_the_projection_resolves_records(
        self, export_client: Client, report: DailyStatisticsReport
    ) -> None:
        fingerprint = report.source_fingerprint
        without_resolution = _archive_cell_values(
            {
                name: load_workbook(BytesIO(content))
                for name, content in _raw_zip_entries(
                    build_sector_zip(
                        build_daily_report_projection(report)
                    ).content
                ).items()
            }
        )
        registered = Patient.objects.create(
            pk=REGISTERED_PATIENT_PK,
            patient_source_key=LSPA_RESOLVED_RECORD,
            source_system="tasy",
            name="PACIENTE CADASTRADO",
        )
        projection = build_daily_report_projection(report)
        assert any(
            patient.patient_id == registered.pk
            for group in projection.groups
            for patient in group.patients
        )

        response = export_client.get(export_url(), {"date": DAY.isoformat()})
        assert response.status_code == 200
        files = _archive_files(response)
        assert _archive_cell_values(files) == without_resolution
        assert not any(
            value == registered.pk or value == str(registered.pk)
            for value in without_resolution.values()
        )
        geral = _group_of(projection, GERAL_KEY)
        worksheet = _geral_file(files, projection)[GERAL_SHEET]
        count, headers, rows = _section(
            worksheet, "Pacientes do fechamento"
        )
        assert headers == PATIENT_HEADERS
        assert count == len(geral.patients)
        assert [row[1] for row in rows] == [
            patient.name for patient in geral.patients
        ]
        assert (
            DailyStatisticsReport.objects.get(
                pk=report.pk
            ).source_fingerprint
            == fingerprint
        )


def _raw_zip_entries(content: bytes) -> dict[str, bytes]:
    """Raw bytes of every entry of a ZIP archive built in memory."""
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


# ---------------------------------------------------------------------------
# R7 - single export path: no parallel endpoint or format
# ---------------------------------------------------------------------------


def test_no_parallel_export_endpoint_or_format() -> None:
    """The ZIP replaces the single-workbook download; nothing runs beside it."""
    from django.urls import URLPattern, URLResolver, get_resolver

    from apps.statistics_reports import export as export_module
    from apps.statistics_reports import views as views_module

    seen: list[str] = []

    def collect(patterns: list[URLPattern | URLResolver]) -> None:
        for entry in patterns:
            if isinstance(entry, URLResolver):
                collect(entry.url_patterns)
            else:
                seen.append(str(entry.pattern))

    collect(get_resolver().url_patterns)
    statistics_routes = [route for route in seen if "statistics" in route]
    assert statistics_routes == [
        "statistics/",
        "statistics/export/",
    ]
    assert not hasattr(export_module, "build_export_workbook")
    assert not hasattr(export_module, "export_filename")
    assert not hasattr(export_module, "XLSX_CONTENT_TYPE")
    assert not hasattr(views_module, "build_export_workbook")
    template = open(
        "apps/statistics_reports/templates/statistics_reports/daily_report.html"
    ).read()
    assert "Exportar ZIP por setor" in template
    assert "Exportar XLSX" not in template
    assert "?format" not in template
