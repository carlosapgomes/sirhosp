"""ECD-S3 unit seams: DOM field mapping, identity, tooltips and eligibility.

These tests are deterministic and browser-free. The real browser affordances
are exercised by ``automation/lab/playwright_experiments/verify_census_dom.py``;
PostgreSQL composition lives in the integration suite.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

_SYS_PATH_BEFORE_IMPORT = list(sys.path)
_SOURCE_SYSTEM_MODULE_BEFORE = sys.modules.get("source_system")

from automation.source_system.current_inpatients import extract_census as ec  # noqa: E402

sys.path[:] = _SYS_PATH_BEFORE_IMPORT
if _SOURCE_SYSTEM_MODULE_BEFORE is None:
    sys.modules.pop("source_system", None)


HEADERS = [
    "Ações",
    "Qrt/Leito",
    "Prontuário",
    "Nome/Situação",
    "Dt. Nasc.",
    "Idade",
    "Dt Int",
    "Esp",
    "Médico",
    "Dt Mvt",
    "Alta",
    "Alta",
    "Origem",
    "Origem",
    "Tempo",
    "Convênio",
    "Transferência",
    "Condições",
    "Destinos",
]


class TestHeaderMapping:
    def test_first_repeated_occurrence_is_the_export_variant(self) -> None:
        mapping = ec.map_census_headers(HEADERS)

        assert mapping["alta"] == HEADERS.index("Alta")
        assert mapping["origem"] == HEADERS.index("Origem")
        assert mapping["dt_int"] == HEADERS.index("Dt Int")
        assert mapping["dt_mvt"] == HEADERS.index("Dt Mvt")

    def test_accented_aliases_and_unrelated_reordering(self) -> None:
        reordered = [
            "Convênio",
            "Tempo",
            "Origem",
            "Origem",
            "Alta",
            "Alta",
            "Dt Mvt",
            "Médico",
            "Esp",
            "Dt Int",
            "Idade",
            "Dt. Nasc.",
            "Nome/Situação",
            "Prontuário",
            "Qrt/Leito",
            "Ações",
        ]
        mapping = ec.map_census_headers(reordered)

        assert mapping["convenio"] == 0
        assert mapping["qrt_leito"] == 14
        assert mapping["prontuario"] == 13
        assert set(mapping) == set(ec.PRODUCTION_FIELDS)

    def test_missing_required_field_fails_explicitly(self) -> None:
        without_origem = [head for head in HEADERS if head != "Origem"]
        with pytest.raises(ec.CensusExtractionError) as error:
            ec.map_census_headers(without_origem)
        assert error.value.reason == ec.REQUIRED_COLUMN_MISSING_REASON

    def test_production_field_contract_is_exactly_eleven(self) -> None:
        assert ec.PRODUCTION_FIELDS == (
            "qrt_leito",
            "prontuario",
            "nome",
            "esp",
            "dt_int",
            "tempo",
            "idade",
            "convenio",
            "dt_mvt",
            "alta",
            "origem",
        )


class TestNormalizationAndEligibility:
    def test_prontuario_drops_presentation_separators(self) -> None:
        assert ec._normalize_prontuario("19.017.680") == "19017680"
        assert ec._normalize_prontuario(" 123/456 ") == "123456"
        assert ec._normalize_prontuario(None) == ""

    def test_age_preserves_month_and_day_units(self) -> None:
        assert ec._normalize_idade("2m12d") == "2m12d"
        assert ec._normalize_idade("40") == "40"
        assert ec._normalize_idade("40.0") == "40"
        assert ec._normalize_idade("") == ""

    def test_tempo_and_zero_discharge_match_parser(self) -> None:
        assert ec._normalize_tempo("3.0") == 3
        assert ec._normalize_tempo("") is None
        assert ec._normalize_tempo("not-a-number") is None
        assert ec._normalize_alta("0") == ""
        assert ec._normalize_alta("0.0") == ""
        assert ec._normalize_alta("1.0") == "1"
        assert ec._normalize_alta("ALTA") == "ALTA"

    def test_only_both_identities_empty_are_ineligible(self) -> None:
        assert ec._is_eligible_dom_row("", "RESERVA") is True
        assert ec._is_eligible_dom_row("", "DESOCUPADO") is True
        assert ec._is_eligible_dom_row("123", "") is True
        assert ec._is_eligible_dom_row("", "") is False

    def test_patient_payload_has_exactly_eleven_fields_plus_metadata(self) -> None:
        patient = ec._build_dom_patient(
            {
                "qrt_leito": " LEITO 1 ",
                "prontuario": "19.017.680",
                "nome": "PACIENTE  SINTÉTICO",
                "esp": "CLI",
                "dt_int": "01/02/2026 08:15",
                "tempo": "3.0",
                "idade": "2m12d",
                "convenio": "SUS",
                "dt_mvt": "02/02/2026 10:30",
                "alta": "0",
                "origem": "ORIGEM",
            },
            setor_codigo="4 8",
            setor_nome="4C - CLINICA MÉDICA PEDIÁTRICA - HGRS",
        )

        assert set(patient) == set(ec.PRODUCTION_FIELDS) | {
            "setor_codigo",
            "setor",
        }
        assert patient["prontuario"] == "19017680"
        assert patient["idade"] == "2m12d"
        assert patient["tempo"] == 3
        assert patient["alta"] == ""
        assert patient["dt_int"] == "01/02/2026 08:15"


class TestSourceTooltip:
    def test_single_associated_timestamp_is_used(self) -> None:
        value = ec.enrich_source_timestamp(
            "01/02", ["01/02/2026 08:15"]
        )
        assert value == "01/02/2026 08:15"

    def test_empty_display_preserves_empty(self) -> None:
        assert ec.enrich_source_timestamp("", []) == ""
        assert ec.enrich_source_timestamp("   ", ["01/02/2026 08:15"]) == ""

    def test_missing_timestamp_signals_readiness(self) -> None:
        with pytest.raises(ec.CensusExtractionError) as error:
            ec.enrich_source_timestamp("01/02", [])
        assert error.value.reason == ec.TOOLTIP_MISSING_REASON

    def test_multiple_distinct_timestamps_are_ambiguous(self) -> None:
        with pytest.raises(ec.CensusExtractionError) as error:
            ec.enrich_source_timestamp(
                "01/02",
                ["01/02/2026 08:15", "01/02/2026 09:15"],
            )
        assert error.value.reason == ec.TOOLTIP_AMBIGUOUS_REASON

    def test_invalid_calendar_value_is_rejected(self) -> None:
        with pytest.raises(ec.CensusExtractionError) as error:
            ec.enrich_source_timestamp("31/02", ["31/02/2026 08:15"])
        assert error.value.reason == ec.TOOLTIP_INVALID_REASON

    def test_date_disagreement_is_rejected(self) -> None:
        with pytest.raises(ec.CensusExtractionError) as error:
            ec.enrich_source_timestamp("01/02", ["02/02/2026 08:15"])
        assert error.value.reason == ec.TOOLTIP_DATE_MISMATCH_REASON

    def test_full_year_display_requires_same_calendar_date(self) -> None:
        assert (
            ec.enrich_source_timestamp(
                "01/02/2026", ["01/02/2026 08:15"]
            )
            == "01/02/2026 08:15"
        )
        with pytest.raises(ec.CensusExtractionError):
            ec.enrich_source_timestamp(
                "01/02/2025", ["01/02/2026 08:15"]
            )


class TestSectorIdentity:
    def test_identity_is_code_plus_native_description(self) -> None:
        identity = ec.parse_setor_identity(
            "4 8 - 4C - CLINICA MÉDICA PEDIÁTRICA - HGRS"
        )
        assert identity is not None
        assert identity["code"] == "4 8"
        assert identity["description"] == (
            "4C - CLINICA MÉDICA PEDIÁTRICA - HGRS"
        )

    def test_confirm_accepts_accented_native_description(self) -> None:
        requested = "4 8 - 4C - CLINICA MÉDICA PEDIÁTRICA - HGRS"
        ec._confirm_selected_setor(
            requested,
            {
                "codigo": "4 8",
                "nome": "4C - CLINICA MÉDICA PEDIÁTRICA - HGRS",
            },
        )

    def test_confirm_rejects_shared_code_with_other_description(self) -> None:
        with pytest.raises(ec.CensusExtractionError) as error:
            ec._confirm_selected_setor(
                "5 1 - ALA NORTE",
                {"codigo": "5 1", "nome": "ALA SUL"},
            )
        assert error.value.reason == ec.SECTOR_SELECTION_MISMATCH_REASON

    def test_confirm_rejects_wrong_code(self) -> None:
        with pytest.raises(ec.CensusExtractionError):
            ec._confirm_selected_setor(
                "5 1 - ALA NORTE",
                {"codigo": "5 2", "nome": "ALA NORTE"},
            )

    def test_description_only_request_must_match_selected_description(self) -> None:
        ec._confirm_selected_setor(
            "CLINICA MÉDICA PEDIÁTRICA",
            {
                "codigo": "4 8",
                "nome": "4C - CLINICA MÉDICA PEDIÁTRICA - HGRS",
            },
        )
        with pytest.raises(ec.CensusExtractionError):
            ec._confirm_selected_setor(
                "OUTRA UNIDADE",
                {"codigo": "4 8", "nome": "ALA NORTE"},
            )

    def test_identity_unavailable_is_explicit(self) -> None:
        with pytest.raises(ec.CensusExtractionError) as error:
            ec._confirm_selected_setor(
                "5 1 - ALA NORTE", {"codigo": "5 1", "nome": ""}
            )
        assert error.value.reason == ec.SECTOR_IDENTITY_UNAVAILABLE_REASON


XLSX_HEADER = [
    "Qrt/Leito",
    "Prontuário",
    "Nome/Situação",
    "Idade",
    "Dt Int",
    "Esp",
    "Médico",
    "Dt Mvt",
    "Alta",
    "Origem",
    "Tempo",
    "Convênio",
    "Transferência",
]


def _write_golden_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(XLSX_HEADER)
    sheet.append(
        [
            "LEITO-1",
            "SYN-1",
            "PACIENTE SINTÉTICO 1",
            40,
            "01/02/2026",
            "CLI",
            "",
            "02/02/2026",
            "",
            "",
            3,
            "",
            "",
        ]
    )
    sheet.append(
        [
            "LEITO-2",
            "",
            "DESOCUPADO",
            "",
            "",
            "",
            "",
            "03/02/2026",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    workbook.save(path)
    workbook.close()


CSV_COLUMNS = [
    "setor_codigo",
    "setor",
    "qrt_leito",
    "prontuario",
    "nome",
    "esp",
    "dt_int",
    "tempo",
    "idade",
    "convenio",
    "dt_mvt",
    "alta",
    "origem",
]


def _write_transport(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})


class TestXlsxReferenceCharacterization:
    """The reference workbook cannot supply either source hour."""

    def test_reference_transport_has_dates_without_hours(self, tmp_path: Path) -> None:
        from apps.census.services import parse_census_csv

        workbook_path = tmp_path / "golden.xlsx"
        _write_golden_workbook(workbook_path)
        parsed = ec.parse_setor_xlsx(
            workbook_path, "600", "SETOR SINTÉTICO"
        )

        assert len(parsed) == 2
        assert all(
            ":" not in str(row.get(field) or "")
            for row in parsed
            for field in ("dt_int", "dt_mvt")
        )

        transport = tmp_path / "transport.csv"
        _write_transport(transport, parsed)
        consumers = parse_census_csv(transport)

        assert all(row["source_admission_at"] is None for row in consumers)
        assert all(row["source_movement_at"] is None for row in consumers)
        assert consumers[0]["data_internacao"] == "01/02/2026"
        assert consumers[0]["data_movimentacao"] == "02/02/2026"

    def test_dom_transport_carries_both_timestamps_and_old_dates(
        self, tmp_path: Path
    ) -> None:
        from apps.census.services import parse_census_csv

        transport = tmp_path / "transport.csv"
        _write_transport(
            transport,
            [
                {
                    "setor_codigo": "4 8",
                    "setor": "ALA SINTÉTICA",
                    "qrt_leito": "LEITO-1",
                    "prontuario": "SYN-1",
                    "nome": "PACIENTE SINTÉTICO 1",
                    "esp": "CLI",
                    "dt_int": "01/02/2026 08:15",
                    "tempo": 3,
                    "idade": "40",
                    "convenio": "SUS",
                    "dt_mvt": "02/02/2026 10:30",
                    "alta": "",
                    "origem": "",
                }
            ],
        )
        consumers = parse_census_csv(transport)

        assert consumers[0]["data_internacao"] == "01/02/2026"
        assert consumers[0]["data_movimentacao"] == "02/02/2026"
        assert consumers[0]["source_admission_at"].isoformat() == (
            "2026-02-01T08:15:00-03:00"
        )
        assert consumers[0]["source_movement_at"].isoformat() == (
            "2026-02-02T10:30:00-03:00"
        )
