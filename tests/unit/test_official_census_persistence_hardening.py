"""Persistence hardening tests for official census extraction.

Slice C2-S2 (tasks.md 2.1-2.3):
- Add tests proving repeated official census extraction for the same date
  does not duplicate records.
- Add tests proving empty official census output persists a successful
  zero-count result and clears stale rows for the target date.
- Verify that process_official_census_records has date-replace semantics.
"""

from __future__ import annotations

import json
import shutil
import tempfile as tempfile_module
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.census.models import OfficialCensusRecord
from apps.census.services import (
    process_official_census_records,
    run_official_census_extraction,
)
from apps.ingestion.models import IngestionRun

# ---------------------------------------------------------------------------
# Synthetic record builders
# ---------------------------------------------------------------------------


def _make_record(
    prontuario: str = "PRT0001",
    nome: str = "Paciente 1",
    data_internacao: str = "01/06/2026",
    tempo_internacao: str = "5",
    quarto_leito: str = "LEITO01",
    cid: str = "A00",
    descricao: str = "Diagnóstico 1",
    unidade: str = "UTI",
    area_funcional: str = "AF01",
    sigla: str = "SIG1",
    especialidade: str = "CLI",
) -> dict[str, str | None]:
    """Build a single synthetic official census record dict."""
    return {
        "PRONTUARIO": prontuario,
        "NOME": nome,
        "DATA INTERNACAO": data_internacao,
        "TEMPO INT": tempo_internacao,
        "QUARTO/LEITO": quarto_leito,
        "CID INT": cid,
        "DESCRICAO": descricao,
        "UNIDADE": unidade,
        "AREA FUNCIONAL": area_funcional,
        "SIGLA": sigla,
        "ESPECIALIDADE": especialidade,
    }


def _make_records(count: int = 3) -> list[dict[str, str | None]]:
    """Build a list of synthetic official census record dicts."""
    records: list[dict[str, str | None]] = []
    for i in range(count):
        records.append(
            _make_record(
                prontuario=f"PRT{i:04d}",
                nome=f"Paciente {i}",
                quarto_leito=f"LEITO{i:02d}",
                cid=f"A{i:02d}",
                sigla=f"SIG{i}",
            )
        )
    return records


# ---------------------------------------------------------------------------
# Helpers for integration-level tests
# ---------------------------------------------------------------------------


def _make_official_census_json(records_count: int = 3) -> dict:
    """Create synthetic official census JSON matching automation output."""
    return {"records": _make_records(records_count)}


def _write_json(
    tmpdir_path: Path,
    data: dict,
    filename: str | None = None,
) -> Path:
    """Write JSON data to a temp directory, returning the path."""
    filepath = tmpdir_path / (
        filename or "censo-oficial-2026-06-01.json"
    )
    filepath.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    return filepath


