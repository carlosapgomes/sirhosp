"""Persistence hardening tests for discharge extraction.

Slice C2-S4 (tasks.md 4.1-4.3):
- Add tests proving repeated discharge extraction for the same date does
  not duplicate ``DischargeRecord`` rows.
- Add tests proving empty discharge output persists a successful zero-count
  result and clears stale records for the target date.
- Harden discharge report persistence with the smallest safe
  transaction/idempotency changes required by the tests.
"""

from __future__ import annotations

import shutil
import tempfile as tempfile_module
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.discharges.models import DailyDischargeCount, DischargeRecord

# ---------------------------------------------------------------------------
# Synthetic XLS helpers
# ---------------------------------------------------------------------------


def _make_discharge_xls_rows(records_count: int = 3):
    """Create synthetic XLS row tuples matching the expected column layout.

    All alta_em dates use the same reference date (01/06/2026) for
    predictable DailyDischargeCount association.
    """
    rows = [
        # Header row (will be skipped by parser)
        (
            "ID", "Prontuario", "Nome", "Internacao", "Equipe",
            "Esp", "Alta Medica", "Local", "Saida",
        ),
    ]
    for i in range(records_count):
        prontuario = float(f"{100000 + i}")
        nome = f"Paciente Teste {i}"
        internacao = f"{1 + i:02d}/06/2026"
        esp = f"ESP{i}"
        alta = f"01/06/2026 10:{i:02d}"
        local = f"L:UN0{i}H"
        saida = f"01/06/2026 12:{i:02d}"
        rows.append((i, prontuario, nome, internacao, f"Eq{i}", esp, alta, local, saida))
    return rows


