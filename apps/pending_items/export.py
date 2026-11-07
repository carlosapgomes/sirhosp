"""XLSX workbook for the aggregate cut (STRUCT-PEND-S4, D7/PP-08).

Pure serialization: the view selects rows through the shared S3 queries
and this module formats them into an in-memory workbook. The workbook
has the exact 23 PP-08 columns, one row per pending item in its current
state and no history. Text is always a literal string cell
(``data_type == 's'``), so formula-looking content (``=``, ``+``, ``-``,
``@``) can never execute; dates and instants are native date cells (the
instants converted to the institutional timezone and stored without
timezone, the civil dates untouched); ids stay numeric and the patient
registration stays text so its leading zeros survive.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Mapping, Sequence

import openpyxl
from django.utils import timezone
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from apps.pending_items import details
from apps.pending_items.services import SYSTEM_AUTHOR_NAME

if TYPE_CHECKING:
    from apps.pending_items.models import PendingItem

EXPORT_HEADERS: tuple[str, ...] = (
    "ID da pendência",
    "ID da internação",
    "Registro",
    "Nome",
    "Unidade atual",
    "Leito",
    "Primeira unidade de internação",
    "Especialidade",
    "Categoria",
    "Tipo",
    "Descrição/observação",
    "Agendada?",
    "Data agendada",
    "Contraste",
    "Sedação",
    "Início do tratamento",
    "Previsão de término",
    "Assinatura do sumário em",
    "Status",
    "Criado em",
    "Criado por",
    "Atualizado em",
    "Atualizado por",
)
"""Exact PP-08 column order; also fixes the expected row width."""

DETAIL_CELL_FIELDS: tuple[str, ...] = (
    "is_scheduled",
    "scheduled_date",
    "contrast",
    "sedation",
    "treatment_start_date",
    "treatment_end_date",
    "signature_at",
)
"""Applicable detail fields in their PP-08 column order."""

EXPORT_SHEET_TITLE = "Pendências"

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

EXPORT_FILENAME_PREFIX = "pendencias"

EXPORT_DATE_FORMAT = "dd/mm/yyyy"
"""Cell format of the civil dates (no timezone conversion applies)."""

EXPORT_INSTANT_FORMAT = "dd/mm/yyyy hh:mm"
"""Cell format of the instants, in the institutional wall clock."""

EXPORT_MAX_COLUMN_WIDTH = 60
"""Width cap: a long observation wraps instead of widening the column."""

UNKNOWN_AUTHOR_LABEL = "—"
"""Fallback mirroring the aggregate panel for missing author names."""


def excel_instant(value: datetime) -> datetime:
    """Convert one instant to the institutional wall clock, tz-naive.

    Excel stores date-times without timezone, so the stored instant is
    rendered in ``TIME_ZONE`` first and only then stripped; the stored
    value itself is never re-written.
    """
    return timezone.localtime(value).replace(tzinfo=None)


def created_by_label(item: PendingItem) -> str:
    """Human creation author, never blank in the workbook."""
    return item.created_by_name or UNKNOWN_AUTHOR_LABEL


def updated_by_label(item: PendingItem) -> str:
    """Last-update author; automatic updates read ``Sistema`` always."""
    if item.is_system_updated:
        return SYSTEM_AUTHOR_NAME
    return item.updated_by_name or UNKNOWN_AUTHOR_LABEL


def detail_cells(
    profile: str | None,
    has_rnm_complements: bool | None,
    values: Mapping[str, object],
) -> list[object]:
    """The seven detail cells, typed by applicability (D7/PP-08).

    Applicable booleans read ``Sim``/``Não`` and an applicable absence
    reads ``Não informado``; a field that does not apply is an empty
    cell, never an invented ``Não``. Civil dates stay native date cells,
    a signature instant becomes the institutional wall clock and an
    unknown date stays empty.
    """
    if profile is None:
        return [None] * len(DETAIL_CELL_FIELDS)
    applicable = set(
        details.applicable_detail_fields(profile, bool(has_rnm_complements))
    )
    cells: list[object] = []
    for name in DETAIL_CELL_FIELDS:
        if name not in applicable:
            cells.append(None)
            continue
        raw = values.get(name)
        if name in details.BOOLEAN_DETAIL_FIELDS:
            cells.append(_detail_boolean(raw))
        elif name == "signature_at":
            cells.append(
                excel_instant(raw) if isinstance(raw, datetime) else None
            )
        else:
            cells.append(
                raw
                if isinstance(raw, date) and not isinstance(raw, datetime)
                else None
            )
    return cells


def _detail_boolean(value: object) -> str:
    """Applicable tri-state answer; ``None`` never reads as ``Não``."""
    if value is True:
        return details.YES
    if value is False:
        return details.NO
    return details.UNKNOWN


def _write_cell(cell, value: object) -> None:
    """Write one typed value, keeping every text cell literal.

    Text never becomes a formula, dates stay native date cells, ids stay
    numeric and an absent value stays an empty cell.
    """
    if value is None:
        cell.value = None
        return
    if isinstance(value, bool):
        raise TypeError(
            "Synced booleans are not written raw; use detail_cells labels."
        )
    if isinstance(value, str):
        cell.value = value
        cell.data_type = "s"
        return
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise ValueError(
                "Excel instants must be tz-naive; use excel_instant()."
            )
        cell.value = value
        cell.number_format = EXPORT_INSTANT_FORMAT
        return
    if isinstance(value, date):
        cell.value = value
        cell.number_format = EXPORT_DATE_FORMAT
        return
    if isinstance(value, int):
        cell.value = value
        return
    raise TypeError(f"Unsupported XLSX cell type: {type(value).__name__}")


def _column_width(sheet, header: str, col_idx: int) -> int:
    """Header-and-content width, capped so one long note stays usable."""
    width = len(header)
    for row in sheet.iter_rows(
        min_row=2, min_col=col_idx, max_col=col_idx
    ):
        for cell in row:
            if cell.value is None:
                continue
            if isinstance(cell.value, datetime):
                text = EXPORT_INSTANT_FORMAT
            elif isinstance(cell.value, date):
                text = EXPORT_DATE_FORMAT
            else:
                text = str(cell.value)
            width = max(width, len(text))
    return min(width + 3, EXPORT_MAX_COLUMN_WIDTH)


def build_pending_items_workbook(rows: Sequence[Sequence[object]]) -> bytes:
    """Serialize header plus one row per item to XLSX bytes.

    The sheet is immediately usable: autofilter over the full range, the
    header row frozen, long observations wrapped. The workbook lives
    only in memory (``BytesIO``) with no temporary file on disk.
    """
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = EXPORT_SHEET_TITLE
    header_font = Font(bold=True)
    header_alignment = Alignment(wrap_text=True, vertical="bottom")
    body_alignment = Alignment(wrap_text=True, vertical="top")
    for col_idx, header in enumerate(EXPORT_HEADERS, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.data_type = "s"
        cell.alignment = header_alignment
    for row_idx, row in enumerate(rows, start=2):
        if len(row) != len(EXPORT_HEADERS):
            raise ValueError(
                f"Row {row_idx} has {len(row)} cells; "
                f"PP-08 requires {len(EXPORT_HEADERS)}."
            )
        for col_idx, value in enumerate(row, start=1):
            cell = sheet.cell(row=row_idx, column=col_idx)
            _write_cell(cell, value)
            cell.alignment = body_alignment
    for col_idx, header in enumerate(EXPORT_HEADERS, start=1):
        sheet.column_dimensions[get_column_letter(col_idx)].width = (
            _column_width(sheet, header, col_idx)
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = (
        f"A1:{get_column_letter(len(EXPORT_HEADERS))}{sheet.max_row}"
    )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_filename(stamp: datetime) -> str:
    """Censo-style filename stamp (``pendencias-YYYYMMDD-HHMM.xlsx``)."""
    file_ts = timezone.localtime(stamp).strftime("%Y%m%d-%H%M")
    return f"{EXPORT_FILENAME_PREFIX}-{file_ts}.xlsx"