@contextmanager
def _mock_tempdir_and_glob(records_count: int = 3):
    """Set up real temp dir with JSON, mock TemporaryDirectory and Path.glob.

    On enter, creates a real temp directory with ``records_count`` synthetic
    official census records and patches ``tempfile.TemporaryDirectory`` and
    ``pathlib.Path.glob`` so the service reads from that directory.

    Yields the real temp directory path. Cleanup happens on exit.
    """
    real_dir = Path(tempfile_module.mkdtemp())
    data = _make_official_census_json(records_count)
    _write_json(real_dir, data)

    json_files = sorted(
        real_dir.glob("censo-oficial-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    with patch("apps.census.services.tempfile.TemporaryDirectory") as m_tmp:
        m_tmp.return_value.__enter__.return_value = str(real_dir)
        with patch("pathlib.Path.glob") as m_glob:
            m_glob.return_value = json_files
            yield real_dir

    shutil.rmtree(str(real_dir), ignore_errors=True)


# =========================================================================
# Unit tests: process_official_census_records
# =========================================================================


@pytest.mark.django_db
class TestProcessOfficialCensusRecordsIdempotency:
    """The persistence function must be idempotent for the same date."""

    def test_repeated_persistence_same_data_no_duplication(self):
        """Calling process twice with same data should result in single set."""
        ref_date = date(2026, 6, 1)
        batch_a = _make_records(5)

        # First call
        result1 = process_official_census_records(batch_a, reference_date=ref_date)
        assert result1["total_records"] == 5

        # Second call with same data
        result2 = process_official_census_records(batch_a, reference_date=ref_date)
        assert result2["total_records"] == 5

        # Verify no duplication: exactly 5 rows, not 10
        stored = OfficialCensusRecord.objects.filter(date=ref_date)
        assert stored.count() == 5

    def test_repeated_persistence_different_data_latest_wins(self):
        """Calling process with different data should replace old records."""
        ref_date = date(2026, 6, 1)
        batch_a = _make_records(3)
        batch_b = _make_records(5)

        # First call with batch_a
        process_official_census_records(batch_a, reference_date=ref_date)
        # Second call with batch_b (different count and data)
        result = process_official_census_records(batch_b, reference_date=ref_date)
        assert result["total_records"] == 5

        stored = OfficialCensusRecord.objects.filter(date=ref_date)
        assert stored.count() == 5, (
            "Should have exactly 5 records (batch_b), not the original 3"
        )

    def test_empty_records_clears_stale_rows(self):
        """Calling process with empty list should delete all rows for date."""
        ref_date = date(2026, 6, 1)
        batch = _make_records(4)

        # Pre-populate
        process_official_census_records(batch, reference_date=ref_date)
        assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 4

        # Call with empty records
        result = process_official_census_records([], reference_date=ref_date)
        assert result["total_records"] == 0

        # Verify stale rows are gone
        stored = OfficialCensusRecord.objects.filter(date=ref_date)
        assert stored.count() == 0, (
            "Empty records should clear all stale rows for the date"
        )

    def test_zero_records_is_valid_success(self):
        """Calling process with empty list on clean state returns success."""
        ref_date = date(2026, 6, 1)

        # No prior records exist for this date
        assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 0

        result = process_official_census_records([], reference_date=ref_date)
        assert result["total_records"] == 0
        assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 0

    def test_isolated_by_date_same_data_different_date_no_interference(self):
        """Records for different dates should not interfere with each other."""
        date_a = date(2026, 6, 1)
        date_b = date(2026, 6, 2)
        batch = _make_records(3)

        # Persist for date_a
        process_official_census_records(batch, reference_date=date_a)
        # Persist for date_b (same data)
        process_official_census_records(batch, reference_date=date_b)

        # Each date should have its own 3 records
        assert OfficialCensusRecord.objects.filter(date=date_a).count() == 3
        assert OfficialCensusRecord.objects.filter(date=date_b).count() == 3

        # Clear date_a with empty
        process_official_census_records([], reference_date=date_a)
        assert OfficialCensusRecord.objects.filter(date=date_a).count() == 0
        # date_b should still have its records
        assert OfficialCensusRecord.objects.filter(date=date_b).count() == 3

    def test_atomic_transaction_recovery(self):
        """If an error occurs mid-process, no partial state should persist.

        Strategy: use a mock that fails during bulk_create to simulate
        a mid-transaction failure, verifying that the delete is rolled back.
        """
        ref_date = date(2026, 6, 1)
        batch = _make_records(4)

        # Pre-populate to have something to roll back to
        process_official_census_records(batch, reference_date=ref_date)
        assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 4

        # Now patch bulk_create to raise, simulating mid-transaction failure
        with patch(
            "apps.census.services.OfficialCensusRecord.objects.bulk_create"
        ) as mock_bulk:
            mock_bulk.side_effect = RuntimeError("Simulated DB failure")

            with pytest.raises(RuntimeError, match="Simulated DB failure"):
                process_official_census_records(
                    _make_records(7), reference_date=ref_date
                )

        # The original 4 records should still be present (transaction rolled back)
        assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 4, (
            "Transaction should roll back on mid-process failure"
        )


# =========================================================================
# Integration tests: run_official_census_extraction idempotency
# =========================================================================


@pytest.mark.django_db
class TestServiceExtractionIdempotency:
    """Full service-level tests proving repeated extraction is deterministic."""

    @pytest.fixture(autouse=True)
    def _mock_credentials(self):
        """Patch resolve_source_credentials for every test in this class."""
        with patch(
            "apps.census.services.resolve_source_credentials"
        ) as mock:
            mock.return_value.url = "https://example.com"
            mock.return_value.username = "admin"
            mock.return_value.password = "secret"
            yield mock

    def test_service_repeated_extraction_no_duplication(self):
        """Calling run_official_census_extraction twice results in one set."""
        date_str = "01/06/2026"
        ref_date = date(2026, 6, 1)

        with patch("apps.census.services.run_subprocess") as mock_sub:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            mock_sub.return_value = proc

            # First extraction
            with _mock_tempdir_and_glob(records_count=3):
                result1 = run_official_census_extraction(date=date_str)
            assert result1.success is True
            assert result1.metrics["total_records"] == 3

            # Second extraction with same data
            with _mock_tempdir_and_glob(records_count=3):
                result2 = run_official_census_extraction(date=date_str)
            assert result2.success is True
            assert result2.metrics["total_records"] == 3

        # Verify no duplication: exactly 3 rows, not 6
        stored = OfficialCensusRecord.objects.filter(date=ref_date)
        assert stored.count() == 3

        # Verify two separate IngestionRuns were created
        assert result1.ingestion_run_id != result2.ingestion_run_id
        runs = IngestionRun.objects.filter(
            intent="official_census_extraction"
        )
        assert runs.count() >= 2

    def test_service_empty_output_clears_stale_rows(self):
        """When no JSON is produced, existing records should be cleared."""
        date_str = "01/06/2026"
        ref_date = date(2026, 6, 1)

        with patch("apps.census.services.run_subprocess") as mock_sub:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            mock_sub.return_value = proc

            # First extraction populates 4 records
            with _mock_tempdir_and_glob(records_count=4):
                result1 = run_official_census_extraction(date=date_str)
            assert result1.success is True
            assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 4

            # Second extraction: no JSON files found → zero records
            real_dir = Path(tempfile_module.mkdtemp())
            try:
                with patch(
                    "apps.census.services.tempfile.TemporaryDirectory"
                ) as m_tmp:
                    m_tmp.return_value.__enter__.return_value = str(real_dir)
                    with patch("pathlib.Path.glob") as m_glob:
                        m_glob.return_value = []
                        result2 = run_official_census_extraction(
                            date=date_str
                        )
            finally:
                shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result2.success is True
        assert result2.metrics["total_records"] == 0

        # Stale rows from first extraction should be cleared
        stored = OfficialCensusRecord.objects.filter(date=ref_date)
        assert stored.count() == 0, (
            "Empty output should clear all stale rows for the date"
        )

    def test_service_persistence_failure_does_not_leave_partial_state(self):
        """If persistence fails, previously stored rows must be preserved.

        This tests the transactional integrity of the delete+insert pattern.
        """
        date_str = "01/06/2026"
        ref_date = date(2026, 6, 1)

        with patch("apps.census.services.run_subprocess") as mock_sub:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            mock_sub.return_value = proc

            # First extraction populates records
            with _mock_tempdir_and_glob(records_count=3):
                result1 = run_official_census_extraction(date=date_str)
            assert result1.success is True
            assert OfficialCensusRecord.objects.filter(date=ref_date).count() == 3

            # Second extraction: subprocess success but persistence fails
            with _mock_tempdir_and_glob(records_count=5):
                with patch(
                    "apps.census.services.process_official_census_records"
                ) as mock_process:
                    mock_process.side_effect = RuntimeError(
                        "Simulated persistence failure"
                    )
                    result2 = run_official_census_extraction(
                        date=date_str
                    )

        assert result2.success is False
        assert result2.failure_reason == "unexpected_exception"

        # The original 3 records should still be intact
        stored = OfficialCensusRecord.objects.filter(date=ref_date)
        assert stored.count() == 3, (
            "Persistence failure must not leave a partial or empty state"
        )
