"""In-memory ZIP export of one daily statistics revision (DSRS-S7).

The exporter reads exactly the projection the authorized page renders, so the
archive can never disagree with the screen it mirrors:

- every rendered group becomes one single-sheet XLSX file, in the order the
  page renders it, and the conditional report-level group becomes the
  ``setor_nao_identificado`` file without pretending to be an official
  grouping;
- every file keeps the fixed sections in the required order -- admissions,
  transfer arrivals, deaths, transfer departures, hospital discharges, events
  with an unidentified endpoint and the closing patients -- including the empty
  ones, each showing its own count beside the title;
- rows reuse the wording, the fields and the natural ordering the projection
  already computed for the page, and a missing value stays missing instead of
  being filled in;
- a value that starts with a formula-significant character is stored as text,
  a sheet label that Excel would reject or collide with is normalized,
  truncated and de-duplicated deterministically while the full grouping name
  stays inside the sheet, and each file name carries the date, the revision
  and a unique ``snake_case`` ASCII slug of the grouping title;
- the archive is built in memory and handed over as bytes: no path is opened,
  no file is persisted and the download name carries only the date and the
  revision.

This module is read-only with respect to the database: it never writes, never
materializes and never audits. The served-export audit row is committed by the
view only after the archive exists.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from apps.statistics_reports.models import DailyStatisticsReport
from apps.statistics_reports.presentation import (
    PATIENT_LIST_TITLE,
    UNIDENTIFIED_LIST_TITLE,
    DailyReportProjection,
    EventRow,
    ReportGroup,
)

ZIP_CONTENT_TYPE = "application/zip"
"""Media type of the archive served by the export endpoint."""

ZIP_FILENAME_SUFFIX = ".zip"
"""Extension of the served archive."""

XLSX_FILENAME_SUFFIX = ".xlsx"
"""Extension of each sector file inside the archive."""

MAX_FILENAME_CHARS = 120
"""Maximum file name length, archive and sector files alike."""

SECTOR_SLUG_FALLBACK = "setor"
"""Slug used when a grouping title keeps no usable ASCII character."""

SHEET_TITLE_LIMIT = 31
"""Maximum worksheet name length Excel accepts."""

FALLBACK_SHEET_TITLE = "Setor"
"""Worksheet name used when a grouping label keeps no usable character."""

UNKNOWN_SHEET_MARKER = "sem agrupamento oficial"
"""Cell that identifies the conditional worksheet of a non-official group."""

FILENAME_PREFIX = "estatisticas-diarias"
"""Filename stem; the served name carries only the date and the revision."""

EVENT_COLUMNS: tuple[str, ...] = (
    "Leito",
    "Nome",
    "Prontuário",
    "Tipo",
    "Momento clínico",
    "Origem",
    "Destino",
    "Detecção",
)
"""Event columns, in the same meaning and order the page renders them."""

PATIENT_COLUMNS: tuple[str, ...] = (
    "Leito",
    "Nome",
    "Prontuário",
    "Especialidade",
)
"""Closing patient columns, in the same meaning and order the page renders."""

_INVALID_SHEET_TITLE_CHARS = frozenset("[]:*?/\\")
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_BOLD = Font(bold=True)


@dataclass(frozen=True)
class SheetSection:
    """One fixed section every worksheet carries, empty or not."""

    title: str
    attribute: str
    columns: tuple[str, ...]
    holds_patients: bool = False


SECTIONS: tuple[SheetSection, ...] = (
    SheetSection("Internações", "admissions", EVENT_COLUMNS),
    SheetSection("Transferências de entrada", "transfer_entries", EVENT_COLUMNS),
    SheetSection("Óbitos", "deaths", EVENT_COLUMNS),
    SheetSection("Transferências de saída", "transfer_exits", EVENT_COLUMNS),
    SheetSection("Altas hospitalares", "discharges", EVENT_COLUMNS),
    SheetSection(UNIDENTIFIED_LIST_TITLE, "unidentified", EVENT_COLUMNS),
    SheetSection(PATIENT_LIST_TITLE, "patients", PATIENT_COLUMNS, holds_patients=True),
)
"""Fixed sections of every worksheet, in the order the report requires."""


@dataclass(frozen=True)
class ExportWorkbook:
    """One single-group workbook built in memory and ready to be archived."""

    filename: str
    content: bytes
    sheet_count: int
    row_count: int


@dataclass(frozen=True)
class SectorExportZip:
    """One archive with a single-sheet XLSX per rendered group."""

    filename: str
    content: bytes
    file_count: int
    row_count: int


def build_sector_zip(
    projection: DailyReportProjection,
) -> SectorExportZip:
    """Build the archive of one rendered revision, entirely in memory.

    Every rendered group becomes one XLSX file in the order the page renders
    it; the conditional report-level group becomes the ``setor_nao_identificado``
    file that mirrors the page section. Each file holds a single worksheet
    written by ``_write_group_sheet``. No filesystem path is ever used and the
    returned bytes are the whole, finalized archive.
    """
    slugs = sector_file_slugs(
        projection.report, [group.title for group in projection.groups]
    )
    zip_buffer = BytesIO()
    row_count = 0
    with zipfile.ZipFile(
        zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for group, slug in zip(projection.groups, slugs, strict=True):
            single = build_single_group_workbook(group, projection.report, slug)
            archive.writestr(single.filename, single.content)
            row_count += single.row_count
    return SectorExportZip(
        filename=export_zip_filename(projection.report),
        content=zip_buffer.getvalue(),
        file_count=len(slugs),
        row_count=row_count,
    )


def build_single_group_workbook(
    group: ReportGroup, report: DailyStatisticsReport, slug: str
) -> ExportWorkbook:
    """Build the single-sheet workbook of one rendered group, in memory.

    ``slug`` is the archive-unique slug of the group (see ``sector_file_slugs``)
    so the standalone file name already matches the archived one. No
    filesystem path is ever used.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_titles([group.title])[0]
    row_count = _write_group_sheet(
        worksheet=sheet, group=group, report=report
    )
    buffer = BytesIO()
    workbook.save(buffer)
    return ExportWorkbook(
        filename=sector_xlsx_filename(report, slug),
        content=buffer.getvalue(),
        sheet_count=1,
        row_count=row_count,
    )


