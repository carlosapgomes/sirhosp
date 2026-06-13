"""Characterization tests for discharge extraction service.

Slice C2-S3 (tasks.md 3.1-3.4):
- Add characterization tests for discharge service execution with
  mocked subprocess output and synthetic XLS data.
- Verify XLS row parsing behavior and report persistence semantics.
- Verify management command delegates to service.

These tests mock the subprocess layer and file I/O so the service logic can
be verified without a real Playwright automation script or source system.
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

from apps.discharges.models import DailyDischargeCount, DischargeRecord

# ---------------------------------------------------------------------------
# Synthetic XLS helpers
# ---------------------------------------------------------------------------


def _make_discharge_xls_rows(records_count: int = 3) -> list[tuple]:
    """Create synthetic XLS row tuples matching the expected column layout.

    Column layout (0-indexed):
      A(0): JSF internal ID (ignored)
      B(1): Prontuario (float)
      C(2): Nome
      D(3): Internacao (DD/MM/YYYY)
      E(4): Equipe (ignored)
      F(5): Esp
      G(6): Alta Medica (DD/MM/YYYY HH:MM)
      H(7): Local (L:UN08H or U:0 T)
      I(8): Saida (DD/MM/YYYY HH:MM)
    """
    rows: list[tuple] = [
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
        alta = f"{(1 + i):02d}/06/2026 10:0{i}"
        local = f"L:UN0{i}H"
        saida = f"{(1 + i):02d}/06/2026 12:0{i}"
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


# ---------------------------------------------------------------------------
# Context manager helpers
# ---------------------------------------------------------------------------


@contextmanager
def _mock_tempdir_and_xls(records_count: int = 3):
    """Set up real temp dir with XLS, mock TemporaryDirectory and Path.glob.

    On enter, creates a real temp directory with ``records_count`` synthetic
    discharge XLS rows and patches ``tempfile.TemporaryDirectory`` and
    ``pathlib.Path.glob`` so the service reads from that directory.

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
            m_glob.return_value = xls_files  # type: ignore[arg-type]
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
def mock_subprocess_failure():
    """Patch run_subprocess to return non-zero exit."""
    with patch("apps.discharges.extraction_service.run_subprocess") as mock:
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "Source system unavailable"
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
# Tests: Parser helpers
# =========================================================================


class TestParseXlsRow:
    """Unit tests for the XLS row parser."""

    def test_parses_valid_row(self):
        from apps.discharges.extraction_service import _parse_xls_row
        row = (
            0, 100001.0, "João", "01/06/2026", "EqA", "CLI",
            "01/06/2026 10:30", "L:UN03H", "01/06/2026 12:00",
        )
        result = _parse_xls_row(row)
        assert result is not None
        assert result["prontuario"] == "100001"
        assert result["nome"] == "João"
        assert result["data_internacao"] == "01/06/2026"
        assert result["especialidade"] == "CLI"
        assert result["leito"] == "UN03H"
        assert result["alta_em"] is not None
        assert result["saida_em"] is not None

    def test_returns_none_for_short_row(self):
        from apps.discharges.extraction_service import _parse_xls_row
        assert _parse_xls_row((1,)) is None

    def test_returns_none_for_missing_prontuario(self):
        from apps.discharges.extraction_service import _parse_xls_row
        row = (0, None, "Nome", "01/06/2026", "Eq", "CLI", "01/06/2026 10:30", "L:UN03H", "")
        assert _parse_xls_row(row) is None

    def test_parses_unit_local_as_empty_leito(self):
        from apps.discharges.extraction_service import _parse_xls_row
        row = (0, 100001.0, "Nome", "01/06/2026", "Eq", "CLI", "01/06/2026 10:30", "U:0 T", "")
        result = _parse_xls_row(row)
        assert result is not None
        assert result["leito"] == ""

    def test_parses_prontuario_as_string_when_not_float(self):
        from apps.discharges.extraction_service import _parse_xls_row
        row = (0, "ABC123", "Nome", "01/06/2026", "Eq", "CLI", "01/06/2026 10:30", "L:UN03H", "")
        result = _parse_xls_row(row)
        assert result is not None
        assert result["prontuario"] == "ABC123"


