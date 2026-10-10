"""Unit tests: autosize column widths of the statistics XLSX export.

Covers the R1/R2 contract of the statistics-export-autosize-columns change:

- R1: each column gets an explicit ``width`` only when its longest content
  (headers included, empty cells counting 0) exceeds the Excel default, as
  ``min(60, max(8.43, max_len + 2))`` with ``str(value)`` for non-text;
- R2: the same content always yields the same widths.

Everything here is pure ``openpyxl`` worksheets with synthetic strings; no
real sector data and no database access.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from apps.statistics_reports.export import autosize_columns

DEFAULT_WIDTH = 8.43


def _sheet() -> Worksheet:
    """A fresh single worksheet to size."""
    return Workbook().active


class TestAutosizeColumns:
    def test_short_content_keeps_the_default_width(self) -> None:
        sheet = _sheet()
        sheet["A1"] = "Leito"
        sheet["A2"] = "101-A"
        autosize_columns(sheet)
        assert "A" not in sheet.column_dimensions

    def test_long_content_gets_content_plus_padding(self) -> None:
        sheet = _sheet()
        value = "Nome sintético de paciente para teste de largura"
        sheet["B1"] = value
        autosize_columns(sheet)
        assert sheet.column_dimensions["B"].width == len(value) + 2

    def test_empty_and_none_cells_count_zero(self) -> None:
        sheet = _sheet()
        sheet["A1"] = None
        sheet["A2"] = ""
        autosize_columns(sheet)
        assert "A" not in sheet.column_dimensions

    def test_header_longer_than_data_drives_the_width(self) -> None:
        sheet = _sheet()
        header = "Momento clínico da transferência sintética"
        sheet["C1"] = header
        sheet["C2"] = "Altas"
        autosize_columns(sheet)
        assert sheet.column_dimensions["C"].width == len(header) + 2

    def test_data_longer_than_header_drives_the_width(self) -> None:
        sheet = _sheet()
        sheet["D1"] = "Nome"
        value = "Especialidade sintética longa para este teste"
        sheet["D2"] = value
        autosize_columns(sheet)
        assert sheet.column_dimensions["D"].width == len(value) + 2

    def test_width_is_capped_at_sixty(self) -> None:
        sheet = _sheet()
        sheet["A1"] = "X" * 100
        autosize_columns(sheet)
        assert sheet.column_dimensions["A"].width == 60

    def test_boundary_around_the_default_width(self) -> None:
        fitting = _sheet()
        fitting["A1"] = "123456"
        autosize_columns(fitting)
        assert "A" not in fitting.column_dimensions

        overflowing = _sheet()
        overflowing["A1"] = "1234567"
        autosize_columns(overflowing)
        assert overflowing.column_dimensions["A"].width == 9

    def test_non_text_uses_its_written_form(self) -> None:
        sheet = _sheet()
        sheet["A1"] = 10**30
        autosize_columns(sheet)
        assert sheet.column_dimensions["A"].width == len(str(10**30)) + 2

    def test_columns_are_sized_independently(self) -> None:
        sheet = _sheet()
        sheet["A1"] = "Leito"
        long_value = "Destino sintético com nome longo para o teste"
        sheet["B1"] = long_value
        autosize_columns(sheet)
        assert "A" not in sheet.column_dimensions
        assert sheet.column_dimensions["B"].width == len(long_value) + 2

    def test_same_content_yields_same_widths(self) -> None:
        first = _sheet()
        second = _sheet()
        for sheet in (first, second):
            sheet["A1"] = "Leito"
            sheet["B1"] = "Nome sintético longo para repetição"
            sheet["B2"] = "Curto"
            autosize_columns(sheet)
        assert dict(second.column_dimensions).keys() == dict(
            first.column_dimensions
        ).keys()
        for column in first.column_dimensions:
            assert (
                second.column_dimensions[column].width
                == first.column_dimensions[column].width
            )

    def test_empty_sheet_records_no_width(self) -> None:
        sheet = _sheet()
        autosize_columns(sheet)
        assert dict(sheet.column_dimensions) == {}