def export_zip_filename(report: DailyStatisticsReport) -> str:
    """Safe archive name built only from the date and the revision."""
    return f"{_export_stem(report)}{ZIP_FILENAME_SUFFIX}"


def sector_xlsx_filename(report: DailyStatisticsReport, slug: str) -> str:
    """Safe sector file name: date, revision and the archive-unique slug."""
    return f"{_export_stem(report)}-{slug}{XLSX_FILENAME_SUFFIX}"


def sector_file_slugs(
    report: DailyStatisticsReport, titles: Sequence[str]
) -> tuple[str, ...]:
    """Archive-unique slugs of the given grouping titles, in order.

    Each slug is truncated so its full file name fits the file name limit, and
    a collision -- including one the normalization itself created -- is resolved
    with a stable numeric suffix while the full name stays inside the sheet.
    """
    max_slug = _max_sector_slug_length(report)
    used: set[str] = set()
    resolved: list[str] = []
    for title in titles:
        base = sector_slug(title)[:max_slug] or SECTOR_SLUG_FALLBACK[:max_slug]
        candidate = base
        index = 2
        while candidate.casefold() in used:
            suffix = f"_{index}"
            candidate = f"{base[: max_slug - len(suffix)]}{suffix}"
            index += 1
        used.add(candidate.casefold())
        resolved.append(candidate)
    return tuple(resolved)


def sector_slug(title: str) -> str:
    """One grouping title reduced to a ``snake_case`` ASCII slug.

    The title is decomposed, stripped of diacritics, lowercased, and every run
    of characters outside ``[a-z0-9]`` becomes one underscore; a title that
    keeps no usable character falls back to ``setor``.
    """
    decomposed = unicodedata.normalize("NFKD", title)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or SECTOR_SLUG_FALLBACK


def _export_stem(report: DailyStatisticsReport) -> str:
    """Shared stem of the archive and its files: date and revision only."""
    return (
        f"{FILENAME_PREFIX}-{report.local_date.isoformat()}-r{report.revision}"
    )


