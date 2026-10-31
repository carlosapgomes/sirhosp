"""ECD-S1: command -> snapshot boundary for optional source timestamps.

The acquisition subprocess is faked by writing a synthetic CSV into the
output directory; the real parser and the real PostgreSQL-backed command
persist the snapshots. Only synthetic rows are used.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.models import IngestionRun
from tests.census_artifacts import build_summary, write_summary

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
LOCAL_TZ = ZoneInfo(settings.TIME_ZONE)

ADMISSION_DATE = "01/02/2026"
MOVEMENT_DATE = "02/02/2026"
ADMISSION_TIMESTAMP = f"{ADMISSION_DATE} 08:15"
MOVEMENT_TIMESTAMP = f"{MOVEMENT_DATE} 09:45"


def _csv_line(**overrides: str) -> str:
    values = {
        "setor_codigo": "600",
        "setor": "SETOR 001",
        "qrt_leito": "LEITO001A",
        "prontuario": "SYN-0001",
        "nome": "PACIENTE SINTETICO 1",
        "esp": "CLI",
        "dt_int": ADMISSION_DATE,
        "tempo": "3",
        "idade": "40",
        "convenio": "",
        "dt_mvt": MOVEMENT_DATE,
        "alta": "",
        "origem": "",
    }
    values.update(overrides)
    return ",".join(values[column] for column in COLUMNS)


def _synthetic_csv(*, sectors: int, enriched: bool) -> str:
    """Return a synthetic census CSV covering ``sectors`` distinct sectors."""
    admission = ADMISSION_TIMESTAMP if enriched else ADMISSION_DATE
    movement = MOVEMENT_TIMESTAMP if enriched else MOVEMENT_DATE
    lines: list[str] = []
    for index in range(1, sectors + 1):
        lines.append(
            _csv_line(
                setor_codigo=str(600 + index),
                setor=f"SETOR {index:03d}",
                qrt_leito=f"LEITO{index:03d}A",
                prontuario=f"SYN-{index:04d}",
                nome=f"PACIENTE SINTETICO {index}",
                dt_int=admission,
                dt_mvt=movement,
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
    return CSV_HEADER + "\n".join(lines) + "\n"


def _fake_acquisition(csv_text: str):
    """Fake only the acquisition subprocess; it drops the CSV in --output-dir."""

    def fake_run(cmd, timeout):
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        (output_dir / "censo-20261030-120000.csv").write_text(
            csv_text, encoding="utf-8"
        )
        write_summary(
            output_dir,
            build_summary(
                discovered=41,
                rows_emitted=len(csv_text.strip().splitlines()) - 1,
            ),
        )
        result = MagicMock()
        result.returncode = 0
        return result

    return fake_run


def _run_command(csv_text: str) -> None:
    with patch(
        "apps.census.management.commands.extract_census.run_subprocess",
        side_effect=_fake_acquisition(csv_text),
    ):
        call_command("extract_census")


@pytest.mark.django_db
class TestExtractCensusSourceTimestampPersistence:
    def test_command_persists_source_timestamps_with_run_provenance(self):
        _run_command(_synthetic_csv(sectors=41, enriched=True))

        run = IngestionRun.objects.get(intent="census_extraction")
        snapshot = CensusSnapshot.objects.get(leito="LEITO001A")

        assert snapshot.ingestion_run_id == run.pk
        assert run.status == "succeeded"
        assert getattr(snapshot, "source_admission_at", None) == datetime(
            2026, 2, 1, 8, 15, tzinfo=LOCAL_TZ
        )
        assert getattr(snapshot, "source_movement_at", None) == datetime(
            2026, 2, 2, 9, 45, tzinfo=LOCAL_TZ
        )
        assert snapshot.data_internacao == ADMISSION_DATE
        assert snapshot.data_movimentacao == MOVEMENT_DATE
        assert snapshot.bed_status == BedStatus.OCCUPIED
        assert CensusSnapshot.objects.filter(ingestion_run_id=run.pk).count() == 82

    def test_legacy_date_only_transport_still_succeeds_with_null_precision(self):
        _run_command(_synthetic_csv(sectors=41, enriched=False))

        run = IngestionRun.objects.get(intent="census_extraction")
        snapshot = CensusSnapshot.objects.get(leito="LEITO001A")

        assert run.status == "succeeded"
        assert getattr(snapshot, "source_admission_at", None) is None
        assert getattr(snapshot, "source_movement_at", None) is None
        assert snapshot.data_internacao == ADMISSION_DATE
        assert snapshot.data_movimentacao == MOVEMENT_DATE

    def test_invalid_timestamp_after_valid_rows_persists_no_partial_batch(
        self, capsys
    ):
        raw_invalid = "31/02/2026 10:00"
        csv_text = _synthetic_csv(sectors=40, enriched=True)
        csv_text += _csv_line(
            setor_codigo="699",
            setor="SETOR 999",
            qrt_leito="LEITO999A",
            prontuario="SYN-9999",
            nome="PACIENTE SINTETICO 9999",
            dt_int=raw_invalid,
        )

        with pytest.raises(SystemExit):
            _run_command(csv_text)

        captured = capsys.readouterr()
        combined_output = captured.out + captured.err
        run = IngestionRun.objects.get(intent="census_extraction")

        assert CensusSnapshot.objects.count() == 0
        assert run.status == "failed"
        assert "source admission timestamp" in combined_output.lower()
        assert raw_invalid not in combined_output
        assert raw_invalid not in run.error_message
        assert "SYN-9999" not in combined_output
        persistence_stage = run.stage_metrics.get(
            stage_name="census_persistence"
        )
        assert persistence_stage.status == "failed"
        assert raw_invalid not in str(persistence_stage.details_json)
