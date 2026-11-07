"""PEND-S4/STRUCT-PEND-S4: pending-items XLSX workbook unit tests.

Contract: PP-08 / design D7. The workbook has the exact 23 columns, one
row per pending item in its current state, native date/datetime cells
for dates and instants, native numeric ids, literal text cells by TYPE
(``data_type`` in ``s``/``inlineStr``, never formula) and a usable
sheet (autofilter over every column, first row frozen). Pure checks, no
database. All fixtures are synthetic.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl
from django.template.loader import get_template
from django.urls import resolve, reverse
from openpyxl.utils import get_column_letter

from apps.pending_items.export import (
    EXPORT_HEADERS,
    EXPORT_MAX_COLUMN_WIDTH,
    XLSX_MIME,
    build_pending_items_workbook,
    created_by_label,
    detail_cells,
    excel_instant,
    updated_by_label,
)
from apps.pending_items.models import PendingItem

TZ = ZoneInfo("America/Bahia")
UTC = ZoneInfo("UTC")

EXPECTED_HEADERS = [
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
]

LAST_COLUMN_LETTER = get_column_letter(len(EXPECTED_HEADERS))

FORMULA_LOOKALIKES = ["=1+1", "+1+1", "-2+3", "@SOMA(A1:A2)"]


def _reopen(payload: bytes):
    return openpyxl.load_workbook(BytesIO(payload)).active


def _column(header: str) -> int:
    return EXPECTED_HEADERS.index(header) + 1


def _blank_row() -> list[object]:
    return [None] * len(EXPECTED_HEADERS)


def _cell(ws, row: int, header: str):
    return ws.cell(row=row, column=_column(header))


def _assert_literal(cell) -> None:
    assert cell.data_type in ("s", "inlineStr")


class TestExportHeaders:
    def test_headers_match_pp08_exact_order(self) -> None:
        assert list(EXPORT_HEADERS) == EXPECTED_HEADERS
        assert len(EXPORT_HEADERS) == 23

    def test_mime_constant(self) -> None:
        assert XLSX_MIME == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_empty_workbook_has_headers_only(self) -> None:
        ws = _reopen(build_pending_items_workbook([]))
        assert ws is not None
        assert [cell.value for cell in ws[1]] == EXPECTED_HEADERS
        assert ws.max_row == 1
        assert ws.max_column == 23


class TestLiteralTextCells:
    def test_every_text_value_is_literal_string_type(self) -> None:
        row = [f"valor-{index}" for index in range(len(EXPECTED_HEADERS))]
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        assert ws.max_row == 2
        for cell in ws[2]:
            _assert_literal(cell)
        assert [cell.value for cell in ws[2]] == row

    def test_formula_lookalikes_stay_literal_in_every_column(self) -> None:
        base = FORMULA_LOOKALIKES * 6
        row = base[: len(EXPECTED_HEADERS)]
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        for cell in ws[2]:
            _assert_literal(cell)
        assert [cell.value for cell in ws[2]] == row

    def test_empty_values_round_trip_as_blank_cells(self) -> None:
        row = ["" for _ in range(len(EXPECTED_HEADERS))]
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        assert ws.max_row == 2
        for cell in ws[2]:
            _assert_literal(cell)
            assert cell.value in ("", None)

    def test_one_row_per_record_without_concatenation(self) -> None:
        rows = [
            [f"primeira-{index}" for index in range(len(EXPECTED_HEADERS))],
            [f"segunda-{index}" for index in range(len(EXPECTED_HEADERS))],
        ]
        ws = _reopen(build_pending_items_workbook(rows))
        assert ws is not None
        assert ws.max_row == 3
        assert [cell.value for cell in ws[2]] == rows[0]
        assert [cell.value for cell in ws[3]] == rows[1]


class TestNativeCellTypes:
    def test_civil_date_is_a_native_date_cell(self) -> None:
        row = _blank_row()
        row[_column("Data agendada") - 1] = date(2026, 11, 10)
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        cell = _cell(ws, 2, "Data agendada")
        assert cell.is_date is True
        assert cell.data_type == "d"
        assert cell.number_format == "dd/mm/yyyy"
        assert isinstance(cell.value, datetime)
        assert cell.value == datetime(2026, 11, 10, 0, 0)

    def test_instant_is_a_native_naive_datetime_cell(self) -> None:
        row = _blank_row()
        row[_column("Assinatura do sumário em") - 1] = datetime(
            2026, 11, 12, 9, 30
        )
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        cell = _cell(ws, 2, "Assinatura do sumário em")
        assert cell.is_date is True
        assert cell.data_type == "d"
        assert cell.number_format == "dd/mm/yyyy hh:mm"
        assert cell.value == datetime(2026, 11, 12, 9, 30)
        assert cell.value.tzinfo is None

    def test_identifier_cells_stay_numeric(self) -> None:
        row = _blank_row()
        row[_column("ID da pendência") - 1] = 42
        row[_column("ID da internação") - 1] = 7
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        assert _cell(ws, 2, "ID da pendência").value == 42
        assert _cell(ws, 2, "ID da internação").value == 7
        for header in ("ID da pendência", "ID da internação"):
            assert _cell(ws, 2, header).data_type == "n"

    def test_leading_zero_registration_stays_text(self) -> None:
        row = _blank_row()
        row[_column("Registro") - 1] = "0001234"
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        cell = _cell(ws, 2, "Registro")
        assert cell.value == "0001234"
        _assert_literal(cell)


class TestSheetUsability:
    def test_autofilter_covers_every_column(self) -> None:
        ws = _reopen(build_pending_items_workbook([]))
        assert ws is not None
        assert ws.auto_filter.ref == f"A1:{LAST_COLUMN_LETTER}1"
        rows = [["x"] * len(EXPECTED_HEADERS) for _ in range(2)]
        filled = _reopen(build_pending_items_workbook(rows))
        assert filled is not None
        assert filled.auto_filter.ref == f"A1:{LAST_COLUMN_LETTER}3"

    def test_first_row_is_frozen(self) -> None:
        ws = _reopen(build_pending_items_workbook([]))
        assert ws is not None
        assert ws.freeze_panes == "A2"


class TestDetailCellTypes:
    """R2: Sim/Não/Não informado/empty by profile applicability (D7)."""

    def test_scheduling_rnm_keeps_unknown_and_not_applicable_apart(
        self,
    ) -> None:
        cells = detail_cells(
            "agendamento",
            True,
            {
                "is_scheduled": True,
                "scheduled_date": date(2026, 11, 10),
                "contrast": None,
                "sedation": False,
            },
        )
        assert cells == [
            "Sim",
            date(2026, 11, 10),
            "Não informado",
            "Não",
            None,
            None,
            None,
        ]

    def test_scheduling_without_complements_blanks_contrast_and_sedation(
        self,
    ) -> None:
        cells = detail_cells(
            "agendamento",
            False,
            {"is_scheduled": False, "scheduled_date": None},
        )
        assert cells[0] == "Não"
        assert cells[1] is None
        assert cells[2] is None
        assert cells[3] is None

    def test_treatment_period_dates_are_native_and_others_empty(self) -> None:
        cells = detail_cells(
            "tratamento-periodo",
            False,
            {
                "treatment_start_date": date(2026, 11, 1),
                "treatment_end_date": date(2026, 11, 10),
            },
        )
        assert cells == [
            None,
            None,
            None,
            None,
            date(2026, 11, 1),
            date(2026, 11, 10),
            None,
        ]

    def test_signature_instant_uses_institutional_wall_clock(self) -> None:
        cells = detail_cells(
            "assinatura-documento",
            False,
            {"signature_at": datetime(2026, 11, 12, 12, 30, tzinfo=UTC)},
        )
        signature = cells[6]
        assert isinstance(signature, datetime)
        assert signature == datetime(2026, 11, 12, 9, 30)
        assert signature.tzinfo is None
        assert cells[:6] == [None] * 6

    def test_simple_profile_has_no_detail_cells(self) -> None:
        cells = detail_cells(
            "registro-simples",
            False,
            {"is_scheduled": True, "contrast": True, "sedation": False},
        )
        assert cells == [None] * 7

    def test_unknown_profile_yields_empty_cells(self) -> None:
        assert detail_cells(None, None, {}) == [None] * 7


class TestExportInstant:
    def test_instant_is_converted_to_the_institutional_timezone(self) -> None:
        stored = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)
        assert excel_instant(stored) == datetime(2026, 6, 10, 12, 0)
        assert excel_instant(stored).tzinfo is None
        assert stored == datetime(2026, 6, 10, 15, 0, tzinfo=UTC)

    def test_local_instant_is_unchanged(self) -> None:
        stored = datetime(2026, 6, 10, 12, 0, tzinfo=TZ)
        assert excel_instant(stored) == datetime(2026, 6, 10, 12, 0)


class TestLongTextUsability:
    def test_long_observation_width_is_capped_and_wrapped(self) -> None:
        row = _blank_row()
        row[_column("Descrição/observação") - 1] = "observacao " * 40
        ws = _reopen(build_pending_items_workbook([row]))
        assert ws is not None
        letter = get_column_letter(_column("Descrição/observação"))
        assert ws.column_dimensions[letter].width <= EXPORT_MAX_COLUMN_WIDTH
        cell = _cell(ws, 2, "Descrição/observação")
        assert cell.alignment.wrap_text is True


class TestExportFormatting:
    def test_system_update_never_shows_human_name(self) -> None:
        item = PendingItem(
            is_system_updated=True, updated_by_name="humano.sintetico"
        )
        assert updated_by_label(item) == "Sistema"

    def test_human_update_shows_recorded_name(self) -> None:
        item = PendingItem(
            is_system_updated=False, updated_by_name="humano.sintetico"
        )
        assert updated_by_label(item) == "humano.sintetico"

    def test_missing_authors_fall_back_to_panel_placeholder(self) -> None:
        item = PendingItem(
            is_system_updated=False,
            created_by_name="",
            updated_by_name="",
        )
        assert created_by_label(item) == "—"
        assert updated_by_label(item) == "—"


class TestExportWiring:
    def test_route_name_resolves_to_xlsx_path(self) -> None:
        assert reverse("pending_items:aggregate_export") == (
            "/pendencias/export.xlsx"
        )

    def test_path_dispatches_to_authenticated_export_view(self) -> None:
        match = resolve("/pendencias/export.xlsx")
        assert match.func.__name__ == "aggregate_export"

    def test_aggregate_panel_links_export_with_filters(self) -> None:
        template = get_template("pending_items/aggregate.html")
        origin = getattr(template, "origin", None)
        assert origin is not None
        source = Path(origin.name).read_text(encoding="utf-8")
        assert "pending_items:aggregate_export" in source
        assert 'data-testid="aggregate-export"' in source
        assert "request.GET.urlencode" in source
