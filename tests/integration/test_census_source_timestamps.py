"""ECD-S1 integration: CSV transport -> command -> PostgreSQL -> consumers.

Real parser, real management command and real isolated PostgreSQL are used;
only the acquisition subprocess is faked and all rows are synthetic.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
    OccupancyAgeBand,
    PatientMovement,
)
from apps.census.services import process_census_snapshot, upsert_patient_movements
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient
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
RESERVED_LABEL = "RESERVA INTERNA"
MAINTENANCE_LABEL = "LIMPEZA"


def _csv_line(**overrides: str) -> str:
    values = {
        "setor_codigo": "601",
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
                idade="1" if index == 1 else "40",
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
    lines.append(
        _csv_line(
            setor_codigo="601",
            setor="SETOR 001",
            qrt_leito="LEITO001C",
            prontuario="",
            nome=RESERVED_LABEL,
            esp="",
            idade="",
            dt_int="",
            tempo="",
            dt_mvt=MOVEMENT_TIMESTAMP if enriched else MOVEMENT_DATE,
        )
    )
    lines.append(
        _csv_line(
            setor_codigo="601",
            setor="SETOR 001",
            qrt_leito="LEITO001D",
            prontuario="",
            nome=MAINTENANCE_LABEL,
            esp="",
            idade="",
            dt_int="",
            tempo="",
            dt_mvt="",
        )
    )
    return CSV_HEADER + "\n".join(lines) + "\n"


def _fake_acquisition(csv_text: str):
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


def _run_command(csv_text: str) -> IngestionRun:
    with patch(
        "apps.census.management.commands.extract_census.run_subprocess",
        side_effect=_fake_acquisition(csv_text),
    ):
        call_command("extract_census")
    return IngestionRun.objects.filter(intent="census_extraction").latest("pk")


def _create_catalog(sectors: int) -> CapacityCatalogVersion:
    catalog = CapacityCatalogVersion.objects.create(
        effective_from=timezone.localdate(),
        source_reference="synthetic ECD-S1 occupancy catalog",
        source_sha256="a" * 64,
        schema_version="1.0",
    )
    group = CapacityGroupDefinition.objects.create(
        catalog=catalog,
        stable_key="SYNTHETIC-ALL",
        display_name="Synthetic all sectors",
        official_capacity=200,
        calculation_policy=CalculationPolicy.STANDARD,
    )
    for index in range(1, sectors + 1):
        CapacitySectorMembership.objects.create(
            catalog=catalog,
            group=group,
            source_code=str(600 + index),
            configured_source_name=f"SETOR {index:03d}",
        )
    return catalog


def _group_values(measurement) -> dict:
    return {
        group.stable_key: (
            group.calculation_status,
            group.official_capacity,
            group.occupied_count,
            group.occupancy_percentage,
            group.exceeded_by,
            group.official_availability,
            group.status_counts_json,
            group.components_json,
        )
        for group in measurement.groups.order_by("stable_key")
    }


@pytest.mark.django_db
class TestCensusSourceTimestampIntegration:
    def test_command_persists_precision_with_run_provenance(self):
        run = _run_command(_synthetic_csv(sectors=41, enriched=True))

        snapshot = CensusSnapshot.objects.get(leito="LEITO001A")

        assert run.status == "succeeded"
        assert snapshot.ingestion_run_id == run.pk
        assert snapshot.source_admission_at == datetime(
            2026, 2, 1, 8, 15, tzinfo=LOCAL_TZ
        )
        assert snapshot.source_movement_at == datetime(
            2026, 2, 2, 9, 45, tzinfo=LOCAL_TZ
        )
        assert snapshot.data_internacao == ADMISSION_DATE
        assert snapshot.data_movimentacao == MOVEMENT_DATE
        assert timezone.is_aware(snapshot.source_admission_at)

    def test_invalid_timestamp_after_valid_rows_persists_nothing(self, capsys):
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

    def test_enriched_rows_preserve_clinical_consumers(self):
        run = _run_command(_synthetic_csv(sectors=41, enriched=True))

        result = process_census_snapshot(run_id=run.pk)

        assert result["rejected"] is False
        assert result["patients_total"] == 41
        assert Patient.objects.count() == 41
        assert not Patient.objects.filter(
            name__in=[RESERVED_LABEL, MAINTENANCE_LABEL, "DESOCUPADO"]
        ).exists()
        assert Admission.objects.count() == 0

        assert CensusSnapshot.objects.get(
            leito="LEITO001C"
        ).bed_status == BedStatus.RESERVED
        assert CensusSnapshot.objects.get(
            leito="LEITO001D"
        ).bed_status == BedStatus.MAINTENANCE
        assert CensusSnapshot.objects.get(
            leito="LEITO001B"
        ).bed_status == BedStatus.EMPTY
        assert CensusSnapshot.objects.get(
            leito="LEITO001A"
        ).age_band == OccupancyAgeBand.UNDER_12
        assert CensusSnapshot.objects.get(
            leito="LEITO002A"
        ).age_band == OccupancyAgeBand.AGE_12_OR_OVER

        first = upsert_patient_movements()
        second = upsert_patient_movements()

        assert first["movements_created"] == 41
        assert second["movements_created"] == 0
        assert second["movements_updated"] == 41
        assert PatientMovement.objects.count() == 41
        movement = PatientMovement.objects.get(
            patient__patient_source_key="SYN-0001",
            sector="SETOR 001",
        )
        assert movement.movement_date == date(2026, 2, 2)
        assert movement.sequence == 0

    def test_date_only_and_enriched_runs_produce_equivalent_occupancy(self):
        _create_catalog(sectors=41)
        date_only_run = _run_command(
            _synthetic_csv(sectors=41, enriched=False)
        )
        date_only_result = process_census_snapshot(run_id=date_only_run.pk)
        enriched_run = _run_command(_synthetic_csv(sectors=41, enriched=True))
        enriched_result = process_census_snapshot(run_id=enriched_run.pk)

        assert date_only_result["materialization_status"] == "created"
        assert enriched_result["materialization_status"] == "created"
        date_only_measurement = date_only_run.occupancy_measurement
        enriched_measurement = enriched_run.occupancy_measurement

        assert (
            date_only_measurement.occupied_for_rate
            == enriched_measurement.occupied_for_rate
        )
        assert (
            date_only_measurement.occupancy_percentage
            == enriched_measurement.occupancy_percentage
        )
        assert (
            date_only_measurement.known_capacity
            == enriched_measurement.known_capacity
        )
        assert _group_values(date_only_measurement) == _group_values(
            enriched_measurement
        )
        assert not CensusSnapshot.objects.filter(
            ingestion_run_id=date_only_run.pk,
            source_admission_at__isnull=False,
        ).exists()
        assert CensusSnapshot.objects.filter(
            ingestion_run_id=enriched_run.pk,
            source_admission_at__isnull=False,
        ).count() == 41