# =========================================================================
# Tests: Successful extraction
# =========================================================================


@pytest.mark.django_db
class TestSuccessfulDischargeExtraction:
    """Happy path: extraction succeeds with various record counts."""

    def test_extracts_and_persists_records(self, mock_credentials, mock_subprocess_success):
        """Successful extraction with records returns success and persists data."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with _mock_tempdir_and_xls(records_count=5):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert result.extraction_type == "discharge_extraction"
        assert result.target_start == date(2026, 6, 1)
        assert result.target_end == date(2026, 6, 1)
        assert result.metrics["total_records"] == 5
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "succeeded"
        assert run.intent == "discharge_extraction"

        stages = list(run.stage_metrics.all())
        stage_names = [s.stage_name for s in stages]
        assert "discharge_extraction" in stage_names
        assert "discharge_persistence" in stage_names

        # Verify persisted DailyDischargeCount
        ddc = DailyDischargeCount.objects.get(date=date(2026, 6, 1))
        assert ddc.count == 5
        assert len(ddc.raw_data) == 5

        # Verify persisted DischargeRecord rows
        records = DischargeRecord.objects.all()
        assert len(records) == 5
        assert records.filter(prontuario="100000").exists()
        assert records.filter(prontuario="100004").exists()

    def test_extracts_zero_records(self, mock_credentials, mock_subprocess_success):
        """Empty XLS (only header) results in success with zero count."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with _mock_tempdir_and_xls(records_count=0):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert result.metrics["total_records"] == 0
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "succeeded"

        ddc = DailyDischargeCount.objects.get(date=date(2026, 6, 1))
        assert ddc.count == 0
        assert ddc.raw_data == []

    def test_no_xls_file_means_zero_records(self, mock_credentials, mock_subprocess_success):
        """When no XLS file is found, treat as zero records (success)."""
        from apps.discharges.extraction_service import run_discharge_extraction

        real_dir = Path(tempfile_module.mkdtemp())
        try:
            with patch("apps.discharges.extraction_service.tempfile.TemporaryDirectory") as m_tmp:
                m_tmp.return_value.__enter__.return_value = str(real_dir)
                with patch("pathlib.Path.glob") as m_glob:
                    m_glob.return_value = []
                    result = run_discharge_extraction(
                        date="01/06/2026",
                    )
        finally:
            shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result.success is True
        assert result.metrics["total_records"] == 0
        ddc = DailyDischargeCount.objects.get(date=date(2026, 6, 1))
        assert ddc.count == 0

    def test_preserves_existing_records_for_different_date(  # noqa: E501
        self, mock_credentials, mock_subprocess_success,
    ):
        """Extracting for different dates preserves both sets."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with _mock_tempdir_and_xls(records_count=3):
            result = run_discharge_extraction(date="01/06/2026")
        assert result.success is True
        assert result.metrics["total_records"] == 3

        # Second date with no XLS files found should result in zero records
        real_dir = Path(tempfile_module.mkdtemp())
        try:
            with patch("apps.discharges.extraction_service.tempfile.TemporaryDirectory") as m_tmp:
                m_tmp.return_value.__enter__.return_value = str(real_dir)
                with patch("pathlib.Path.glob") as m_glob:
                    # Return empty list — no matches for altas-02-06-2026-*
                    m_glob.return_value = []
                    result2 = run_discharge_extraction(date="02/06/2026")
        finally:
            shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result2.success is True
        assert result2.metrics["total_records"] == 0

        # DailyDischargeCount: 3 from first run (one per alta_em date), 0 new from second (no XLS)
        assert DailyDischargeCount.objects.count() == 3
        assert DischargeRecord.objects.count() == 3  # only from first date


# =========================================================================
# Tests: Failure modes
# =========================================================================


@pytest.mark.django_db
class TestDischargeExtractionFailures:
    """Failure modes: invalid dates, missing credentials, subprocess failures."""

    def test_invalid_date_format_returns_validation_error(  # noqa: E501
        self, mock_credentials, mock_subprocess_success,
    ):
        """Invalid date returns structured failure."""
        from apps.discharges.extraction_service import run_discharge_extraction

        result = run_discharge_extraction(date="not-a-date")
        assert result.success is False
        assert result.failure_reason == "validation_error"
        assert "Invalid date format" in result.error_message
        assert result.ingestion_run_id is None

    def test_missing_credentials_returns_validation_error(self):
        """Missing credentials returns structured failure."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with patch(
            "apps.discharges.extraction_service.resolve_source_credentials",
            side_effect=ValueError("Missing source system credential(s): SOURCE_SYSTEM_URL"),
        ):
            result = run_discharge_extraction(date="01/06/2026")
        assert result.success is False
        assert result.failure_reason == "validation_error"
        assert "Missing source system credential" in result.error_message
        assert result.ingestion_run_id is None

    def test_subprocess_failure_returns_source_unavailable(  # noqa: E501
        self, mock_credentials, mock_subprocess_failure,
    ):
        """Non-zero subprocess exit returns structured failure."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        result = run_discharge_extraction(date="01/06/2026")
        assert result.success is False
        assert result.failure_reason == "source_unavailable"
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        assert run.failure_reason == "source_unavailable"

    def test_subprocess_timeout_returns_timeout(self, mock_credentials, mock_subprocess_timeout):
        """Timeout subprocess returns structured failure with timeout reason."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        result = run_discharge_extraction(date="01/06/2026")
        assert result.success is False
        assert result.failure_reason == "timeout"
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True
        # Credentials must not appear in error message
        assert "https://" not in result.error_message
        assert "admin" not in result.error_message
        assert "secret" not in result.error_message
        assert "example.com" not in result.error_message

    def test_unexpected_subprocess_exception_returns_failure(self, mock_credentials):
        """Unexpected exception during subprocess returns structured failure."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch("apps.discharges.extraction_service.run_subprocess") as mock:
            mock.side_effect = RuntimeError("Unexpected crash")

            result = run_discharge_extraction(date="01/06/2026")
        assert result.success is False
        assert result.failure_reason == "unexpected_exception"
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        assert run.failure_reason == "unexpected_exception"

    def test_outer_exception_marks_run_as_failed(self, mock_credentials, mock_subprocess_success):
        """The outer fallback except must mark the IngestionRun as failed.

        If an unexpected exception occurs after the run is created but the
        inner handlers miss it, the outer fallback must not leave the run
        as ``running``.
        """
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        real_dir = Path(tempfile_module.mkdtemp())
        try:
            with patch(
                "apps.discharges.extraction_service.tempfile.TemporaryDirectory"
            ) as m_tmp:
                m_tmp.return_value.__enter__.return_value = str(real_dir)
                with patch("pathlib.Path.glob") as m_glob:
                    m_glob.side_effect = OSError("Disk full")
                    result = run_discharge_extraction(
                        date="01/06/2026",
                    )
        finally:
            shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result.success is False
        assert result.failure_reason == "unexpected_exception"
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed", (
            "Outer exception must mark the run as failed, not leave it running"
        )
        assert run.failure_reason == "unexpected_exception"


# =========================================================================
# Tests: IngestionRun observability
# =========================================================================


@pytest.mark.django_db
class TestDischargeIngestionRunObservability:
    """Service execution must preserve IngestionRun lifecycle and stage metrics."""

    def test_stage_metrics_recorded_for_success(
        self, mock_credentials, mock_subprocess_success,
    ):
        """Successful extraction records extraction and persistence stages."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with _mock_tempdir_and_xls(records_count=3):
            result = run_discharge_extraction(
                date="01/06/2026",
            )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stages = list(
            run.stage_metrics.all().order_by("started_at")
        )
        assert len(stages) == 2
        assert stages[0].stage_name == "discharge_extraction"
        assert stages[0].status == "succeeded"
        assert stages[1].stage_name == "discharge_persistence"
        assert stages[1].status == "succeeded"
        assert stages[1].details_json.get("total_records") == 3

    def test_stage_metrics_for_failed_extraction(
        self, mock_credentials, mock_subprocess_failure,
    ):
        """Failed extraction records a failed extraction stage."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        result = run_discharge_extraction(
            date="01/06/2026",
        )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stages = list(
            run.stage_metrics.all().order_by("started_at")
        )
        assert len(stages) >= 1
        assert stages[0].stage_name == "discharge_extraction"
        assert stages[0].status == "failed"

    def test_ingestion_run_parameters(
        self, mock_credentials, mock_subprocess_success,
    ):
        """The IngestionRun stores the extraction parameters."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with _mock_tempdir_and_xls(records_count=2):
            result = run_discharge_extraction(
                date="01/06/2026",
            )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.parameters_json["date"] == "01/06/2026"

    def test_run_uses_proper_intent(
        self, mock_credentials, mock_subprocess_success,
    ):
        """The IngestionRun intent should be discharge_extraction."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with _mock_tempdir_and_xls(records_count=1):
            result = run_discharge_extraction(
                date="01/06/2026",
            )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.intent == "discharge_extraction"

    def test_error_stage_metric_does_not_contain_credentials(
        self, mock_credentials, mock_subprocess_failure,
    ):
        """Error details in stage metrics must not expose credentials."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        result = run_discharge_extraction(
            date="01/06/2026",
        )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stages = list(run.stage_metrics.all())
        for stage in stages:
            details_str = json.dumps(stage.details_json)
            assert "secret" not in details_str
        assert "secret" not in run.error_message