def _max_sector_slug_length(report: DailyStatisticsReport) -> int:
    """Longest slug whose full file name still fits the file name limit."""
    return max(
        1,
        MAX_FILENAME_CHARS - len(_export_stem(report)) - 1 - len(XLSX_FILENAME_SUFFIX),
    )


def sheet_titles(titles: Sequence[str]) -> tuple[str, ...]:
    """Valid, unique and deterministic worksheet names for the given labels.

    A label is normalized to what Excel accepts, truncated to the worksheet
    limit, and a collision -- including one the normalization itself created --
    is resolved with a stable numeric suffix while the full name stays inside
    the sheet.
    """
    used: set[str] = set()
    resolved: list[str] = []
    for title in titles:
        base = _sanitize_sheet_title(title)
        candidate = base
        index = 2
        while candidate.casefold() in used:
            suffix = f" ({index})"
            candidate = f"{base[: SHEET_TITLE_LIMIT - len(suffix)]}{suffix}"
            index += 1
        used.add(candidate.casefold())
        resolved.append(candidate)
    return tuple(resolved)


def _sanitize_sheet_title(title: str) -> str:
    """One label reduced to what Excel accepts as a worksheet name."""
    cleaned = "".join(
        " " if character in _INVALID_SHEET_TITLE_CHARS else character
        for character in title
    )
    cleaned = cleaned.strip().strip("'").strip()
    if not cleaned:
        return FALLBACK_SHEET_TITLE
    return cleaned[:SHEET_TITLE_LIMIT]


def _write_group_sheet(
    *, worksheet: Worksheet, group: ReportGroup, report: DailyStatisticsReport
) -> int:
    """Write one grouping worksheet and return its aggregate data row count."""
    _write_cell(worksheet, 1, 1, group.title, bold=True)
    _write_cell(
        worksheet,
        1,
        2,
        group.stable_key or UNKNOWN_SHEET_MARKER,
        bold=True,
    )
    _write_cell(worksheet, 2, 1, f"Data do relatório: {report.local_date.isoformat()}")
    _write_cell(worksheet, 2, 2, f"Revisão: {report.revision}")

    cursor = 4
    data_rows = 0
    for section in SECTIONS:
        entries = getattr(group, section.attribute)
        _write_cell(worksheet, cursor, 1, section.title, bold=True)
        _write_cell(worksheet, cursor, 2, len(entries), bold=True)
        cursor += 1
        for column, header in enumerate(section.columns, start=1):
            _write_cell(worksheet, cursor, column, header, bold=True)
        cursor += 1
        for entry in entries:
            values = (
                _patient_values(entry)
                if section.holds_patients
                else _event_values(entry)
            )
            for column, value in enumerate(values, start=1):
                _write_cell(worksheet, cursor, column, value)
            cursor += 1
            data_rows += 1
        cursor += 1
    return data_rows


def _write_cell(
    worksheet: Worksheet, row: int, column: int, value: object, *, bold: bool = False
) -> None:
    """Write one cell, keeping text starting a formula inert.

    The workbook must never evaluate nominal content: a text value whose first
    character is formula-significant is stored with the explicit string type
    instead of the formula type openpyxl would otherwise assign.
    """
    cell = worksheet.cell(row=row, column=column, value=value)
    if bold:
        cell.font = _BOLD
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        cell.data_type = "s"


def _event_values(row: EventRow) -> tuple[str, ...]:
    """Nominal and temporal fields of one event row, as the page shows them."""
    event = row.event
    return (
        event.bed,
        event.name,
        event.record,
        row.label,
        row.clinical_display,
        row.origin_display,
        row.destination_display,
        row.detection_display,
    )


class PatientExportRow(Protocol):
    """Contract of the nominal fields the workbook reads from a patient row."""

    @property
    def bed(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def record(self) -> str: ...

    @property
    def specialty(self) -> str: ...


def _patient_values(patient: PatientExportRow) -> tuple[str, ...]:
    """Nominal fields of one closing patient row, as the page shows them."""
    return (patient.bed, patient.name, patient.record, patient.specialty)
