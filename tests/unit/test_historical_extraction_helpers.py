"""Tests for shared historical extraction helper functions.

Slice S2 requirements (tasks.md 2.1):
- Add tests for shared helper behavior including safe credential resolution
  and IngestionRun stage/failure recording.

These helpers interact with Django models (IngestionRun,
IngestionRunStageMetric) and settings, so tests requiring the database
are marked with @pytest.mark.django_db.
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pytest
from django.utils import timezone as django_timezone

from apps.ingestion.historical_extraction import (
    ExtractionResult,
    SourceCredentials,
    create_stage_metric,
    mark_run_failed,
    mark_run_succeeded,
    resolve_source_credentials,
    safe_error_message,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric

# ---------------------------------------------------------------------------
# SourceCredentials
# ---------------------------------------------------------------------------


class TestSourceCredentials:
    """SourceCredentials is a simple dataclass for credential transport."""

    def test_has_url_username_password_fields(self):
        creds = SourceCredentials(url="http://example.com", username="user", password="pass")
        assert creds.url == "http://example.com"
        assert creds.username == "user"
        assert creds.password == "pass"

    def test_is_dataclass(self):
        creds = SourceCredentials(url="", username="", password="")
        assert hasattr(creds, "__dataclass_fields__")

    def test_repr_does_not_include_password(self):
        """Password must be excluded from repr to prevent log exposure."""
        creds = SourceCredentials(
            url="https://example.com",
            username="admin",
            password="super-secret-123",
        )
        rep = repr(creds)
        # With repr=False, neither the field name nor the value appears
        assert "password" not in rep
        assert "super-secret-123" not in rep
        # password field should still be accessible directly
        assert creds.password == "super-secret-123"

    def test_repr_does_not_include_password_empty(self):
        """Even with empty password, it should not appear in repr."""
        creds = SourceCredentials(url="", username="", password="")
        # Empty string is always a substring, so check for the field name instead
        assert "password" not in repr(creds)

    def test_repr_includes_url_and_username(self):
        """repr should include non-sensitive fields for debugging."""
        creds = SourceCredentials(
            url="https://example.com",
            username="admin",
            password="secret",
        )
        rep = repr(creds)
        assert "https://example.com" in rep
        assert "admin" in rep
        assert "SourceCredentials" in rep


# ---------------------------------------------------------------------------
# resolve_source_credentials
# ---------------------------------------------------------------------------


class TestResolveSourceCredentials:
    """resolve_source_credentials reads from settings or env."""

    @patch("apps.ingestion.historical_extraction.django_settings")
    def test_returns_creds_from_settings(self, mock_settings):
        mock_settings.SOURCE_SYSTEM_URL = "https://example.com"
        mock_settings.SOURCE_SYSTEM_USERNAME = "admin"
        mock_settings.SOURCE_SYSTEM_PASSWORD = "secret"

        creds = resolve_source_credentials()

        assert creds.url == "https://example.com"
        assert creds.username == "admin"
        assert creds.password == "secret"

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.ingestion.historical_extraction.django_settings")
    def test_falls_back_to_env_when_settings_empty(self, mock_settings):
        """When settings attrs are empty strings, fall back to env."""
        mock_settings.SOURCE_SYSTEM_URL = ""
        mock_settings.SOURCE_SYSTEM_USERNAME = ""
        mock_settings.SOURCE_SYSTEM_PASSWORD = ""

        with patch.dict(
            os.environ,
            {
                "SOURCE_SYSTEM_URL": "https://env.example.com",
                "SOURCE_SYSTEM_USERNAME": "env_user",
                "SOURCE_SYSTEM_PASSWORD": "env_pass",
            },
            clear=True,
        ):
            creds = resolve_source_credentials()

        assert creds.url == "https://env.example.com"
        assert creds.username == "env_user"
        assert creds.password == "env_pass"

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.ingestion.historical_extraction.django_settings")
    def test_raises_value_error_when_url_missing(self, mock_settings):
        mock_settings.SOURCE_SYSTEM_URL = ""
        mock_settings.SOURCE_SYSTEM_USERNAME = "admin"
        mock_settings.SOURCE_SYSTEM_PASSWORD = "secret"

        with pytest.raises(ValueError, match="SOURCE_SYSTEM_URL"):
            resolve_source_credentials()

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.ingestion.historical_extraction.django_settings")
    def test_raises_value_error_when_username_missing(self, mock_settings):
        mock_settings.SOURCE_SYSTEM_URL = "https://example.com"
        mock_settings.SOURCE_SYSTEM_USERNAME = ""
        mock_settings.SOURCE_SYSTEM_PASSWORD = "secret"

        with pytest.raises(ValueError, match="SOURCE_SYSTEM_USERNAME"):
            resolve_source_credentials()

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.ingestion.historical_extraction.django_settings")
    def test_raises_value_error_when_password_missing(self, mock_settings):
        mock_settings.SOURCE_SYSTEM_URL = "https://example.com"
        mock_settings.SOURCE_SYSTEM_USERNAME = "admin"
        mock_settings.SOURCE_SYSTEM_PASSWORD = ""

        with pytest.raises(ValueError, match="SOURCE_SYSTEM_PASSWORD"):
            resolve_source_credentials()

    @patch.dict(os.environ, {}, clear=True)
    @patch("apps.ingestion.historical_extraction.django_settings")
    def test_raises_value_error_when_all_missing(self, mock_settings):
        mock_settings.SOURCE_SYSTEM_URL = ""
        mock_settings.SOURCE_SYSTEM_USERNAME = ""
        mock_settings.SOURCE_SYSTEM_PASSWORD = ""

        with pytest.raises(ValueError, match="SOURCE_SYSTEM_URL"):
            resolve_source_credentials()


# ---------------------------------------------------------------------------
# create_stage_metric
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateStageMetric:
    """create_stage_metric creates an IngestionRunStageMetric row."""

    def test_creates_stage_with_minimal_args(self):
        run = IngestionRun.objects.create(status="running")
        now = django_timezone.now()

        metric = create_stage_metric(
            run=run,
            stage_name="data_extraction",
            status="succeeded",
            started_at=now,
        )

        assert isinstance(metric, IngestionRunStageMetric)
        assert metric.run_id == run.pk
        assert metric.stage_name == "data_extraction"
        assert metric.status == "succeeded"
        assert metric.started_at == now
        assert metric.finished_at is not None  # defaults to now
        assert metric.details_json == {}

    def test_creates_stage_with_explicit_finished_at(self):
        run = IngestionRun.objects.create(status="running")
        start = django_timezone.now()
        finish = django_timezone.now()
        metric = create_stage_metric(
            run=run,
            stage_name="data_persistence",
            status="failed",
            started_at=start,
            finished_at=finish,
        )

        assert metric.finished_at == finish

    def test_creates_stage_with_details_json(self):
        run = IngestionRun.objects.create(status="running")
        now = django_timezone.now()
        details = {"records_processed": 42, "errors": []}

        metric = create_stage_metric(
            run=run,
            stage_name="data_persistence",
            status="succeeded",
            started_at=now,
            details_json=details,
        )

        assert metric.details_json == details

    def test_stage_is_persisted(self):
        run = IngestionRun.objects.create(status="running")
        now = django_timezone.now()

        metric = create_stage_metric(
            run=run,
            stage_name="data_extraction",
            status="succeeded",
            started_at=now,
        )
        pk = metric.pk

        # Reload from DB
        reloaded = IngestionRunStageMetric.objects.get(pk=pk)
        assert reloaded.stage_name == "data_extraction"
        assert reloaded.status == "succeeded"

    def test_stage_is_linked_to_run(self):
        run = IngestionRun.objects.create(status="running")
        now = django_timezone.now()

        metric = create_stage_metric(
            run=run,
            stage_name="phase_one",
            status="succeeded",
            started_at=now,
        )

        assert metric.run_id == run.pk
        # Verify reverse relation
        assert list(run.stage_metrics.all()) == [metric]


# ---------------------------------------------------------------------------
# mark_run_succeeded
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarkRunSucceeded:
    """mark_run_succeeded transitions an IngestionRun to succeeded."""

    def test_sets_status_to_succeeded(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_succeeded(run)

        assert run.status == "succeeded"

    def test_sets_finished_at(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_succeeded(run)

        assert run.finished_at is not None

    def test_preserves_error_message(self):
        run = IngestionRun.objects.create(status="running", error_message="previous")
        mark_run_succeeded(run)
        run.refresh_from_db()
        # succeeded runs keep whatever error_message was there
        assert run.error_message == "previous"

    def test_persists_to_db(self):
        run = IngestionRun.objects.create(status="running")
        pk = run.pk

        mark_run_succeeded(run)

        reloaded = IngestionRun.objects.get(pk=pk)
        assert reloaded.status == "succeeded"
        assert reloaded.finished_at is not None


# ---------------------------------------------------------------------------
# mark_run_failed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarkRunFailed:
    """mark_run_failed transitions an IngestionRun to failed."""

    def test_sets_status_to_failed(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Something broke")

        assert run.status == "failed"

    def test_sets_error_message(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Connection refused")

        assert run.error_message == "Connection refused"

    def test_sets_finished_at(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Timeout")

        assert run.finished_at is not None

    def test_defaults_failure_reason_to_empty(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Error")

        assert run.failure_reason == ""

    def test_accepts_failure_reason(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Timeout", failure_reason="timeout")

        assert run.failure_reason == "timeout"

    def test_accepts_timed_out(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(
            run,
            error_message="Timed out",
            failure_reason="timeout",
            timed_out=True,
        )

        assert run.timed_out is True

    def test_defaults_timed_out_to_false(self):
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Error")

        assert run.timed_out is False

    def test_safe_error_message_uses_default_truncation(self):
        """The default error_message argument is short."""
        run = IngestionRun.objects.create(status="running")

        mark_run_failed(run, error_message="Short error")

        assert "\n" not in run.error_message  # single line

    def test_persists_to_db(self):
        run = IngestionRun.objects.create(status="running")
        pk = run.pk

        mark_run_failed(
            run,
            error_message="Failure",
            failure_reason="source_unavailable",
        )

        reloaded = IngestionRun.objects.get(pk=pk)
        assert reloaded.status == "failed"
        assert reloaded.error_message == "Failure"
        assert reloaded.failure_reason == "source_unavailable"
        assert reloaded.finished_at is not None


# ---------------------------------------------------------------------------
# safe_error_message
# ---------------------------------------------------------------------------


class TestSafeErrorMessage:
    """safe_error_message truncates and sanitizes error messages."""

    def test_short_message_passes_through(self):
        result = safe_error_message("Short error")
        assert result == "Short error"

    def test_long_message_is_truncated(self):
        long_msg = "x" * 1000
        result = safe_error_message(long_msg)
        # max_length=500 → keep 497 + "..." = 500 total
        assert len(result) == 500
        assert result == "x" * 497 + "..."

    def test_custom_max_length(self):
        msg = "a" * 100
        result = safe_error_message(msg, max_length=10)
        assert len(result) == 10
        assert result == "aaaaaaa..."  # 7 chars + "..." = 10

    def test_max_length_exactly_fits_message(self):
        """Message exactly max_length long is not truncated."""
        msg = "abc"
        result = safe_error_message(msg, max_length=3)
        assert result == "abc"
        assert len(result) == 3

    def test_max_length_three_uses_ellipsis_only(self):
        """A 4-char message with max_length=3 is truncated to '...' (3 chars)."""
        result = safe_error_message("abcd", max_length=3)
        assert result == "..."
        assert len(result) == 3

    def test_max_length_two_no_ellipsis(self):
        """When max_length < 3, ellipsis does not fit; return truncated without it."""
        result = safe_error_message("abcdef", max_length=2)
        assert result == "ab"
        assert len(result) == 2

    def test_max_length_one_no_ellipsis(self):
        result = safe_error_message("abcdef", max_length=1)
        assert result == "a"
        assert len(result) == 1

    def test_max_length_zero_returns_empty(self):
        result = safe_error_message("abcdef", max_length=0)
        assert result == ""
        assert len(result) == 0

    def test_empty_message_returns_empty(self):
        assert safe_error_message("") == ""

    def test_message_shorter_than_max_length_is_not_truncated(self):
        msg = "Hello, world!"
        result = safe_error_message(msg, max_length=500)
        assert result == "Hello, world!"

    def test_none_message_returns_empty_string(self):
        assert safe_error_message(None) == ""


# ---------------------------------------------------------------------------
# Integration: helpers preserve ExtractionResult contract
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHelpersExtractionResultIntegration:
    """Helpers should be usable together to produce an ExtractionResult."""

    def test_success_flow_produces_result(self):
        run = IngestionRun.objects.create(
            status="running",
            intent="admission_extraction",
            parameters_json={"start_date": "01/06/2026", "end_date": "01/06/2026"},
        )
        now = django_timezone.now()

        create_stage_metric(
            run=run,
            stage_name="admission_extraction",
            status="succeeded",
            started_at=now,
        )
        create_stage_metric(
            run=run,
            stage_name="admission_persistence",
            status="succeeded",
            started_at=now,
            details_json={"total_records": 5},
        )
        mark_run_succeeded(run)

        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
            metrics={"total_records": 5},
            ingestion_run_id=run.pk,
        )

        assert result.success is True
        assert result.metrics["total_records"] == 5
        assert result.ingestion_run_id == run.pk

        # Verify DB state
        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.stage_metrics.count() == 2

    def test_failure_flow_produces_result(self):
        run = IngestionRun.objects.create(
            status="running",
            intent="death_extraction",
            parameters_json={"start_date": "01/06/2026", "end_date": "01/06/2026"},
        )
        now = django_timezone.now()

        create_stage_metric(
            run=run,
            stage_name="death_extraction",
            status="failed",
            started_at=now,
            details_json={"error": "Connection refused"},
        )
        mark_run_failed(
            run,
            error_message="Connection refused",
            failure_reason="source_unavailable",
        )

        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="source_unavailable",
            error_message="Connection refused",
            ingestion_run_id=run.pk,
        )

        assert result.success is False
        assert result.failure_reason == "source_unavailable"
        assert result.ingestion_run_id == run.pk

        # Verify DB state
        run.refresh_from_db()
        assert run.status == "failed"
        assert run.error_message == "Connection refused"
        assert run.failure_reason == "source_unavailable"
        assert run.stage_metrics.count() == 1
