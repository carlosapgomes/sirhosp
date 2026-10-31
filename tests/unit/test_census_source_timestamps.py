"""ECD-S1: source timestamp precision at the CSV parser boundary.

These tests describe the behavior approved by
``openspec/changes/extract-daily-census-from-dom`` (D6): a full source
timestamp is retained as an aware datetime while the legacy date-only
fields keep their established projections. Only synthetic rows are used.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.utils import timezone as django_timezone

from apps.census.models import BedStatus
from apps.census.services import parse_census_csv

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


def _csv_line(**overrides: str) -> str:
    values = {
        "setor_codigo": "640",
        "setor": "UTI A",
        "qrt_leito": "UG01A",
        "prontuario": "SYN-0001",
        "nome": "PACIENTE SINTETICO",
        "esp": "CLI",
        "dt_int": "",
        "tempo": "3",
        "idade": "40",
        "convenio": "",
        "dt_mvt": "",
        "alta": "",
        "origem": "",
    }
    values.update(overrides)
    return ",".join(values[column] for column in COLUMNS)


def _write_csv(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "censo-synthetic.csv"
    path.write_text(CSV_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_both_source_timestamps_are_aware_in_configured_timezone(tmp_path):
    path = _write_csv(
        tmp_path,
        [
            _csv_line(
                dt_int="25/12/2026 10:30",
                dt_mvt="26/12/2026 23:05",
            )
        ],
    )

    row = parse_census_csv(path)[0]

    admission_at = row.get("source_admission_at")
    movement_at = row.get("source_movement_at")
    assert admission_at == datetime(2026, 12, 25, 10, 30, tzinfo=LOCAL_TZ)
    assert movement_at == datetime(2026, 12, 26, 23, 5, tzinfo=LOCAL_TZ)
    assert django_timezone.is_aware(admission_at)
    assert django_timezone.is_aware(movement_at)
    assert admission_at.utcoffset() == timedelta(hours=-3)
    assert movement_at.utcoffset() == timedelta(hours=-3)
    assert row["data_internacao"] == "25/12/2026"
    assert row["data_movimentacao"] == "26/12/2026"
    assert row["bed_status"] == BedStatus.OCCUPIED


def test_local_calendar_projection_does_not_shift_the_day(tmp_path):
    path = _write_csv(
        tmp_path,
        [
            _csv_line(
                dt_int="01/01/2026 00:15",
                dt_mvt="31/12/2026 23:59",
            )
        ],
    )

    row = parse_census_csv(path)[0]

    assert row["source_admission_at"] == datetime(
        2026, 1, 1, 0, 15, tzinfo=LOCAL_TZ
    )
    assert row["source_movement_at"] == datetime(
        2026, 12, 31, 23, 59, tzinfo=LOCAL_TZ
    )
    assert row["data_internacao"] == "01/01/2026"
    assert row["data_movimentacao"] == "31/12/2026"


def test_legacy_date_only_values_keep_processing_and_leave_precision_null(
    tmp_path,
):
    path = _write_csv(
        tmp_path,
        [
            _csv_line(
                dt_int="25/12/2025",
                dt_mvt="26/12/2025",
            )
        ],
    )

    row = parse_census_csv(path)[0]

    assert row.get("source_admission_at") is None
    assert row.get("source_movement_at") is None
    assert row["data_internacao"] == "25/12/2025"
    assert row["data_movimentacao"] == "26/12/2025"


def test_empty_source_values_keep_empty_text_and_null_precision(tmp_path):
    path = _write_csv(tmp_path, [_csv_line(dt_int="", dt_mvt="")])

    row = parse_census_csv(path)[0]

    assert row.get("source_admission_at") is None
    assert row.get("source_movement_at") is None
    assert row["data_internacao"] == ""
    assert row["data_movimentacao"] == ""


def test_bed_label_row_without_patient_keeps_movement_precision(tmp_path):
    path = _write_csv(
        tmp_path,
        [
            _csv_line(
                prontuario="",
                nome="RESERVA INTERNA",
                idade="",
                dt_int="",
                dt_mvt="27/12/2026 14:45",
            )
        ],
    )

    row = parse_census_csv(path)[0]

    assert row["bed_status"] == BedStatus.RESERVED
    assert row.get("source_admission_at") is None
    assert row.get("source_movement_at") == datetime(
        2026, 12, 27, 14, 45, tzinfo=LOCAL_TZ
    )
    assert row["data_internacao"] == ""
    assert row["data_movimentacao"] == "27/12/2026"


@pytest.mark.parametrize(
    "invalid_value",
    [
        "31/02/2026 10:00",
        "25/12/2026 24:00",
        "25/12/2026 10:60",
        "25/12/2026 10:0",
        "25/12/2026 10:30:15",
        "25-12-2026 10:30",
    ],
)
def test_invalid_admission_timestamp_is_rejected_without_leaking_value(
    tmp_path, invalid_value
):
    path = _write_csv(tmp_path, [_csv_line(dt_int=invalid_value)])

    with pytest.raises(ValueError) as excinfo:
        parse_census_csv(path)

    message = str(excinfo.value)
    assert "source admission timestamp" in message.lower()
    assert invalid_value not in message
    assert "SYN-0001" not in message
    assert "PACIENTE SINTETICO" not in message


def test_invalid_movement_timestamp_is_rejected_without_leaking_value(tmp_path):
    path = _write_csv(
        tmp_path,
        [_csv_line(dt_mvt="32/12/2026 09:00")],
    )

    with pytest.raises(ValueError) as excinfo:
        parse_census_csv(path)

    message = str(excinfo.value)
    assert "source movement timestamp" in message.lower()
    assert "32/12/2026 09:00" not in message
    assert "SYN-0001" not in message
