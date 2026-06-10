"""Characterization tests for admission extraction service.

Slice S3 (tasks.md 3.1):
- Add characterization tests for extract_admissions service execution with
  mocked subprocess output.

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

from apps.admissions.services import run_admission_extraction
from apps.ingestion.historical_extraction import ExtractionResult
from apps.ingestion.models import IngestionRun

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_credentials():
    """Patch resolve_source_credentials to return valid creds."""
    with patch("apps.admissions.services.resolve_source_credentials") as mock:
        mock.return_value.url = "https://example.com"
        mock.return_value.username = "admin"
        mock.return_value.password = "secret"
        yield mock


@pytest.fixture
def mock_subprocess_success():
    """Patch run_subprocess to return success with empty output."""
    with patch("apps.admissions.services.run_subprocess") as mock:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        mock.return_value = proc
        yield mock


@pytest.fixture
def mock_subprocess_failure():
    """Patch run_subprocess to return non-zero exit."""
    with patch("apps.admissions.services.run_subprocess") as mock:
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        proc.stderr = "Source system unavailable"
        mock.return_value = proc
        yield mock


@pytest.fixture
def mock_subprocess_timeout():
    """Patch run_subprocess to raise SubprocessTimeoutError."""
    with patch("apps.admissions.services.run_subprocess") as mock:
        from apps.ingestion.extractors.subprocess_utils import (
            SubprocessTimeoutError,
        )
        mock.side_effect = SubprocessTimeoutError(
            cmd=["python", "script.py"], timeout=600, output="", stderr="Timed out"
        )
        yield mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admission_json(records_count: int = 3):
    """Create synthetic admission JSON data matching the automation output."""
    records = []
    for i in range(records_count):
        records.append(
            {
                "PRONTUARIO": f"PRT{i:04d}",
                "NOME": f"Paciente {i}",
                "DATA INTERNACAO": "01/06/2026",
                "LEITO": f"{i:02d}A",
            }
        )
    return {"records": records}


def _write_json(tmpdir_path: Path, data: dict, filename: str | None = None):
    """Write JSON data to a temp directory, returning the path."""
    filepath = tmpdir_path / (filename or "admissoes-2026-06-01.json")
    filepath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return filepath


@contextmanager
def _mock_tempdir_and_glob(records_count: int = 3):
    """Set up real temp dir with JSON, mock TemporaryDirectory and Path.glob.

    On enter, creates a real temp directory with ``records_count`` synthetic
    admission records and patches ``tempfile.TemporaryDirectory`` and
    ``pathlib.Path.glob`` so the service reads from that directory.

    Yields the real temp directory path. Cleanup happens on exit.
    """
    real_dir = Path(tempfile_module.mkdtemp())
    data = _make_admission_json(records_count)
    _write_json(real_dir, data)

    # Compute glob results BEFORE mocking pathlib.Path.glob
    json_files = sorted(
        real_dir.glob("admissoes-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    with patch("apps.admissions.services.tempfile.TemporaryDirectory") as m_tmp:
        m_tmp.return_value.__enter__.return_value = str(real_dir)
        with patch("pathlib.Path.glob") as m_glob:
            m_glob.return_value = json_files
            yield real_dir

    shutil.rmtree(str(real_dir), ignore_errors=True)


# =========================================================================
# Tests: Successful extraction
# =========================================================================


@pytest.mark.django_db
class TestSuccessfulAdmissionExtraction:
    """Happy path: extraction succeeds with various record counts."""

    def test_extracts_and_persists_records(self, mock_credentials, mock_subprocess_success):
        """Successful extraction with records returns success and persists data."""
        with _mock_tempdir_and_glob(records_count=5):
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )

        assert result.success is True
        assert result.extraction_type == "admission_extraction"
        assert result.target_start == date(2026, 6, 1)
        assert result.target_end == date(2026, 6, 1)
        assert result.metrics["total_records"] == 5
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "succeeded"
        assert run.intent == "admission_extraction"

        stages = list(run.stage_metrics.all())
        stage_names = [s.stage_name for s in stages]
        assert "admission_extraction" in stage_names
        assert "admission_persistence" in stage_names

    def test_extracts_zero_records(self, mock_credentials, mock_subprocess_success):
        """Empty JSON (no records) results in success with zero count."""
        with _mock_tempdir_and_glob(records_count=0):
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )

        assert result.success is True
        assert result.metrics["total_records"] == 0
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "succeeded"

    def test_no_json_file_means_zero_records(self, mock_credentials, mock_subprocess_success):
        """When no JSON file is found, treat as zero records (success)."""
        real_dir = Path(tempfile_module.mkdtemp())
        try:
            with patch("apps.admissions.services.tempfile.TemporaryDirectory") as m_tmp:
                m_tmp.return_value.__enter__.return_value = str(real_dir)
                with patch("pathlib.Path.glob") as m_glob:
                    m_glob.return_value = []
                    result = run_admission_extraction(
                        start_date="01/06/2026",
                        end_date="01/06/2026",
                    )
        finally:
            shutil.rmtree(str(real_dir), ignore_errors=True)

        assert result.success is True
        assert result.metrics["total_records"] == 0
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "succeeded"

    def test_preserves_existing_cli_date_format(self, mock_credentials, mock_subprocess_success):
        """DD/MM/AAAA format works the same as when called from CLI."""
        with _mock_tempdir_and_glob(records_count=2):
            result = run_admission_extraction(
                start_date="15/05/2026",
                end_date="15/05/2026",
            )

        assert result.success is True
        assert result.target_start == date(2026, 5, 15)
        assert result.metrics["total_records"] == 2


# =========================================================================
# Tests: Failure modes
# =========================================================================


@pytest.mark.django_db
class TestFailedAdmissionExtraction:
    """Unhappy path: various failure modes produce correct ExtractionResult."""

    def test_missing_credentials(self):
        """Missing credentials should fail with validation_error."""
        with patch("apps.admissions.services.resolve_source_credentials") as mock:
            mock.side_effect = ValueError("Missing SOURCE_SYSTEM_URL")
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )

        assert result.success is False
        assert result.failure_reason == "validation_error"
        assert "SOURCE_SYSTEM_URL" in result.error_message

    def test_subprocess_timeout(self, mock_credentials, mock_subprocess_timeout):
        """Subprocess timeout should fail with timeout reason."""
        result = run_admission_extraction(
            start_date="01/06/2026",
            end_date="01/06/2026",
        )

        assert result.success is False
        assert result.failure_reason == "timeout"
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        assert run.timed_out is True
        assert run.failure_reason == "timeout"

    def test_subprocess_non_zero_exit(self, mock_credentials, mock_subprocess_failure):
        """Subprocess non-zero exit should fail with source_unavailable."""
        result = run_admission_extraction(
            start_date="01/06/2026",
            end_date="01/06/2026",
        )

        assert result.success is False
        assert result.failure_reason == "source_unavailable"
        assert result.ingestion_run_id is not None

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        assert run.failure_reason == "source_unavailable"

    def test_invalid_date_format(self, mock_credentials, mock_subprocess_success):
        """Invalid date string should fail with validation_error."""
        result = run_admission_extraction(
            start_date="not-a-date",
            end_date="not-a-date",
        )

        assert result.success is False
        assert result.failure_reason == "validation_error"
        assert "DD/MM/AAAA" in result.error_message

    def test_unexpected_exception_during_persistence(
        self, mock_credentials, mock_subprocess_success
    ):
        """If persistence raises, the service should capture it as unexpected_exception."""
        with patch("apps.admissions.services.process_admissions") as mock_process:
            mock_process.side_effect = RuntimeError("DB connection lost")
            with _mock_tempdir_and_glob(records_count=3):
                result = run_admission_extraction(
                    start_date="01/06/2026",
                    end_date="01/06/2026",
                )

        assert result.success is False
        assert result.failure_reason == "unexpected_exception"
        assert "DB connection lost" in result.error_message


# =========================================================================
# Tests: ExtractionResult contract compliance
# =========================================================================


@pytest.mark.django_db
class TestServiceReturnsExtractionResult:
    """The service must return an ExtractionResult in all cases."""

    def test_return_type_is_extraction_result(self):
        """Even with missing creds, the return type is ExtractionResult."""
        with patch("apps.admissions.services.resolve_source_credentials") as mock:
            mock.side_effect = ValueError("Missing credentials")
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )
        assert isinstance(result, ExtractionResult)

    def test_success_result_has_empty_failure_fields(
        self, mock_credentials, mock_subprocess_success
    ):
        """Successful results should have empty failure reason and error message."""
        with _mock_tempdir_and_glob(records_count=1):
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )
        assert result.success is True
        assert result.failure_reason == ""
        assert result.error_message == ""


# =========================================================================
# Tests: IngestionRun observability
# =========================================================================


@pytest.mark.django_db
class TestIngestionRunObservability:
    """Service execution must preserve IngestionRun lifecycle and stage metrics."""

    def test_stage_metrics_recorded_for_success(self, mock_credentials, mock_subprocess_success):
        """Successful extraction records extraction and persistence stages."""
        with _mock_tempdir_and_glob(records_count=3):
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stages = list(run.stage_metrics.all().order_by("started_at"))
        assert len(stages) == 2
        assert stages[0].stage_name == "admission_extraction"
        assert stages[0].status == "succeeded"
        assert stages[1].stage_name == "admission_persistence"
        assert stages[1].status == "succeeded"
        assert stages[1].details_json.get("total_records") == 3

    def test_stage_metrics_for_failed_extraction(self, mock_credentials, mock_subprocess_failure):
        """Failed extraction records a failed extraction stage."""
        result = run_admission_extraction(
            start_date="01/06/2026",
            end_date="01/06/2026",
        )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stages = list(run.stage_metrics.all().order_by("started_at"))
        assert len(stages) >= 1
        assert stages[0].stage_name == "admission_extraction"
        assert stages[0].status == "failed"

    def test_ingestion_run_parameters(self, mock_credentials, mock_subprocess_success):
        """The IngestionRun stores the extraction parameters."""
        with _mock_tempdir_and_glob(records_count=2):
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.parameters_json["start_date"] == "01/06/2026"
        assert run.parameters_json["end_date"] == "01/06/2026"

    def test_run_uses_proper_intent(self, mock_credentials, mock_subprocess_success):
        """The IngestionRun intent should be admission_extraction."""
        with _mock_tempdir_and_glob(records_count=1):
            result = run_admission_extraction(
                start_date="01/06/2026",
                end_date="01/06/2026",
            )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.intent == "admission_extraction"

    def test_error_stage_metric_does_not_contain_credentials(
        self, mock_credentials, mock_subprocess_failure
    ):
        """Error details in stage metrics must not expose credentials."""
        result = run_admission_extraction(
            start_date="01/06/2026",
            end_date="01/06/2026",
        )

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stages = list(run.stage_metrics.all())
        for stage in stages:
            details_str = json.dumps(stage.details_json)
            assert "secret" not in details_str
        assert "secret" not in run.error_message
