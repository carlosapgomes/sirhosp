"""Unit tests: sector slug normalization for the ZIP-per-sector export.

Covers the deterministic ``snake_case`` ASCII slug contract of the
statistics-export-zip-per-sector change:

- R2: accents are stripped, separators collapse to one underscore, file-system
  unsafe characters never survive, collisions resolve with a stable numeric
  suffix, overlong titles are truncated so the full file name fits the limit
  and a title without any usable character falls back to ``setor``.

Everything here is pure string normalization over synthetic titles; no real
sector data and no database access.
"""

from __future__ import annotations

from datetime import date

from apps.statistics_reports.export import (
    MAX_FILENAME_CHARS,
    export_zip_filename,
    sector_file_slugs,
    sector_slug,
    sector_xlsx_filename,
)
from apps.statistics_reports.models import DailyStatisticsReport

REPORT_DATE = date(2026, 2, 10)


def _report(revision: int = 3) -> DailyStatisticsReport:
    """An unsaved revision anchor: only the date and revision shape names."""
    return DailyStatisticsReport(local_date=REPORT_DATE, revision=revision)


class TestSectorSlug:
    def test_accented_title_loses_diacritics(self) -> None:
        assert sector_slug("OBSTETRÍCIA") == "obstetricia"

    def test_spaces_collapse_to_single_underscores(self) -> None:
        assert sector_slug("  CLÍNICA   MÉDICA  ") == "clinica_medica"

    def test_invalid_filename_characters_become_separators(self) -> None:
        assert sector_slug('SETOR: A/B\\C*D?E"F<G>H|I') == "setor_a_b_c_d_e_f_g_h_i"

    def test_digits_are_kept_including_leading_ones(self) -> None:
        assert sector_slug("3º ANDAR - UTI 2") == "3o_andar_uti_2"

    def test_empty_and_symbol_only_titles_use_the_fallback(self) -> None:
        assert sector_slug("") == "setor"
        assert sector_slug("   ") == "setor"
        assert sector_slug("///***") == "setor"

    def test_unknown_section_title_has_a_stable_slug(self) -> None:
        assert sector_slug("Setor não identificado") == "setor_nao_identificado"


class TestSectorFileSlugs:
    def test_collision_resolves_with_a_stable_numeric_suffix(self) -> None:
        assert sector_file_slugs(_report(), ["CLÍNICA", "CLINICA", "Clinica!"]) == (
            "clinica",
            "clinica_2",
            "clinica_3",
        )

    def test_uniqueness_is_case_insensitive(self) -> None:
        assert sector_file_slugs(_report(), ["UTI", "uti"]) == ("uti", "uti_2")

    def test_truncation_keeps_the_full_filename_within_the_limit(self) -> None:
        report = _report()
        long_title = "SETOR " + "MUITO LONGO " * 40
        (slug,) = sector_file_slugs(report, [long_title])
        filename = sector_xlsx_filename(report, slug)
        assert len(filename) <= MAX_FILENAME_CHARS
        assert filename.endswith(".xlsx")
        assert filename == filename.encode("ascii").decode("ascii")

    def test_truncated_collision_still_resolves_uniquely(self) -> None:
        report = _report()
        prefix = "SETOR " + "X" * 200
        slugs = sector_file_slugs(report, [prefix + " A", prefix + " B"])
        assert len(set(slugs)) == 2
        for slug in slugs:
            assert len(sector_xlsx_filename(report, slug)) <= MAX_FILENAME_CHARS


class TestExportFilenames:
    def test_archive_name_carries_only_date_and_revision(self) -> None:
        assert (
            export_zip_filename(_report())
            == "estatisticas-diarias-2026-02-10-r3.zip"
        )

    def test_sector_filename_carries_date_revision_and_slug(self) -> None:
        assert (
            sector_xlsx_filename(_report(), "obstetricia")
            == "estatisticas-diarias-2026-02-10-r3-obstetricia.xlsx"
        )