# =========================================================================
# Tests: Persistence semantics
# =========================================================================


@pytest.mark.django_db
class TestDischargePersistenceSemantics:
    """Preserve existing upsert and update semantics."""

    def test_upsert_updates_existing_record(self, mock_credentials, mock_subprocess_success):
        """Re-running with changed data updates existing records."""
        from apps.discharges.extraction_service import run_discharge_extraction

        # First run with initial data
        with _mock_tempdir_and_xls(records_count=3):
            result1 = run_discharge_extraction(date="01/06/2026")
        assert result1.success is True
        assert result1.metrics["total_records"] == 3
        assert result1.metrics["updated"] == 0
        assert result1.metrics["created"] == 3

        # Second run with same data — should find existing and update
        with _mock_tempdir_and_xls(records_count=3):
            result2 = run_discharge_extraction(date="01/06/2026")
        assert result2.success is True
        assert result2.metrics["created"] == 0  # no new records
        assert DischargeRecord.objects.count() == 3  # no duplicates

    def test_created_and_updated_counts(self, mock_credentials, mock_subprocess_success):
        """Metrics report correct created/updated counts."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with _mock_tempdir_and_xls(records_count=3):
            result = run_discharge_extraction(date="01/06/2026")
        assert result.metrics["created"] == 3
        assert result.metrics["updated"] == 0


# =========================================================================
# Tests: Management command wrapper
# =========================================================================


@pytest.mark.django_db
class TestExtractDischargesCommand:
    """Verify the management command delegates to the service."""

    def test_command_imports_service_function(self):
        """The command module imports run_discharge_extraction from service."""
        from apps.discharges.management.commands import extract_discharges  # noqa: PLC0415
        assert hasattr(extract_discharges, "run_discharge_extraction") or \
            "run_discharge_extraction" in dir(extract_discharges)

    def test_command_delegates_to_service_and_reports_success(  # noqa: E501
        self, mock_credentials, mock_subprocess_success,
    ):
        """Command delegates to service and reports success."""
        from apps.discharges.management.commands.extract_discharges import Command  # noqa: PLC0415

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd.style = MagicMock()
        cmd.style.SUCCESS = MagicMock(side_effect=lambda x: x)

        with _mock_tempdir_and_xls(records_count=5):
            cmd.handle(headless=True, date="01/06/2026")

        cmd.stdout.write.assert_called()
        # Should have called style.SUCCESS at least once for success message
        assert cmd.style.SUCCESS.call_count >= 1

    def test_command_exits_on_failure(self, mock_credentials, mock_subprocess_failure):
        """Command exits with code 1 on failure."""
        from apps.discharges.management.commands.extract_discharges import Command  # noqa: PLC0415

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd.style = MagicMock()

        with pytest.raises(SystemExit) as exc:
            cmd.handle(headless=True, date="01/06/2026")
        assert exc.value.code == 1
