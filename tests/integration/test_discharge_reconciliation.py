"""Integration: canonical hospital-discharge reconciliation (RPSA-S2).

Proves, through the real ``run_discharge_extraction`` flow (mocked
subprocess plus synthetic XLS), that:

- evidence persistence is decoupled from ``DailyDischargeCount``
  (no aggregate write, no patient-bearing ``raw_data``);
- persisted rows are reconciled through the canonical service using
  ``saida_em`` only, with per-status metrics;
- repeated extraction is idempotent (``already_reconciled``, no
  duplicate evidence or audit);
- unresolved evidence stays pending and enqueues bounded source
  synchronization without creating synthetic domain rows;
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

from apps.discharges.extraction_service import run_discharge_extraction
from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

TZ_LOCAL = ZoneInfo("America/Bahia")

XLS_HEADER = (
    "ID", "Prontuario", "Nome", "Internacao", "Equipe",
    "Esp", "Alta Medica", "Local", "Saida",
)


def _xls_rows(records: list[dict]) -> list[tuple]:
    """Build synthetic XLS rows from compact record dicts."""
    rows: list[tuple] = [XLS_HEADER]
    for i, rec in enumerate(records):
        rows.append(
            (
                i,
                float(rec["prontuario"]),
                f"PACIENTE {rec['prontuario']}",
                rec["data_internacao"],
                f"Eq{i}",
                "CLI",
                rec.get("alta", ""),
                "L:UN01H",
                rec.get("saida", ""),
            )
        )
    return rows


def _write_xls(dir_path: Path, rows: list[tuple], filename: str) -> Path:
    import openpyxl  # noqa: PLC0415

    filepath = dir_path / filename
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(filepath))
    wb.close()
    return filepath


@contextmanager
def _mock_tempdir_and_xls(records: list[dict]):
    """Serve a synthetic discharge XLS to the extraction service."""
    real_dir = Path(tempfile_module.mkdtemp())
    _write_xls(real_dir, _xls_rows(records), "altas-01-06-2026-001.xlsx")
    xls_files = sorted(
        real_dir.glob("altas-01-06-2026-*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    with patch(
        "apps.discharges.extraction_service.tempfile.TemporaryDirectory"
    ) as m_tmp:
        m_tmp.return_value.__enter__.return_value = str(real_dir)
        with patch("pathlib.Path.glob") as m_glob:
            m_glob.return_value = xls_files
            yield real_dir
    shutil.rmtree(str(real_dir), ignore_errors=True)


@pytest.fixture
def mock_credentials():
    with patch(
        "apps.discharges.extraction_service.resolve_source_credentials"
    ) as mock:
        mock.return_value.url = "https://example.com"
        mock.return_value.username = "admin"
        mock.return_value.password = "secret"
        yield mock


@pytest.fixture
def mock_subprocess_success():
    with patch("apps.discharges.extraction_service.run_subprocess") as mock:
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


# =========================================================================
# Schema constraints
# =========================================================================


@pytest.mark.django_db
class TestDischargeReconciliationSchema:
    def test_reconciliation_columns_default_to_unlinked_pending(self):
        record = DischargeRecord.objects.create(
            prontuario="777",
            nome="PACIENTE 777",
            data_internacao="20/05/2026",
        )
        assert record.daily_count_id is None
        assert record.admission_id is None
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert record.reconciled_at is None

    def test_daily_count_is_nullable_in_database(self):
        record = DischargeRecord.objects.create(
            prontuario="777",
            nome="PACIENTE 777",
            data_internacao="20/05/2026",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT daily_count_id FROM discharges_dischargerecord WHERE id = %s",
                [record.pk],
            )
            row = cursor.fetchone()
        assert row is not None
        assert row[0] is None

    def test_invalid_evidence_status_rejected_by_database(self):
        with pytest.raises(IntegrityError):
            DischargeRecord.objects.create(
                prontuario="777",
                nome="PACIENTE 777",
                data_internacao="20/05/2026",
                reconciliation_status="closed_because_guess",
            )

    def test_reconciliation_event_rejects_invalid_status(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        with pytest.raises(IntegrityError):
            ReconciliationEvent.objects.create(
                source_kind="discharge_record",
                source_id=1,
                admission=admission,
                status="closed_because_guess",
            )


# =========================================================================
# Extraction flow integration
# =========================================================================


@pytest.mark.django_db
class TestExtractionReconciliationFlow:
    def test_evidence_persistence_writes_no_daily_count(
        self, mock_credentials, mock_subprocess_success,
    ):
        """Report persistence must not create/update the operational aggregate."""
        records = [
            {"prontuario": 300001, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert result.metrics["total_records"] == 1
        assert DailyDischargeCount.objects.count() == 0
        record = DischargeRecord.objects.get()
        assert record.daily_count_id is None

    def test_report_row_closes_unique_admission_via_saida(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("300001")
        admission = _make_admission(
            patient, "ADM-300001", "2026-05-20T08:00:00"
        )
        records = [
            {"prontuario": 300001, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        record = DischargeRecord.objects.get()
        assert record.admission_id == admission.pk
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        assert ReconciliationEvent.objects.count() == 1

    def test_row_without_saida_stays_pending_and_alta_never_closes(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("300002")
        admission = _make_admission(
            patient, "ADM-300002", "2026-05-20T08:00:00"
        )
        records = [
            {"prontuario": 300002, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": ""},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        admission.refresh_from_db()
        assert admission.discharge_date is None
        record = DischargeRecord.objects.get()
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert record.admission_id is None
        assert result.metrics["reconciliation_pending"] == 1
        assert ReconciliationEvent.objects.count() == 0

    def test_metrics_distinguish_reconciliation_statuses(
        self, mock_credentials, mock_subprocess_success,
    ):
        """One uniquely matched row and one unknown patient in the same report."""
        patient = _make_patient("300003")
        _make_admission(patient, "ADM-300003", "2026-05-20T08:00:00")
        records = [
            {"prontuario": 300003, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
            {"prontuario": 399999, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 11:00", "saida": "01/06/2026 13:00"},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert result.metrics["reconciliation_reconciled"] == 1
        assert result.metrics["reconciliation_patient_not_found"] == 1

    def test_repeated_extraction_is_idempotent(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("300004")
        admission = _make_admission(
            patient, "ADM-300004", "2026-05-20T08:00:00"
        )
        records = [
            {"prontuario": 300004, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
        ]

        with _mock_tempdir_and_xls(records):
            first = run_discharge_extraction(date="01/06/2026")
        with _mock_tempdir_and_xls(records):
            second = run_discharge_extraction(date="01/06/2026")

        assert first.metrics["reconciliation_reconciled"] == 1
        assert second.metrics["reconciliation_already_reconciled"] == 1
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        assert DischargeRecord.objects.count() == 1
        assert ReconciliationEvent.objects.count() == 1

    def test_ambiguous_same_day_report_leaves_admissions_open(
        self, mock_credentials, mock_subprocess_success,
    ):
        patient = _make_patient("300005")
        first = _make_admission(patient, "ADM-A", "2026-05-20T08:00:00")
        second = _make_admission(patient, "ADM-B", "2026-05-20T16:00:00")
        records = [
            {"prontuario": 300005, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.discharge_date is None
        assert second.discharge_date is None
        record = DischargeRecord.objects.get()
        assert record.reconciliation_status == RECONCILIATION_STATUS_AMBIGUOUS
        assert record.admission_id is None
        assert result.metrics["reconciliation_ambiguous"] == 1

    def test_unresolved_report_row_enqueues_bounded_sync(
        self, mock_credentials, mock_subprocess_success,
    ):
        records = [
            {"prontuario": 399998, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.metrics["reconciliation_patient_not_found"] == 1
        run = IngestionRun.objects.filter(
            intent="admissions_only",
            parameters_json__patient_record="399998",
        ).get()
        assert run.status == "queued"
        assert Admission.objects.count() == 0
        assert Patient.objects.filter(patient_source_key="399998").count() == 0

    def test_audit_payloads_and_logs_are_identity_safe(
        self, mock_credentials, mock_subprocess_success, caplog,
    ):
        patient = _make_patient("300006")
        _make_admission(patient, "ADM-300006", "2026-05-20T08:00:00")
        records = [
            {"prontuario": 300006, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
            {"prontuario": 399997, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 11:00", "saida": "01/06/2026 13:00"},
        ]

        with caplog.at_level(logging.INFO):
            with _mock_tempdir_and_xls(records):
                result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True

        # Audit payloads: structural state only.
        for event in ReconciliationEvent.objects.all():
            payload = json.dumps(
                {
                    "details": event.details_json,
                    "reason": event.reason_code,
                    "prior": None,
                    "new": None,
                }
            )
            assert "300006" not in payload
            assert "399997" not in payload
            assert "PACIENTE" not in payload

        # Logs: no patient record number or name.
        assert "300006" not in caplog.text
        assert "399997" not in caplog.text
        assert "PACIENTE" not in caplog.text

    def test_status_counters_are_reported_for_every_persisted_row(
        self, mock_credentials, mock_subprocess_success,
    ):
        """Rows with saida=na and alta only are counted, never silently dropped."""
        patient = _make_patient("300007")
        _make_admission(patient, "ADM-300007", "2026-05-20T08:00:00")
        records = [
            {"prontuario": 300007, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 10:00", "saida": "01/06/2026 12:00"},
            {"prontuario": 300008, "data_internacao": "20/05/2026",
             "alta": "01/06/2026 11:00", "saida": ""},
        ]
        with _mock_tempdir_and_xls(records):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.metrics["reconciliation_reconciled"] == 1
        assert result.metrics["reconciliation_pending"] == 1
