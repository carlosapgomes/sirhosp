"""ECD-S2: management command handoff gate for census publication.

Only the acquisition subprocess is faked. The real command selects and parses
the delivered artifacts, validates the version-1 summary, applies the existing
40-sector threshold and persists snapshots in PostgreSQL.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.census.models import CensusSnapshot
from apps.ingestion.models import IngestionRun
from tests.census_artifacts import SUMMARY_FILENAME, build_summary, write_summary

CSV_HEADER = (
    "setor_codigo,setor,qrt_leito,prontuario,nome,esp,"
    "dt_int,tempo,idade,convenio,dt_mvt,alta,origem\n"
)
COLUMNS = (
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
)


def _csv_line(**overrides: str) -> str:
    values = {
        "setor_codigo": "600",
        "setor": "SETOR 001",
        "qrt_leito": "LEITO001A",
        "prontuario": "SYN-0001",
        "nome": "PACIENTE SINTETICO 1",
        "esp": "CLI",
        "dt_int": "01/02/2026",
        "tempo": "3",
        "idade": "40",
        "convenio": "",
        "dt_mvt": "02/02/2026",
        "alta": "",
        "origem": "",
    }
    values.update(overrides)
    return ",".join(values[column] for column in COLUMNS)


def _synthetic_csv(
    *,
    sectors: int,
    empty_sectors: int = 0,
    sentinel: str | None = None,
) -> str:
    lines: list[str] = []
    for index in range(1, sectors + 1):
        record = sentinel or f"SYN-{index:04d}"
        name = sentinel or f"PACIENTE SINTETICO {index}"
        lines.append(
            _csv_line(
                setor_codigo=str(600 + index),
                setor=f"SETOR {index:03d}",
                qrt_leito=f"LEITO{index:03d}A",
                prontuario=record,
                nome=name,
            )
        )
        lines.append(
            _csv_line(
                setor_codigo=str(600 + index),
                setor=f"SETOR {index:03d}",
                qrt_leito=f"LEITO{index:03d}B",
                prontuario="",
                nome="DESOCUPADO",
                esp="",
                idade="",
                dt_int="",
                tempo="",
                dt_mvt="",
            )
        )
    # Empty sectors contribute no CSV row at all; they only appear in the
    # aggregate summary.
    return CSV_HEADER + "\n".join(lines) + "\n"


def _summary_for(
    *,
    csv_text: str,
    sectors: int,
    empty_sectors: int = 0,
    discovered: int | None = None,
    **overrides,
) -> dict:
    rows_emitted = len(csv_text.strip().splitlines()) - 1
    summary = build_summary(
        discovered=(
            sectors + empty_sectors if discovered is None else discovered
        ),
        selected=sectors + empty_sectors,
        processed=sectors + empty_sectors,
        empty=empty_sectors,
        rows_emitted=rows_emitted,
    )
    summary.update(overrides)
    return summary


def _run_command(
    tmp_path: Path,
    *,
    summary: dict | None,
    summary_text: str | None = None,
    csv_text: str | None = None,
    csv_name: str = "censo-20261030-120000.csv",
    extra_csv: bool = False,
    summary_name: str = SUMMARY_FILENAME,
    expect_exit: bool = True,
) -> IngestionRun:
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_tmp_ctx = MagicMock()
    fake_tmp_ctx.__enter__.return_value = str(tmp_path)

    if csv_text is not None:
        (tmp_path / csv_name).write_text(csv_text, encoding="utf-8")
        if extra_csv:
            (tmp_path / "censo-duplicate.csv").write_text(
                csv_text, encoding="utf-8"
            )
    if summary_text is not None:
        (tmp_path / summary_name).write_text(summary_text, encoding="utf-8")
    elif summary is not None:
        write_summary(tmp_path, summary, name=summary_name)

    with (
        patch(
            "apps.census.management.commands.extract_census.run_subprocess",
            return_value=fake_result,
        ),
        patch(
            "tempfile.TemporaryDirectory",
            return_value=fake_tmp_ctx,
        ),
    ):
        if expect_exit:
            with pytest.raises(SystemExit):
                call_command("extract_census")
        else:
            call_command("extract_census")

    return IngestionRun.objects.filter(intent="census_extraction").latest("pk")


@pytest.mark.django_db
class TestCensusSummaryGate:
    def test_missing_summary_is_rejected_even_with_exit_zero(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        run = _run_command(tmp_path, summary=None, csv_text=csv_text)

        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"
        assert CensusSnapshot.objects.count() == 0

    def test_partial_summary_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["sectors_processed"] = 40
        summary["scope_complete"] = False
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_malformed_summary_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        run = _run_command(
            tmp_path,
            summary=None,
            summary_text="{not json",
            csv_text=csv_text,
        )

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_unknown_summary_field_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["raw_stdout"] = "SENTINEL-RAW-STDOUT"
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_invalid_summary_type_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["rows_emitted"] = "80"
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_incoherent_row_equation_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["rows_omitted"] = 1
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_csv_row_count_mismatch_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["rows_emitted"] = 79
        summary["rows_read"] = 79
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_failed_sector_summary_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["sectors_failed"] = 1
        summary["scope_complete"] = False
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_limited_diagnostic_scope_is_rejected_at_forty_sectors(self, tmp_path):
        csv_text = _synthetic_csv(sectors=40)
        summary = _summary_for(
            csv_text=csv_text,
            sectors=40,
            discovered=41,
        )
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_ambiguous_canonical_csv_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        run = _run_command(
            tmp_path,
            summary=summary,
            csv_text=csv_text,
            extra_csv=True,
        )

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_noncanonical_csv_is_not_used_as_fallback(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        run = _run_command(
            tmp_path,
            summary=summary,
            csv_text=csv_text,
            csv_name="other.csv",
        )

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_sector_count_equation_mismatch_is_rejected(self, tmp_path):
        csv_text = _synthetic_csv(sectors=40)
        summary = _summary_for(
            csv_text=csv_text,
            sectors=40,
            empty_sectors=1,
        )
        summary["sectors_empty"] = 0
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0

    def test_valid_empty_sector_keeps_forty_nonempty_sectors_acceptable(
        self, tmp_path
    ):
        csv_text = _synthetic_csv(sectors=40)
        summary = _summary_for(
            csv_text=csv_text,
            sectors=40,
            empty_sectors=1,
        )
        run = _run_command(
            tmp_path,
            summary=summary,
            csv_text=csv_text,
            expect_exit=False,
        )

        assert run.status == "succeeded"
        assert CensusSnapshot.objects.count() == len(
            csv_text.strip().splitlines()
        ) - 1
        persistence = run.stage_metrics.get(
            stage_name="census_persistence"
        )
        assert persistence.details_json["sectors_empty"] == 1
        assert persistence.details_json["scope_complete"] is True

    def test_threshold_still_rejects_thirty_nine_nonempty_sectors(self, tmp_path):
        csv_text = _synthetic_csv(sectors=39, empty_sectors=2)
        summary = _summary_for(
            csv_text=csv_text,
            sectors=39,
            empty_sectors=2,
        )
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        assert CensusSnapshot.objects.count() == 0
        details = run.stage_metrics.get(
            stage_name="census_persistence"
        ).details_json
        assert details["sector_count"] == 39
        assert details["minimum_required_sectors"] == 40

    def test_command_requests_csv_only_transport(self, tmp_path):
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_tmp_ctx = MagicMock()
        fake_tmp_ctx.__enter__.return_value = str(tmp_path)
        (tmp_path / "censo-20261030-120000.csv").write_text(
            csv_text, encoding="utf-8"
        )
        write_summary(tmp_path, summary)

        with (
            patch(
                "apps.census.management.commands.extract_census.run_subprocess",
                return_value=fake_result,
            ) as run_subprocess,
            patch("tempfile.TemporaryDirectory", return_value=fake_tmp_ctx),
        ):
            call_command("extract_census")

        cmd = run_subprocess.call_args.args[0]
        assert "--csv-only" in cmd

    def test_rejection_output_and_metrics_never_include_patient_values(
        self, tmp_path, capsys
    ):
        sentinel = "SENTINEL-PATIENT-VALUE-77"
        csv_text = _synthetic_csv(sectors=41, sentinel=sentinel)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["rows_emitted"] = 1
        summary["rows_read"] = 1
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert run.status == "failed"
        assert sentinel not in combined
        assert sentinel not in run.error_message
        assert sentinel not in str(
            list(run.stage_metrics.values_list("details_json", flat=True))
        )

    def test_unknown_summary_content_is_not_copied_to_metrics(self, tmp_path):
        sentinel = "SENTINEL-SUMMARY-CONTENT"
        csv_text = _synthetic_csv(sectors=41)
        summary = _summary_for(csv_text=csv_text, sectors=41)
        summary["browser_error"] = sentinel
        run = _run_command(tmp_path, summary=summary, csv_text=csv_text)

        assert run.status == "failed"
        for details in run.stage_metrics.values_list("details_json", flat=True):
            assert sentinel not in json.dumps(details)
