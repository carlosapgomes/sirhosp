"""RPAP-S5 unit tests: one-shot aggregate ingestion pipeline health check.

Covers the vertical slice requirements:

- R1: window/settling/threshold argument validation before any query;
- R2: batch-bound invariants (empty success, missing full-sync after
  settling, duplicate batch-owned demographics);
- R3: queue age and full-sync terminal failure rate with minimum sample;
- R4: optional freshness alarms with aggregate presence/age;
- R5: sanitized stdout/stderr/CommandError (no identifiers, no raw text);
- R6: read-only evaluation with zero external calls (spies).
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.census.models import CensusSnapshot, PatientMovement
from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)
from apps.patients.models import Admission, Patient

COMMAND_NAME = "check_ingestion_pipeline_health"

pytestmark = pytest.mark.django_db

SENTINEL_PATIENT = "PRIV-PAT-S5-042"
SENTINEL_NAME = "PRIV-NOME-S5-FULANO"
SENTINEL_ADMISSION = "PRIV-ADM-S5-777"
SENTINEL_SECTOR = "PRIV-SETOR-S5-999"
SENTINEL_EVENT_KEY = "PRIV-EVT-S5-KEY"
SENTINEL_TEXT = "PRIV-TEXTO-CLINICO-S5"
SENTINEL_AUTHOR = "PRIV-AUTOR-S5"
SENTINEL_URL = "https://priv-sentinel-s5.invalid/x"
SENTINEL_ERROR = f"erro bruto {SENTINEL_URL} {SENTINEL_TEXT}"

_COUNTED_MODELS = (
    IngestionRun,
    CensusExecutionBatch,
    IngestionRunAttempt,
    FinalRunFailure,
    IngestionRunStageMetric,
    Patient,
    Admission,
    PatientMovement,
    ClinicalEvent,
    CensusSnapshot,
)


def _model_counts() -> dict[str, int]:
    return {model._meta.label: model.objects.count() for model in _COUNTED_MODELS}


def _minutes_ago(minutes: int):
    return timezone.now() - timedelta(minutes=minutes)


def _batch(status: str = "succeeded") -> CensusExecutionBatch:
    return CensusExecutionBatch.objects.create(status=status)


def _run(
    *,
    intent: str,
    status: str,
    batch: CensusExecutionBatch | None = None,
    patient_record: str = "PRIV-PAT-001",
    admissions_seen: int = 0,
    events_created: int = 0,
    finished_at=None,
    queued_at=None,
    failure_reason: str = "",
    error_message: str = "",
) -> IngestionRun:
    kwargs: dict[str, Any] = {
        "intent": intent,
        "status": status,
        "batch": batch,
        "admissions_seen": admissions_seen,
        "events_created": events_created,
        "failure_reason": failure_reason,
        "error_message": error_message,
        "parameters_json": {
            "patient_record": patient_record,
            "intent": intent,
        },
    }
    if finished_at is not None:
        kwargs["finished_at"] = finished_at
    if queued_at is not None:
        kwargs["queued_at"] = queued_at
    return IngestionRun.objects.create(**kwargs)


def _admissions_success(
    *,
    batch: CensusExecutionBatch,
    patient_record: str = "PRIV-PAT-001",
    admissions_seen: int = 2,
    finished_at=None,
) -> IngestionRun:
    return _run(
        intent="admissions_only",
        status="succeeded",
        batch=batch,
        patient_record=patient_record,
        admissions_seen=admissions_seen,
        finished_at=finished_at or _minutes_ago(90),
    )


def _full_sync(
    *,
    batch: CensusExecutionBatch,
    patient_record: str = "PRIV-PAT-001",
    intent: str = "full_sync",
    status: str = "succeeded",
    events_created: int = 0,
    finished_at=None,
    failure_reason: str = "",
    error_message: str = "",
) -> IngestionRun:
    return _run(
        intent=intent,
        status=status,
        batch=batch,
        patient_record=patient_record,
        events_created=events_created,
        finished_at=finished_at or _minutes_ago(60),
        failure_reason=failure_reason,
        error_message=error_message,
    )


def _demographics(
    *,
    batch: CensusExecutionBatch,
    patient_record: str = "PRIV-PAT-001",
    queued_at=None,
) -> IngestionRun:
    return _run(
        intent="demographics_only",
        status="queued",
        batch=batch,
        patient_record=patient_record,
        queued_at=queued_at or _minutes_ago(30),
    )


def _run_healthy(*args: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue()


def _run_unhealthy(*args: str) -> tuple[str, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises(CommandError) as exc:
        call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue(), str(exc.value)


class TestHealthyPipeline:
    def test_empty_database_returns_success_with_aggregate_counts(self):
        output = _run_healthy()
        assert "healthy=true" in output
        assert "empty_success=0" in output
        assert "missing_full_sync=0" in output
        assert "duplicate_demographics=0" in output
        assert "queue: active=0 oldest_age_minutes=0" in output
        assert "full_sync: terminal=0 succeeded=0 failed=0" in output
        assert "freshness: movement_present=false" in output


class TestEmptySuccessInvariant:
    def test_succeeded_batch_bound_empty_admissions_is_unhealthy(self):
        _admissions_success(batch=_batch(), admissions_seen=0, finished_at=_minutes_ago(5))
        out, _err, error = _run_unhealthy()
        assert "empty_success=1" in out
        assert "empty_success=1" in error
        assert "missing_full_sync=0" in out

    def test_standalone_empty_admissions_is_legitimate(self):
        _run(
            intent="admissions_only",
            status="succeeded",
            batch=None,
            admissions_seen=0,
            finished_at=_minutes_ago(5),
        )
        output = _run_healthy()
        assert "healthy=true" in output
        assert "empty_success=0" in output

    def test_non_empty_admissions_is_not_flagged_empty(self):
        batch = _batch()
        _admissions_success(batch=batch, admissions_seen=3)
        _full_sync(batch=batch)
        output = _run_healthy()
        assert "empty_success=0" in output

    def test_empty_success_outside_window_is_ignored(self):
        _admissions_success(
            batch=_batch(), admissions_seen=0, finished_at=_minutes_ago(30 * 60)
        )
        output = _run_healthy("--window-hours", "24")
        assert "healthy=true" in output
        assert "empty_success=0" in output


class TestMissingFullSyncInvariant:
    def test_missing_full_sync_after_settling_is_unhealthy(self):
        _admissions_success(batch=_batch(), finished_at=_minutes_ago(90))
        out, _err, error = _run_unhealthy("--settling-minutes", "30")
        assert "missing_full_sync=1" in out
        assert "missing_full_sync=1" in error

    def test_missing_full_sync_before_settling_is_ignored(self):
        _admissions_success(batch=_batch(), finished_at=_minutes_ago(10))
        output = _run_healthy("--settling-minutes", "30")
        assert "healthy=true" in output
        assert "missing_full_sync=0" in output

    def test_present_full_sync_same_batch_patient_is_healthy(self):
        batch = _batch()
        _admissions_success(batch=batch, finished_at=_minutes_ago(90))
        _full_sync(batch=batch)
        output = _run_healthy("--settling-minutes", "30")
        assert "healthy=true" in output

    def test_present_full_admission_sync_satisfies_invariant(self):
        batch = _batch()
        _admissions_success(batch=batch, finished_at=_minutes_ago(90))
        _full_sync(batch=batch, intent="full_admission_sync")
        output = _run_healthy("--settling-minutes", "30")
        assert "healthy=true" in output

    def test_full_sync_of_another_batch_does_not_satisfy(self):
        batch = _batch()
        _admissions_success(batch=batch, finished_at=_minutes_ago(90))
        _full_sync(batch=_batch())
        out, _err, _error = _run_unhealthy("--settling-minutes", "30")
        assert "missing_full_sync=1" in out

    def test_empty_admissions_does_not_trigger_missing_full_sync(self):
        batch = _batch()
        _admissions_success(batch=batch, admissions_seen=0, finished_at=_minutes_ago(90))
        out, _err, _error = _run_unhealthy("--settling-minutes", "30")
        assert "missing_full_sync=0" in out
        assert "empty_success=1" in out


class TestDuplicateDemographicsInvariant:
    def test_duplicate_demographics_same_batch_patient_unhealthy(self):
        batch = _batch()
        _demographics(batch=batch)
        _demographics(batch=batch)
        out, _err, error = _run_unhealthy()
        assert "duplicate_demographics=1" in out
        assert "duplicate_demographics=1" in error

    def test_single_demographics_per_batch_patient_healthy(self):
        batch = _batch()
        _demographics(batch=batch)
        output = _run_healthy()
        assert "healthy=true" in output

    def test_same_patient_in_different_batches_is_not_duplicate(self):
        _demographics(batch=_batch())
        _demographics(batch=_batch())
        output = _run_healthy()
        assert "healthy=true" in output

    def test_duplicate_demographics_outside_window_is_ignored(self):
        batch = _batch()
        for _ in range(2):
            _run(
                intent="demographics_only",
                status="succeeded",
                batch=batch,
                queued_at=_minutes_ago(30 * 60),
                finished_at=_minutes_ago(30 * 60 - 1),
            )
        output = _run_healthy("--window-hours", "24")
        assert "healthy=true" in output


class TestQueueAge:
    def test_queue_age_below_threshold_healthy(self):
        _run(intent="full_sync", status="queued", queued_at=_minutes_ago(10))
        output = _run_healthy("--max-active-age-minutes", "120")
        assert "healthy=true" in output
        assert "oldest_age_minutes=10" in output

    def test_queue_age_above_threshold_unhealthy(self):
        _run(intent="admissions_only", status="running", queued_at=_minutes_ago(200))
        out, _err, error = _run_unhealthy("--max-active-age-minutes", "120")
        assert "active_queue_age=1" in out
        assert "active_queue_age=1" in error

    def test_unsupported_intent_queue_is_ignored(self):
        _run(
            intent="census_extraction",
            status="queued",
            queued_at=_minutes_ago(300),
        )
        output = _run_healthy("--max-active-age-minutes", "120")
        assert "healthy=true" in output
        assert "queue: active=0" in output


class TestFullSyncFailureRate:
    def test_failure_rate_below_threshold_healthy(self):
        batch = _batch()
        for _ in range(9):
            _full_sync(batch=batch, events_created=1)
        _full_sync(batch=batch, status="failed", failure_reason="timeout")
        output = _run_healthy()
        assert "healthy=true" in output
        assert "failure_percent=10.0" in output

    def test_failure_rate_above_threshold_with_sample_unhealthy(self):
        batch = _batch()
        for _ in range(4):
            _full_sync(batch=batch)
        for reason in ("timeout", "timeout", "invalid_payload", "invalid_payload"):
            _full_sync(batch=batch, status="failed", failure_reason=reason)
        out, _err, error = _run_unhealthy(
            "--min-full-sync-terminal-sample", "5",
            "--max-full-sync-failure-percent", "20",
        )
        assert "full_sync_failure_rate=1" in out
        assert "full_sync_failure_rate=1" in error
        assert "failure_percent=50.0" in out

    def test_failure_rate_above_threshold_below_sample_is_informational(self):
        batch = _batch()
        _full_sync(batch=batch, status="failed", failure_reason="timeout")
        output = _run_healthy(
            "--min-full-sync-terminal-sample", "5",
            "--max-full-sync-failure-percent", "20",
        )
        assert "healthy=true" in output
        assert "failure_percent=100.0" in output

    def test_reasons_aggregated_and_events_created_summed(self):
        batch = _batch()
        for _ in range(2):
            _full_sync(batch=batch, events_created=5)
        _full_sync(batch=batch, status="failed", failure_reason="timeout")
        _full_sync(batch=batch, status="failed", failure_reason="timeout")
        _full_sync(batch=batch, status="failed", failure_reason="invalid_payload")
        output = _run_healthy("--min-full-sync-terminal-sample", "100")
        assert "events_created=10" in output
        assert "full_sync_failure_reasons: invalid_payload=1,timeout=2" in output

    def test_failed_run_without_reason_is_aggregated_as_none(self):
        batch = _batch()
        _full_sync(batch=batch, status="failed", failure_reason="")
        output = _run_healthy("--min-full-sync-terminal-sample", "100")
        assert "full_sync_failure_reasons: none=1" in output


class TestFreshness:
    def test_freshness_omitted_is_informational(self):
        patient = _patient_with_domain_rows(last_seen=_minutes_ago(30 * 24 * 60))
        assert patient is not None
        output = _run_healthy()
        assert "healthy=true" in output
        assert "movement_present=true" in output

    def test_freshness_threshold_healthy_when_recent(self):
        _patient_with_domain_rows(last_seen=_minutes_ago(60))
        output = _run_healthy(
            "--max-movement-age-hours", "24",
            "--max-admission-age-hours", "24",
            "--max-event-age-hours", "24",
        )
        assert "healthy=true" in output

    def test_freshness_threshold_old_unhealthy(self):
        _patient_with_domain_rows(last_seen=_minutes_ago(30 * 24 * 60))
        out, _err, error = _run_unhealthy("--max-movement-age-hours", "24")
        assert "movement_freshness=1" in out
        assert "movement_freshness=1" in error

    def test_freshness_absent_with_threshold_unhealthy(self):
        out, _err, error = _run_unhealthy("--max-event-age-hours", "24")
        assert "event_freshness=1" in out
        assert "event_freshness=1" in error
        assert "event_present=false" in out


class TestArgumentValidation:
    @pytest.mark.parametrize(
        "args",
        [
            ("--window-hours", "0"),
            ("--window-hours", "-5"),
            ("--settling-minutes", "-1"),
            ("--max-active-age-minutes", "0"),
            ("--max-active-age-minutes", "-10"),
            ("--max-full-sync-failure-percent", "-1"),
            ("--max-full-sync-failure-percent", "101"),
            ("--min-full-sync-terminal-sample", "0"),
            ("--min-full-sync-terminal-sample", "-3"),
            ("--max-movement-age-hours", "0"),
            ("--max-admission-age-hours", "-1"),
            ("--max-event-age-hours", "0"),
        ],
    )
    @mock.patch(
        "apps.ingestion.management.commands."
        "check_ingestion_pipeline_health.evaluate_pipeline_health"
    )
    def test_invalid_arguments_fail_before_any_query(
        self, mock_evaluate: mock.Mock, args: tuple[str, str]
    ):
        with pytest.raises(CommandError):
            call_command(COMMAND_NAME, *args)
        mock_evaluate.assert_not_called()


class TestReadOnlyEvaluation:
    def test_evaluation_does_not_mutate_any_model(self):
        batch = _batch()
        _admissions_success(batch=batch, admissions_seen=0, finished_at=_minutes_ago(5))
        _full_sync(batch=batch, status="failed", failure_reason="timeout")
        _demographics(batch=batch)
        _demographics(batch=batch)
        _patient_with_domain_rows(last_seen=_minutes_ago(60))
        before = _model_counts()
        _run_unhealthy()
        assert _model_counts() == before

    def test_evaluation_does_not_mutate_any_model_when_healthy(self):
        _patient_with_domain_rows(last_seen=_minutes_ago(60))
        before = _model_counts()
        _run_healthy()
        assert _model_counts() == before

    def test_no_playwright_network_or_command_execution(self):
        batch = _batch()
        _admissions_success(batch=batch, admissions_seen=0, finished_at=_minutes_ago(5))
        _full_sync(batch=batch, status="failed", failure_reason="timeout")
        with (
            mock.patch(
                "subprocess.Popen", side_effect=AssertionError("subprocess.Popen called")
            ),
            mock.patch(
                "subprocess.run", side_effect=AssertionError("subprocess.run called")
            ),
            mock.patch(
                "urllib.request.urlopen", side_effect=AssertionError("urllib called")
            ),
            mock.patch(
                "django.core.management.call_command",
                side_effect=AssertionError("call_command called"),
            ),
            mock.patch(
                "playwright.sync_api.sync_playwright",
                side_effect=AssertionError("playwright called"),
            ),
        ):
            _run_unhealthy()
            _run_unhealthy()


class TestOutputPrivacy:
    def test_sentinels_never_appear_in_stdout_stderr_or_error(self):
        batch = CensusExecutionBatch.objects.create(
            status="failed",
            notes_json={"sentinel": SENTINEL_TEXT},
        )
        run = _run(
            intent="admissions_only",
            status="succeeded",
            batch=batch,
            patient_record=SENTINEL_PATIENT,
            admissions_seen=0,
            finished_at=_minutes_ago(5),
            error_message=SENTINEL_ERROR,
        )
        IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="failed",
            failure_reason="invalid_payload",
            error_message=SENTINEL_ERROR,
        )
        FinalRunFailure.objects.create(
            batch=batch,
            run=run,
            patient_record=SENTINEL_PATIENT,
            intent="admissions_only",
            attempts_exhausted=3,
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="admissions_capture",
            started_at=_minutes_ago(10),
            status="failed",
            details_json={"sentinel": SENTINEL_TEXT},
        )
        _full_sync(
            batch=batch,
            status="failed",
            failure_reason="invalid_payload",
            error_message=SENTINEL_ERROR,
        )
        _patient_with_domain_rows(
            last_seen=_minutes_ago(30 * 24 * 60),
            patient_record=SENTINEL_PATIENT,
        )
        out, err, error = _run_unhealthy(
            "--max-movement-age-hours", "24",
            "--settling-minutes", "30",
        )
        combined = out + err + error
        for sentinel in (
            SENTINEL_PATIENT,
            SENTINEL_NAME,
            SENTINEL_ADMISSION,
            SENTINEL_SECTOR,
            SENTINEL_EVENT_KEY,
            SENTINEL_TEXT,
            SENTINEL_AUTHOR,
            SENTINEL_URL,
        ):
            assert sentinel not in combined, f"sentinel leaked: {sentinel}"
        assert "invalid_payload=1" in out


def _patient_with_domain_rows(
    *,
    last_seen,
    patient_record: str = "PRIV-PAT-001",
) -> Patient:
    patient = Patient.objects.create(
        patient_source_key=patient_record,
        source_system="tasy",
        name="PACIENTE SINTETICO S5",
    )
    admission = Admission.objects.create(
        patient=patient,
        source_admission_key=f"ADM-{patient_record}",
        source_system="tasy",
        admission_date=_minutes_ago(48 * 60),
        updated_at=last_seen,
    )
    PatientMovement.objects.create(
        patient=patient,
        admission=admission,
        movement_date=date.today(),
        sector="SETOR SINTETICO",
        first_seen_at=_minutes_ago(24 * 60),
        last_seen_at=last_seen,
    )
    ClinicalEvent.objects.create(
        admission=admission,
        patient=patient,
        event_identity_key=f"EVT-{patient_record}",
        content_hash="hash-sintetico",
        happened_at=_minutes_ago(12 * 60),
        signed_at=_minutes_ago(12 * 60),
        author_name="AUTOR SINTETICO",
        profession_type="medica",
        content_text="evolucao sintetica",
        signature_line="",
    )
    return patient
