"""Integration: canonical death reconciliation through extraction (RPSA-S3).

Proves, through the real ``run_death_extraction`` flow (mocked subprocess
plus synthetic death JSON), that:

- a persisted death row with a complete datetime is reconciled through
  the canonical service and closes the unique containing admission as
  ``death`` with per-status metrics;
- date-only death rows stay pending, never synthesize an hour and
  enqueue deduplicated ``admissions_only`` confirmation;
- repeated extraction preserves the evidence PK/link/status and does not
  duplicate audit or synchronization runs;
- death persistence never touches ``DailyDischargeCount`` and never
  creates synthetic patients or admissions;
- schema constraints enforce exactly the eight reconciliation statuses;
- audit payloads and logs carry no patient identity.

All fixtures are synthetic.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile as tempfile_module
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, connection

from apps.deaths.models import DeathRecord
from apps.deaths.services import run_death_extraction
from apps.discharges.models import DailyDischargeCount
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

TZ_LOCAL = ZoneInfo("America/Bahia")


def _death_json(records: list[dict[str, str]]) -> dict:
    return {
        "data": "01/06/2026",
        "start_date": "01/06/2026",
        "end_date": "01/06/2026",
        "total": len(records),
        "columns": list(records[0].keys()) if records else [],
        "records": records,
    }


def _write_json(tmpdir_path: Path, data: dict) -> Path:
    filepath = tmpdir_path / "obitos-01-06-2026.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return filepath


@contextmanager
def _mock_tempdir_and_json(records: list[dict[str, str]]):
    real_dir = Path(tempfile_module.mkdtemp())
    _write_json(real_dir, _death_json(records))
    json_files = sorted(
        real_dir.glob("obitos-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    try:
        with patch(
            "apps.deaths.services.tempfile.TemporaryDirectory"
        ) as m_tmp:
            m_tmp.return_value.__enter__.return_value = str(real_dir)
            with patch("pathlib.Path.glob") as m_glob:
                m_glob.return_value = json_files
                yield real_dir
    finally:
        shutil.rmtree(str(real_dir), ignore_errors=True)


@pytest.fixture
def mock_credentials():
    with patch("apps.deaths.services.resolve_source_credentials") as mock:
        mock.return_value.url = "https://example.com"
        mock.return_value.username = "admin"
        mock.return_value.password = "secret"
        yield mock


@pytest.fixture
def mock_subprocess_success():
    with patch("apps.deaths.services.run_subprocess") as mock:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        mock.return_value = proc
        yield mock


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str,
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=datetime.fromisoformat(start).replace(tzinfo=TZ_LOCAL),
        discharge_date=(
            datetime.fromisoformat(end).replace(tzinfo=TZ_LOCAL) if end else None
        ),
    )


COMPLETE_DATETIME = "01/06/2026 12:00"
DATE_ONLY = "01/06/2026"


def _record(prontuario: str, data_obito: str) -> dict[str, str]:
    return {
        "PRONTUARIO": prontuario,
        "NOME": f"PACIENTE {prontuario}",
        "OBITO": data_obito,
        "DATA OBITO": data_obito,
    }


# =========================================================================
# Schema constraints
# =========================================================================


@pytest.mark.django_db
class TestDeathReconciliationSchema:
    def test_reconciliation_columns_default_to_unlinked_pending(self):
        record = DeathRecord.objects.create(
            date=datetime(2026, 6, 1).date(),
            prontuario="555",
            nome="PACIENTE 555",
        )
        assert record.daily_count_id is None
        assert record.admission_id is None
        assert record.obito_em is None
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert record.reconciled_at is None

    def test_daily_count_is_nullable_in_database(self):
        record = DeathRecord.objects.create(
            date=datetime(2026, 6, 1).date(),
            prontuario="555",
            nome="PACIENTE 555",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT daily_count_id, admission_id, obito_em "
                "FROM deaths_deathrecord WHERE id = %s",
                [record.pk],
            )
            row = cursor.fetchone()
        assert row is not None
        assert row == (None, None, None)

    def test_invalid_evidence_status_rejected_by_database(self):
        with pytest.raises(IntegrityError):
            DeathRecord.objects.create(
                date=datetime(2026, 6, 1).date(),
                prontuario="555",
                nome="PACIENTE 555",
                reconciliation_status="closed_because_guess",
            )


# =========================================================================
# Extraction flow integration
# =========================================================================


@pytest.mark.django_db
class TestDeathExtractionReconciliationFlow:
    def test_complete_datetime_closes_unique_admission_as_death(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("600001")
        admission = _make_admission(patient, "ADM-600001", "2026-05-20T08:00:00")
        records = [_record("600001", COMPLETE_DATETIME)]

        with _mock_tempdir_and_json(records):
            result = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )

        assert result.success is True
        assert result.metrics.get("reconciliation_reconciled") == 1
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        record = DeathRecord.objects.get()
        assert record.admission_id == admission.pk
        assert record.obito_em == datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        event = ReconciliationEvent.objects.get()
        assert event.exit_type == "death"
        assert event.source_kind == "death_record"

    def test_death_extraction_never_writes_discharge_aggregate(
        self, mock_credentials, mock_subprocess_success,
    ):
        _make_patient("600002")
        _make_admission(
            _make_patient("600003"), "ADM-600003", "2026-05-20T08:00:00"
        )
        records = [
            _record("600002", COMPLETE_DATETIME),
            _record("600003", COMPLETE_DATETIME),
        ]

        with _mock_tempdir_and_json(records):
            result = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )

        assert result.success is True
        assert DailyDischargeCount.objects.count() == 0

    def test_date_only_death_stays_pending_and_enqueues_admissions_only(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("600004")
        admission = _make_admission(patient, "ADM-600004", "2026-05-20T08:00:00")
        records = [_record("600004", DATE_ONLY)]

        with _mock_tempdir_and_json(records):
            result = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )

        assert result.success is True
        assert result.metrics.get("reconciliation_pending") == 1
        admission.refresh_from_db()
        assert admission.discharge_date is None  # no synthesized hour
        record = DeathRecord.objects.get()
        assert record.obito_em is None
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        run = IngestionRun.objects.filter(intent="admissions_only").get()
        assert run.status == "queued"
        assert run.parameters_json["patient_record"] == "600004"
        assert (
            IngestionRun.objects.filter(intent="demographics_only").count() == 0
        )

    def test_missing_patient_enqueues_bounded_sync_without_synthetic_rows(
        self, mock_credentials, mock_subprocess_success,
    ):
        records = [_record("699999", COMPLETE_DATETIME)]

        with _mock_tempdir_and_json(records):
            result = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )

        assert result.metrics.get("reconciliation_patient_not_found") == 1
        assert Admission.objects.count() == 0
        assert Patient.objects.filter(patient_source_key="699999").count() == 0
        admissions_runs = IngestionRun.objects.filter(intent="admissions_only")
        demographics_runs = IngestionRun.objects.filter(
            intent="demographics_only"
        )
        assert admissions_runs.count() == 1
        assert demographics_runs.count() == 1

    def test_repeated_extraction_preserves_pk_link_and_status(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("600005")
        admission = _make_admission(patient, "ADM-600005", "2026-05-20T08:00:00")
        records = [_record("600005", COMPLETE_DATETIME)]

        with _mock_tempdir_and_json(records):
            first = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )
        record = DeathRecord.objects.get()
        original_pk = record.pk

        with _mock_tempdir_and_json(records):
            second = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )

        assert first.metrics.get("reconciliation_reconciled") == 1
        assert second.metrics.get("reconciliation_already_reconciled") == 1
        record.refresh_from_db()
        assert record.pk == original_pk
        assert record.admission_id == admission.pk
        assert (
            record.reconciliation_status
            == RECONCILIATION_STATUS_ALREADY_RECONCILED
        )
        assert DeathRecord.objects.count() == 1
        assert ReconciliationEvent.objects.count() == 1
        # Reconciled evidence never enqueues source synchronization.
        assert IngestionRun.objects.filter(
            intent__in=("admissions_only", "demographics_only")
        ).count() == 0

    def test_row_absent_from_repeated_snapshot_is_retained(
        self, mock_credentials, mock_subprocess_success,
    ):
        _make_patient("600006")
        records_first = [
            _record("600006", COMPLETE_DATETIME),
            _record("600007", COMPLETE_DATETIME),
        ]

        with _mock_tempdir_and_json(records_first):
            run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )
        assert DeathRecord.objects.count() == 2

        records_second = [_record("600006", COMPLETE_DATETIME)]
        with _mock_tempdir_and_json(records_second):
            second = run_death_extraction(
                start_date="01/06/2026", end_date="01/06/2026",
            )

        assert second.success is True
        assert DeathRecord.objects.count() == 2
        absent = DeathRecord.objects.get(prontuario="600007")
        assert absent.daily_count_id is None
        aggregate_records = DeathRecord.objects.filter(daily_count__isnull=False)
        assert aggregate_records.count() == 1

    def test_audit_and_logs_are_identity_safe(
        self, mock_credentials, mock_subprocess_success, caplog,
    ):
        patient = _make_patient("600008")
        _make_admission(patient, "ADM-600008", "2026-05-20T08:00:00")
        records = [
            _record("600008", COMPLETE_DATETIME),
            _record("699998", COMPLETE_DATETIME),
        ]

        with caplog.at_level(logging.INFO):
            with _mock_tempdir_and_json(records):
                result = run_death_extraction(
                    start_date="01/06/2026", end_date="01/06/2026",
                )

        assert result.success is True

        for event in ReconciliationEvent.objects.all():
            payload = json.dumps(
                {
                    "details": event.details_json,
                    "reason": event.reason_code,
                    "status": event.status,
                }
            )
            assert "600008" not in payload
            assert "699998" not in payload
            assert "PACIENTE" not in payload

        assert "600008" not in caplog.text
        assert "699998" not in caplog.text
        assert "PACIENTE" not in caplog.text