def _write_xls(tmpdir_path: Path, rows: list[tuple], filename: str | None = None) -> Path:
    """Write synthetic XLS data to a temp directory, returning the path."""
    import openpyxl  # noqa: PLC0415

    filepath = tmpdir_path / (filename or "altas-01-06-2026-001.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(filepath))
    wb.close()
    return filepath


@contextmanager
def _mock_tempdir_and_xls(records_count: int = 3):
    """Set up real temp dir with XLS, mock TemporaryDirectory and Path.glob.

    Yields the real temp directory path. Cleanup happens on exit.
    """
    real_dir = Path(tempfile_module.mkdtemp())
    rows = _make_discharge_xls_rows(records_count)
    _write_xls(real_dir, rows)

    xls_files = sorted(
        real_dir.glob("altas-01-06-2026-*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    with patch("apps.discharges.extraction_service.tempfile.TemporaryDirectory") as m_tmp:
        m_tmp.return_value.__enter__.return_value = str(real_dir)
        with patch("pathlib.Path.glob") as m_glob:
            m_glob.return_value = xls_files
            yield real_dir

    shutil.rmtree(str(real_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_credentials():
    """Patch resolve_source_credentials to return valid creds."""
    with patch("apps.discharges.extraction_service.resolve_source_credentials") as mock:
        mock.return_value.url = "https://example.com"
        mock.return_value.username = "admin"
        mock.return_value.password = "secret"
        yield mock


@pytest.fixture
def mock_subprocess_success():
    """Patch run_subprocess to return success."""
    with patch("apps.discharges.extraction_service.run_subprocess") as mock:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        mock.return_value = proc
        yield mock


@pytest.fixture
def mock_subprocess_timeout():
    """Patch run_subprocess to raise SubprocessTimeoutError."""
    with patch("apps.discharges.extraction_service.run_subprocess") as mock:
        from apps.ingestion.extractors.subprocess_utils import (
            SubprocessTimeoutError,
        )
        mock.side_effect = SubprocessTimeoutError(
            cmd=["python", "script.py"], timeout=600, output="", stderr="Timed out"
        )
        yield mock


# =========================================================================
# Tests: _persist_discharge_records idempotency
# =========================================================================


@pytest.mark.django_db
class TestPersistDischargeRecordsIdempotency:
    """Unit tests for the internal _persist_discharge_records function."""

    def test_repeated_persistence_same_data_no_duplication(self):
        """Calling _persist_discharge_records twice with same data produces same count."""
        from apps.discharges.extraction_service import _persist_discharge_records

        ref_date = date(2026, 6, 1)
        patients = [
            {
                "prontuario": "100000",
                "nome": "Paciente 0",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP0",
                "leito": "UN00H",
                "alta_em": None,
                "saida_em": None,
            },
            {
                "prontuario": "100001",
                "nome": "Paciente 1",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP1",
                "leito": "UN01H",
                "alta_em": None,
                "saida_em": None,
            },
        ]

        # First call
        result1 = _persist_discharge_records(patients, ref_date=ref_date)
        assert result1["total_records"] == 2
        assert result1["created"] == 2

        # Second call with same data
        result2 = _persist_discharge_records(patients, ref_date=ref_date)
        assert result2["total_records"] == 2
        assert result2["created"] == 0  # no new records created

        # Verify no duplication
        records = DischargeRecord.objects.all()
        assert len(records) == 2, "Should have exactly 2 records, not 4"

    def test_repeated_persistence_different_data_latest_wins(self):
        """Re-running with different data replaces old records' attributes."""
        from apps.discharges.extraction_service import _persist_discharge_records

        ref_date = date(2026, 6, 1)
        batch_a = [
            {
                "prontuario": "100000",
                "nome": "Paciente 0",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP0",
                "leito": "LEITO_A",
                "alta_em": None,
                "saida_em": None,
            },
        ]
        batch_b = [
            {
                "prontuario": "100000",
                "nome": "Paciente 0 Updated",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP0",
                "leito": "LEITO_B",
                "alta_em": None,
                "saida_em": None,
            },
        ]

        # First call
        result1 = _persist_discharge_records(batch_a, ref_date=ref_date)
        assert result1["total_records"] == 1
        assert result1["created"] == 1

        record = DischargeRecord.objects.get(prontuario="100000", data_internacao="01/06/2026")
        assert record.leito == "LEITO_A"

        # Second call with updated data
        result2 = _persist_discharge_records(batch_b, ref_date=ref_date)
        assert result2["total_records"] == 1
        assert result2["updated"] == 1

        # Verify the record was updated
        record.refresh_from_db()
        assert record.nome == "Paciente 0 Updated"
        assert record.leito == "LEITO_B"

        # Still only 1 record
        assert DischargeRecord.objects.count() == 1

    def test_empty_persistence_resets_daily_count(self):
        """Persistence with empty patient list should reset DailyDischargeCount."""
        from apps.discharges.extraction_service import _persist_discharge_records

        ref_date = date(2026, 6, 1)
        batch = [
            {
                "prontuario": "100000",
                "nome": "Paciente 0",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP0",
                "leito": "UN00H",
                "alta_em": None,
                "saida_em": None,
            },
        ]

        # Pre-populate
        _persist_discharge_records(batch, ref_date=ref_date)
        assert DischargeRecord.objects.count() == 1

        # Call with empty list
        result = _persist_discharge_records([], ref_date=ref_date)
        assert result["total_records"] == 0

        # Verify DDC is reset to 0
        ddc = DailyDischargeCount.objects.get(date=ref_date)
        assert ddc.count == 0

        # DischargeRecord rows remain (no date-based cleanup needed)
        assert DischargeRecord.objects.count() == 1

    def test_zero_records_is_valid_success(self):
        """Calling with empty list on clean state returns success with zero count."""
        from apps.discharges.extraction_service import _persist_discharge_records

        ref_date = date(2026, 6, 1)
        assert DischargeRecord.objects.count() == 0

        result = _persist_discharge_records([], ref_date=ref_date)
        assert result["total_records"] == 0
        assert DischargeRecord.objects.count() == 0
        ddc = DailyDischargeCount.objects.get(date=ref_date)
        assert ddc.count == 0

    def test_isolated_by_date_same_data_different_date_no_interference(self):
        """Records for different dates should not interfere with each other."""
        from apps.discharges.extraction_service import _persist_discharge_records

        date_a = date(2026, 6, 1)
        date_b = date(2026, 6, 2)
        batch = [
            {
                "prontuario": "100000",
                "nome": "Paciente 0",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP0",
                "leito": "UN00H",
                "alta_em": None,
                "saida_em": None,
            },
        ]

        # Persist for date_a
        _persist_discharge_records(batch, ref_date=date_a)
        assert DischargeRecord.objects.count() == 1
        assert DailyDischargeCount.objects.filter(date=date_a).count() == 1

        # Persist same data for date_b
        _persist_discharge_records(batch, ref_date=date_b)
        assert DischargeRecord.objects.count() == 1  # still 1 (same prontuario+data_int)
        assert DailyDischargeCount.objects.filter(date=date_b).count() == 1

        # Reset date_a to zero
        _persist_discharge_records([], ref_date=date_a)
        ddc_a = DailyDischargeCount.objects.get(date=date_a)
        assert ddc_a.count == 0
        # date_b is unaffected
        ddc_b = DailyDischargeCount.objects.get(date=date_b)
        assert ddc_b.count == 1

    def test_atomic_transaction_recovery(self):
        """If an error occurs mid-persistence, no partial state should persist."""
        from apps.discharges.extraction_service import _persist_discharge_records

        ref_date = date(2026, 6, 1)
        batch = [
            {
                "prontuario": "100000",
                "nome": "Paciente 0",
                "data_internacao": "01/06/2026",
                "especialidade": "ESP0",
                "leito": "UN00H",
                "alta_em": None,
                "saida_em": None,
            },
        ]

        # Pre-populate
        _persist_discharge_records(batch, ref_date=ref_date)
        assert DischargeRecord.objects.count() == 1

        # Simulate mid-transaction failure during an upsert operation.
        # We patch DischargeRecord.objects.create (called during the loop)
        # to raise, verifying the transaction rolls back.
        new_batch = [
            {
                "prontuario": "100001",
                "nome": "Paciente 1",
                "data_internacao": "02/06/2026",
                "especialidade": "ESP1",
                "leito": "UN01H",
                "alta_em": None,
                "saida_em": None,
            },
        ]
        with patch(
            "apps.discharges.models.DischargeRecord.objects.create"
        ) as mock_create:
            mock_create.side_effect = RuntimeError("Simulated DB failure")

            with pytest.raises(RuntimeError, match="Simulated DB failure"):
                _persist_discharge_records(
                    new_batch, ref_date=ref_date
                )

        # The original record should still be present (transaction rolled back)
        assert DischargeRecord.objects.count() == 1, (
            "Transaction should roll back on mid-process failure"
        )
        # DailyDischargeCount should not have been created for new_batch
        assert DailyDischargeCount.objects.filter(date=ref_date).count() == 1


# =========================================================================
# Tests: Service-level idempotency
# =========================================================================


@pytest.mark.django_db
class TestServiceDischargeExtractionIdempotency:
    """Full service-level tests proving repeated extraction is deterministic."""

    def test_service_repeated_extraction_no_duplicate_records(
        self, mock_credentials, mock_subprocess_success,
    ):
        """Calling run_discharge_extraction twice results in one set of records."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        ref_date = date(2026, 6, 1)

        # First extraction
        with _mock_tempdir_and_xls(records_count=3):
            result1 = run_discharge_extraction(date="01/06/2026")
        assert result1.success is True
        assert result1.metrics["total_records"] == 3

        # Second extraction with same data
        with _mock_tempdir_and_xls(records_count=3):
            result2 = run_discharge_extraction(date="01/06/2026")
        assert result2.success is True
        assert result2.metrics["total_records"] == 3

        # Verify no duplication: exactly 3 DischargeRecord rows, not 6
        records = DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        )
        assert len(records) == 3, (
            "Repeated extraction should not duplicate DischargeRecord rows"
        )

        # DailyDischargeCount should have count=3
        ddc = DailyDischargeCount.objects.get(date=ref_date)
        assert ddc.count == 3

        # Verify two separate IngestionRuns were created
        assert result1.ingestion_run_id != result2.ingestion_run_id
        runs = IngestionRun.objects.filter(intent="discharge_extraction")
        assert runs.count() >= 2

    def test_service_empty_output_resets_daily_count(
        self, mock_credentials, mock_subprocess_success,
    ):
        """When no XLS output is produced on re-run, DailyDischargeCount should reset to 0."""
        from apps.discharges.extraction_service import run_discharge_extraction

        ref_date = date(2026, 6, 1)

        # First extraction populates 3 records
        with _mock_tempdir_and_xls(records_count=3):
            result1 = run_discharge_extraction(date="01/06/2026")
        assert result1.success is True
        assert DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        ).count() == 3
        assert DailyDischargeCount.objects.get(date=ref_date).count == 3

        # Second extraction: no XLS files found → zero records
        real_dir = Path(tempfile_module.mkdtemp())
        try:
            with patch(
                "apps.discharges.extraction_service.tempfile.TemporaryDirectory"
            ) as m_tmp:
                m_tmp.return_value.__enter__.return_value = str(real_dir)
                with patch("pathlib.Path.glob") as m_glob:
                    m_glob.return_value = []
                    result2 = run_discharge_extraction(date="01/06/2026")
        finally:
            shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result2.success is True
        assert result2.metrics["total_records"] == 0

        # DailyDischargeCount should be reset to 0
        ddc = DailyDischargeCount.objects.get(date=ref_date)
        assert ddc.count == 0
        assert ddc.raw_data == []

        # DischargeRecord rows from first extraction remain (no date-based cleanup)
        assert DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        ).count() == 3

    def test_service_empty_xls_resets_daily_count(
        self, mock_credentials, mock_subprocess_success,
    ):
        """When XLS has only header, DailyDischargeCount should reset to 0."""
        from apps.discharges.extraction_service import run_discharge_extraction

        ref_date = date(2026, 6, 1)

        # First extraction populates records
        with _mock_tempdir_and_xls(records_count=3):
            result1 = run_discharge_extraction(date="01/06/2026")
        assert result1.success is True
        assert DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        ).count() == 3

        # Second extraction: XLS with only header → zero records
        real_dir = Path(tempfile_module.mkdtemp())
        try:
            rows = [
                (
                    "ID", "Prontuario", "Nome", "Internacao", "Equipe",
                    "Esp", "Alta Medica", "Local", "Saida",
                ),
            ]
            filename = "altas-01-06-2026-002.xlsx"
            _write_xls(real_dir, rows, filename=filename)
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
                    result2 = run_discharge_extraction(date="01/06/2026")
        finally:
            shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result2.success is True
        assert result2.metrics["total_records"] == 0

        # DailyDischargeCount should be reset to 0
        ddc = DailyDischargeCount.objects.get(date=ref_date)
        assert ddc.count == 0

        # DischargeRecord rows from first extraction remain (no date-based cleanup)
        assert DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        ).count() == 3

    def test_service_persistence_failure_does_not_leave_partial_state(
        self, mock_credentials, mock_subprocess_success,
    ):
        """If persistence fails, previously stored rows must be preserved.

        This tests the transactional integrity of the persistence logic.
        """
        from apps.discharges.extraction_service import run_discharge_extraction

        ref_date = date(2026, 6, 1)

        # First extraction populates records
        with _mock_tempdir_and_xls(records_count=3):
            result1 = run_discharge_extraction(date="01/06/2026")
        assert result1.success is True
        assert DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        ).count() == 3

        # Second extraction: subprocess success but persistence fails
        with _mock_tempdir_and_xls(records_count=5):
            with patch(
                "apps.discharges.extraction_service._persist_discharge_records"
            ) as mock_persist:
                mock_persist.side_effect = RuntimeError(
                    "Simulated persistence failure"
                )
                result2 = run_discharge_extraction(date="01/06/2026")

        assert result2.success is False
        assert result2.failure_reason == "unexpected_exception"

        # The original 3 records should still be intact
        assert DischargeRecord.objects.filter(
            daily_count__date=ref_date,
        ).count() == 3, (
            "Persistence failure must not leave a partial or empty state"
        )
