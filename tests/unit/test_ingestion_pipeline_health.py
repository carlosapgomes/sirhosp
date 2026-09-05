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
from datetime import date, datetime, timedelta
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, PatientMovement
from apps.clinical_docs.models import ClinicalEvent
from apps.deaths.models import DeathRecord
from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)
from apps.ingestion.pipeline_health import HealthConfig, evaluate_pipeline_health
from apps.patients.models import (
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
    StaleAdmissionCase,
)

COMMAND_NAME = "check_ingestion_pipeline_health"
DAILY_COMMAND_NAME = "report_admission_reconciliation_integrity"

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
SENTINEL_BED = "PRIV-LEITO-S10"

TZ_LOCAL = ZoneInfo("America/Bahia")
T_BASE = datetime(2026, 3, 10, 9, 0, 0, tzinfo=TZ_LOCAL)

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


# ---------------------------------------------------------------------------
# RPSA-S10 fixtures (synthetic, identity-bearing values are sentinels)
# ---------------------------------------------------------------------------


def _hours_ago(hours: int):
    return timezone.now() - timedelta(hours=hours)


def _discharge_evidence(
    *,
    status: str,
    saida_em=None,
    alta_em=None,
    prontuario: str = SENTINEL_PATIENT,
) -> DischargeRecord:
    return DischargeRecord.objects.create(
        prontuario=prontuario,
        data_internacao=(
            f"PRIV-DI-S10-{DischargeRecord.objects.count() + 1}"
        ),
        saida_em=saida_em,
        alta_em=alta_em,
        nome=SENTINEL_NAME,
        reconciliation_status=status,
    )


def _death_evidence(
    *,
    status: str,
    obito_em=None,
    death_date: date | None = None,
) -> DeathRecord:
    return DeathRecord.objects.create(
        date=death_date or date.today(),
        prontuario=SENTINEL_PATIENT,
        nome=SENTINEL_NAME,
        obito_em=obito_em,
        reconciliation_status=status,
    )


def _census_run(captured_at) -> IngestionRun:
    return IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
        queued_at=captured_at,
        processing_started_at=captured_at,
        finished_at=captured_at,
    )


def _open_stale_case(*, first_absence_at) -> StaleAdmissionCase:
    patient = Patient.objects.create(
        patient_source_key=f"PRONT-S10-{StaleAdmissionCase.objects.count() + 1}",
        source_system="tasy",
        name="PACIENTE SINTETICO S10",
    )
    admission = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM-S10-{patient.pk}",
        admission_date=T_BASE - timedelta(days=2),
    )
    last_absence_at = first_absence_at + timedelta(minutes=45)
    return StaleAdmissionCase.objects.create(
        admission=admission,
        first_absence_run=_census_run(first_absence_at),
        first_absence_at=first_absence_at,
        last_absence_run=_census_run(last_absence_at),
        last_absence_at=last_absence_at,
    )


def _duplicate_pair(*, closed_fresher: bool = True):
    """Open + closed canonical admissions on one Bahia local date."""
    tag = Admission.objects.count() + 1
    patient = Patient.objects.create(
        patient_source_key=f"PRONT-S10-DUP-{tag}",
        source_system="tasy",
        name="PACIENTE SINTETICO S10",
    )
    opened = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM-S10-{tag}-OPEN",
        admission_date=T_BASE,
    )
    closed = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM-S10-{tag}-CLOSED",
        admission_date=T_BASE + timedelta(hours=1),
        discharge_date=T_BASE + timedelta(days=3),
    )
    if closed_fresher:
        Admission.objects.filter(pk=closed.pk).update(updated_at=_hours_ago(1))
        Admission.objects.filter(pk=opened.pk).update(updated_at=_hours_ago(10))
    else:
        Admission.objects.filter(pk=closed.pk).update(updated_at=_hours_ago(10))
        Admission.objects.filter(pk=opened.pk).update(updated_at=_hours_ago(1))
    return patient, opened, closed


def _discharge_run(
    *,
    ref_date: str,
    status: str = "succeeded",
    total_records: int | None = None,
    zero_confirmed: bool | None = None,
    attempt_count: int | None = None,
    with_persist_stage: bool = True,
) -> IngestionRun:
    """A durable discharge-extraction run keyed by its extraction date."""
    run = IngestionRun.objects.create(
        status=status,
        intent="discharge_extraction",
        queued_at=_hours_ago(2),
        processing_started_at=_hours_ago(2),
        finished_at=_hours_ago(1) if status in {"succeeded", "failed"} else None,
        failure_reason="" if status == "succeeded" else "timeout",
        parameters_json={"date": "01/06/2026", "ref_date": ref_date},
    )
    if with_persist_stage:
        details: dict[str, Any] = {}
        if total_records is not None:
            details["total_records"] = total_records
        if zero_confirmed is not None:
            details["zero_confirmed"] = zero_confirmed
        if attempt_count is not None:
            details["attempt_count"] = attempt_count
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="discharge_persistence",
            started_at=_hours_ago(2),
            status="succeeded" if status == "succeeded" else "failed",
            details_json=details,
        )
    return run


def _census_run_for_health() -> IngestionRun:
    return _census_run(_minutes_ago(30))


def _evaluate_reconciliation(**overrides):
    result = evaluate_pipeline_health(
        HealthConfig(**overrides), now=timezone.now()
    )
    return result.reconciliation, result


def _group(stats, name: str):
    return next(group for group in stats.backlog if group.name == name)


def _codes(result) -> set[str]:
    return {violation.code for violation in result.violations}


def _reconciliation_model_counts() -> dict[str, int]:
    models = (
        IngestionRun,
        IngestionRunStageMetric,
        Admission,
        Patient,
        StaleAdmissionCase,
        ReconciliationEvent,
        DischargeRecord,
        DeathRecord,
        DailyDischargeCount,
        CensusSnapshot,
    )
    return {model._meta.label: model.objects.count() for model in models}


# ---------------------------------------------------------------------------
# RPSA-S10: exit-evidence backlog by status group (count + oldest age)
# ---------------------------------------------------------------------------


class TestReconciliationBacklog:
    def test_backlog_counts_and_oldest_age_per_status_group(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_PENDING, saida_em=_hours_ago(72)
        )
        _death_evidence(
            status=RECONCILIATION_STATUS_PENDING, obito_em=_hours_ago(20)
        )
        stats, result = _evaluate_reconciliation()

        assert _group(stats, "pending").count == 2
        assert _group(stats, "pending").oldest_age_hours in (71, 72, 73)
        assert _group(stats, "ambiguous").count == 0
        assert _group(stats, "conflict").count == 0
        assert _group(stats, "stale_cases").count == 0
        assert "reconciliation_backlog_age" in _codes(result)

    def test_backlog_age_above_threshold_is_unhealthy_via_command(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_PENDING, saida_em=_hours_ago(72)
        )
        out, _err, error = _run_unhealthy()
        assert "reconciliation_backlog_age=1" in out
        assert "reconciliation_backlog_age=1" in error

    def test_ambiguous_group_also_respects_age_threshold(self):
        _death_evidence(
            status=RECONCILIATION_STATUS_AMBIGUOUS, obito_em=_hours_ago(72)
        )
        stats, result = _evaluate_reconciliation()
        assert _group(stats, "ambiguous").count == 1
        assert "reconciliation_backlog_age" in _codes(result)

    def test_fresh_backlog_is_within_default_threshold(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_PENDING, saida_em=_hours_ago(2)
        )
        stats, result = _evaluate_reconciliation()
        assert _group(stats, "pending").count == 1
        assert _group(stats, "pending").oldest_age_hours in (1, 2, 3)
        assert result.healthy

    def test_reconciled_evidence_is_not_backlog(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_RECONCILED, saida_em=_hours_ago(72)
        )
        _death_evidence(
            status=RECONCILIATION_STATUS_RECONCILED, obito_em=_hours_ago(72)
        )
        stats, result = _evaluate_reconciliation()
        for name in ("pending", "ambiguous", "conflict", "stale_cases"):
            assert _group(stats, name).count == 0
        assert result.healthy

    def test_reconciliation_events_are_never_pending_work(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_PENDING, saida_em=_hours_ago(2)
        )
        ReconciliationEvent.objects.create(
            source_kind="discharge_record",
            source_id=1,
            status=RECONCILIATION_STATUS_PENDING,
        )
        ReconciliationEvent.objects.create(
            source_kind="death_record",
            source_id=2,
            status=RECONCILIATION_STATUS_CONFLICT,
        )
        stats, result = _evaluate_reconciliation()
        assert _group(stats, "pending").count == 1
        assert _group(stats, "conflict").count == 0
        assert result.healthy

    def test_conflict_evidence_violates_at_max_zero(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_CONFLICT, saida_em=_hours_ago(1)
        )
        _death_evidence(
            status=RECONCILIATION_STATUS_CONFLICT, obito_em=_hours_ago(1)
        )
        stats, result = _evaluate_reconciliation()
        assert _group(stats, "conflict").count == 2
        conflict = next(
            violation
            for violation in result.violations
            if violation.code == "reconciliation_conflict_evidence"
        )
        assert conflict.count == 2

    def test_conflict_age_has_no_threshold(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_CONFLICT, saida_em=_hours_ago(500)
        )
        stats, result = _evaluate_reconciliation()
        assert _group(stats, "conflict").oldest_age_hours >= 499
        assert _codes(result) == {"reconciliation_conflict_evidence"}

    def test_open_stale_cases_are_the_fourth_group(self):
        _open_stale_case(first_absence_at=_hours_ago(5))
        stats, result = _evaluate_reconciliation()
        stale = _group(stats, "stale_cases")
        assert stale.count == 1
        assert stale.oldest_age_hours in (4, 5, 6)
        assert result.healthy  # count + age reported without a threshold

    def test_resolved_stale_cases_are_not_backlog(self):
        case = _open_stale_case(first_absence_at=_hours_ago(5))
        StaleAdmissionCase.objects.filter(pk=case.pk).update(
            resolved_at=timezone.now(),
            resolution_reason=StaleAdmissionCase.ResolutionReason.REAPPEARED,
        )
        stats, result = _evaluate_reconciliation()
        assert _group(stats, "stale_cases").count == 0
        assert result.healthy

    def test_evidence_without_anchor_is_counted_without_age(self):
        _discharge_evidence(status=RECONCILIATION_STATUS_PENDING)
        stats, result = _evaluate_reconciliation()
        pending = _group(stats, "pending")
        assert pending.count == 1
        assert pending.oldest_age_hours is None
        assert result.healthy  # unknown age cannot breach an age threshold

    def test_backlog_age_threshold_is_overridable(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_PENDING, saida_em=_hours_ago(2)
        )
        stats, result = _evaluate_reconciliation(backlog_age_max_hours=1)
        assert "reconciliation_backlog_age" in _codes(result)
        assert not result.healthy


# ---------------------------------------------------------------------------
# RPSA-S10: source-confirmed duplicate invariant (RPSA-S9 cohort shape)
# ---------------------------------------------------------------------------


class TestReconciliationDuplicates:
    def test_source_confirmed_duplicate_pair_violates(self):
        _duplicate_pair(closed_fresher=True)
        stats, result = _evaluate_reconciliation()
        assert stats.duplicate_pairs == 1
        duplicate = next(
            violation
            for violation in result.violations
            if violation.code == "reconciliation_duplicate_pair"
        )
        assert duplicate.count == 1

    def test_duplicate_pair_violation_reaches_command_output(self):
        _duplicate_pair(closed_fresher=True)
        out, _err, error = _run_unhealthy()
        assert "reconciliation_duplicate_pair=1" in out
        assert "reconciliation_duplicate_pair=1" in error

    def test_stale_closed_row_is_not_a_confirmed_duplicate(self):
        _duplicate_pair(closed_fresher=False)
        stats, result = _evaluate_reconciliation()
        assert stats.duplicate_pairs == 0
        assert result.healthy

    def test_two_open_rows_are_not_duplicates(self):
        patient, opened, _closed = _duplicate_pair(closed_fresher=True)
        Admission.objects.filter(pk=_closed.pk).update(discharge_date=None)
        del patient
        stats, result = _evaluate_reconciliation()
        assert stats.duplicate_pairs == 0
        assert result.healthy

    def test_different_local_dates_are_not_duplicates(self):
        _patient, opened, closed = _duplicate_pair(closed_fresher=True)
        Admission.objects.filter(pk=closed.pk).update(
            admission_date=T_BASE + timedelta(days=4)
        )
        del opened
        stats, result = _evaluate_reconciliation()
        assert stats.duplicate_pairs == 0
        assert result.healthy

    def test_different_patients_are_not_duplicates(self):
        _patient, opened, closed = _duplicate_pair(closed_fresher=True)
        other = Patient.objects.create(
            patient_source_key="PRONT-S10-OTHER",
            source_system="tasy",
            name="PACIENTE SINTETICO S10",
        )
        Admission.objects.filter(pk=closed.pk).update(patient_id=other.pk)
        del opened
        stats, result = _evaluate_reconciliation()
        assert stats.duplicate_pairs == 0
        assert result.healthy

    def test_merged_rows_leave_the_invariant(self):
        _patient, opened, closed = _duplicate_pair(closed_fresher=True)
        Admission.all_objects.filter(pk=closed.pk).update(
            merged_into_id=opened.pk
        )
        stats, result = _evaluate_reconciliation()
        assert stats.duplicate_pairs == 0
        assert result.healthy

    def test_duplicate_max_count_override_disarms_the_alarm(self):
        _duplicate_pair(closed_fresher=True)
        stats, result = _evaluate_reconciliation(duplicate_max_count=1)
        assert stats.duplicate_pairs == 1
        assert result.healthy


# ---------------------------------------------------------------------------
# RPSA-S10: extraction coverage from durable metadata only
# ---------------------------------------------------------------------------


class TestExtractionCoverage:
    def test_nonzero_persisted_records_is_complete(self):
        _discharge_run(ref_date="2026-06-01", total_records=5, attempt_count=1)
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.dates_total == 1
        assert stats.coverage.complete_dates == 1
        assert stats.coverage.gap_count == 0
        assert result.healthy

    def test_confirmed_zero_with_two_attempts_is_complete(self):
        _discharge_run(
            ref_date="2026-06-01",
            total_records=0,
            zero_confirmed=True,
            attempt_count=2,
        )
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.complete_dates == 1
        assert stats.coverage.gap_count == 0
        assert result.healthy

    def test_one_successful_empty_attempt_is_incomplete(self):
        _discharge_run(ref_date="2026-06-01", total_records=0, attempt_count=1)
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.incomplete_dates == 1
        assert stats.coverage.gap_count == 1
        assert stats.coverage.gap_first_date == date(2026, 6, 1)
        assert stats.coverage.gap_last_date == date(2026, 6, 1)
        assert result.healthy  # gap within the configured boundary

    def test_missing_zero_confirmed_flag_is_incomplete(self):
        _discharge_run(ref_date="2026-06-01", total_records=0)
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.incomplete_dates == 1
        assert stats.coverage.gap_count == 1

    def test_zero_confirmed_with_single_attempt_is_incomplete(self):
        _discharge_run(
            ref_date="2026-06-01",
            total_records=0,
            zero_confirmed=True,
            attempt_count=1,
        )
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.incomplete_dates == 1

    def test_succeeded_run_without_persist_stage_is_incomplete(self):
        _discharge_run(ref_date="2026-06-01", with_persist_stage=False)
        stats, _result = _evaluate_reconciliation()
        assert stats.coverage.incomplete_dates == 1

    def test_failed_run_only_is_missing(self):
        _discharge_run(
            ref_date="2026-06-01",
            status="failed",
            total_records=0,
            zero_confirmed=False,
        )
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.missing_dates == 1
        assert stats.coverage.gap_count == 1
        assert result.healthy

    def test_gap_bounds_span_earliest_and_latest_dates(self):
        _discharge_run(ref_date="2026-06-05", total_records=0, attempt_count=1)
        _discharge_run(ref_date="2026-06-01", total_records=0, attempt_count=1)
        _discharge_run(ref_date="2026-06-03", total_records=4)
        stats, _result = _evaluate_reconciliation()
        assert stats.coverage.gap_first_date == date(2026, 6, 1)
        assert stats.coverage.gap_last_date == date(2026, 6, 5)
        assert stats.coverage.gap_count == 2
        assert stats.coverage.complete_dates == 1

    def test_gap_above_seven_raises_operator_action_violation(self):
        for day in range(1, 9):  # eight incomplete dates
            _discharge_run(
                ref_date=f"2026-06-{day:02d}", total_records=0, attempt_count=1
            )
        before = IngestionRun.objects.filter(
            intent="historical_recovery"
        ).count()
        stats, result = _evaluate_reconciliation()
        gap = next(
            violation
            for violation in result.violations
            if violation.code == "extraction_coverage_gap"
        )
        assert gap.count == 8
        assert stats.coverage.gap_count == 8
        # Health NEVER starts recovery itself: no runs were enqueued.
        assert (
            IngestionRun.objects.filter(intent="historical_recovery").count()
            == before
        )

    def test_daily_discharge_count_is_never_coverage_evidence(self):
        DailyDischargeCount.objects.create(date=date(2026, 6, 1), count=7)
        stats, result = _evaluate_reconciliation()
        assert stats.coverage.dates_total == 0
        assert stats.coverage.gap_count == 0
        assert result.healthy

    def test_missing_dates_max_is_overridable(self):
        _discharge_run(ref_date="2026-06-01", total_records=0, attempt_count=1)
        _discharge_run(ref_date="2026-06-02", total_records=0, attempt_count=1)
        stats, result = _evaluate_reconciliation(missing_dates_max=1)
        assert stats.coverage.gap_count == 2
        gap = next(
            violation
            for violation in result.violations
            if violation.code == "extraction_coverage_gap"
        )
        assert gap.count == 2


# ---------------------------------------------------------------------------
# RPSA-S10: open admissions outside the current census (informational)
# ---------------------------------------------------------------------------


class TestOpenOutsideCensus:
    def _census_snapshot(self, captured_at, prontuario: str) -> None:
        CensusSnapshot.objects.create(
            captured_at=captured_at,
            ingestion_run=_census_run(captured_at),
            setor="SETOR SINTETICO",
            setor_codigo="1000",
            leito=SENTINEL_BED,
            prontuario=prontuario,
            nome="PACIENTE SINTETICO S10",
            bed_status=BedStatus.OCCUPIED,
        )

    def _admitted_patient(self, prontuario: str) -> Patient:
        patient = Patient.objects.create(
            patient_source_key=prontuario,
            source_system="tasy",
            name="PACIENTE SINTETICO S10",
        )
        Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key=f"ADM-S10-CENSUS-{patient.pk}",
            admission_date=T_BASE,
        )
        return patient

    def test_patient_present_in_latest_census_is_not_counted(self):
        self._admitted_patient("PRONT-S10-PRESENT")
        self._census_snapshot(_minutes_ago(30), "PRONT-S10-PRESENT")
        stats, result = _evaluate_reconciliation()
        assert stats.open_outside_census == 0
        assert result.healthy

    def test_patient_absent_from_latest_census_is_counted(self):
        self._admitted_patient("PRONT-S10-ABSENT")
        self._census_snapshot(_minutes_ago(30), "PRONT-S10-OTHER")
        stats, result = _evaluate_reconciliation()
        assert stats.open_outside_census == 1
        assert result.healthy  # informational: no threshold, no case created

    def test_only_the_latest_capture_is_compared(self):
        self._admitted_patient("PRONT-S10-GONE")
        self._census_snapshot(_minutes_ago(90), "PRONT-S10-GONE")
        self._census_snapshot(_minutes_ago(30), "PRONT-S10-SOMEONE-ELSE")
        stats, _result = _evaluate_reconciliation()
        assert stats.open_outside_census == 1

    def test_closed_and_merged_admissions_are_ignored(self):
        _patient, opened, closed = _duplicate_pair(closed_fresher=True)
        self._census_snapshot(_minutes_ago(30), "PRONT-S10-NOBODY")
        Admission.objects.filter(pk=closed.pk).update(
            merged_into_id=opened.pk
        )
        stats, result = _evaluate_reconciliation()
        # The open canonical twin stays open but is now the only candidate;
        # the closed row left the canonical manager with the merge.
        assert stats.open_outside_census == 1
        del _patient
        assert result.healthy

    def test_no_census_snapshot_at_all_is_informational_zero(self):
        self._admitted_patient("PRONT-S10-NO-CENSUS")
        stats, result = _evaluate_reconciliation()
        assert stats.open_outside_census == 0
        assert result.healthy


# ---------------------------------------------------------------------------
# RPSA-S10: named thresholds, read-only proof and identity-safe rendering
# ---------------------------------------------------------------------------


class TestReconciliationThresholdDefaults:
    def test_reconciliation_thresholds_have_safe_defaults(self):
        config = HealthConfig()
        assert config.missing_dates_max == 7
        assert config.backlog_age_max_hours == 48
        assert config.conflict_max_count == 0
        assert config.duplicate_max_count == 0

    def test_evaluation_is_read_only_with_reconciliation_data(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_PENDING, saida_em=_hours_ago(72)
        )
        _duplicate_pair(closed_fresher=True)
        _discharge_run(ref_date="2026-06-01", total_records=0, attempt_count=1)
        _open_stale_case(first_absence_at=_hours_ago(3))
        ReconciliationEvent.objects.create(
            source_kind="discharge_record", source_id=1, status="conflict"
        )
        before = _reconciliation_model_counts()
        _run_unhealthy()
        assert _reconciliation_model_counts() == before


class TestReconciliationArgumentValidation:
    @pytest.mark.parametrize(
        "args",
        [
            ("--missing-dates-max", "-1"),
            ("--backlog-age-max-hours", "0"),
            ("--conflict-max-count", "-1"),
            ("--duplicate-max-count", "-1"),
        ],
    )
    @mock.patch(
        "apps.ingestion.management.commands."
        "check_ingestion_pipeline_health.evaluate_pipeline_health"
    )
    def test_invalid_reconciliation_options_fail_before_any_query(
        self, mock_evaluate: mock.Mock, args: tuple[str, str]
    ):
        with pytest.raises(CommandError):
            call_command(COMMAND_NAME, *args)
        mock_evaluate.assert_not_called()

    @mock.patch(
        "apps.ingestion.management.commands."
        "check_ingestion_pipeline_health.evaluate_pipeline_health"
    )
    def test_reconciliation_options_reach_the_config(
        self, mock_evaluate: mock.Mock
    ):
        # Render the real result so the command completes end to end.
        mock_evaluate.side_effect = lambda config: evaluate_pipeline_health(
            config
        )
        call_command(
            COMMAND_NAME,
            "--missing-dates-max", "3",
            "--backlog-age-max-hours", "12",
            "--conflict-max-count", "2",
            "--duplicate-max-count", "4",
        )
        config = mock_evaluate.call_args.args[0]
        assert config.missing_dates_max == 3
        assert config.backlog_age_max_hours == 12
        assert config.conflict_max_count == 2
        assert config.duplicate_max_count == 4


class TestReconciliationOutputPrivacy:
    def test_reconciliation_sentinels_never_reach_the_output(self):
        _discharge_evidence(
            status=RECONCILIATION_STATUS_CONFLICT, saida_em=_hours_ago(72)
        )
        _death_evidence(status=RECONCILIATION_STATUS_CONFLICT)
        _duplicate_pair(closed_fresher=True)
        _open_stale_case(first_absence_at=_hours_ago(72))
        run = _discharge_run(
            ref_date="2026-06-01", total_records=0, attempt_count=1
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="discharge_persistence",
            started_at=_hours_ago(2),
            status="succeeded",
            details_json={"sentinel": SENTINEL_TEXT, "total_records": 0},
        )
        self._census_occupied_row()
        out, err, error = _run_unhealthy()
        combined = out + err + error
        for sentinel in (
            SENTINEL_PATIENT,
            SENTINEL_NAME,
            SENTINEL_ADMISSION,
            SENTINEL_BED,
            SENTINEL_TEXT,
        ):
            assert sentinel not in combined, f"sentinel leaked: {sentinel}"
        assert "group=conflict count=2" in out
        assert "reconciliation_duplicate_pair=1" in out

    def _census_occupied_row(self) -> None:
        captured_at = _minutes_ago(30)
        CensusSnapshot.objects.create(
            captured_at=captured_at,
            ingestion_run=_census_run(captured_at),
            setor="SETOR SINTETICO",
            setor_codigo="1000",
            leito=SENTINEL_BED,
            prontuario=SENTINEL_PATIENT,
            nome=SENTINEL_NAME,
            bed_status=BedStatus.OCCUPIED,
        )


class TestReconciliationRender:
    def test_healthy_output_renders_the_reconciliation_block(self):
        output = _run_healthy()
        assert (
            "reconciliation_backlog: group=pending count=0 "
            "oldest_age_hours=none" in output
        )
        assert (
            "reconciliation_backlog: group=stale_cases count=0 "
            "oldest_age_hours=none" in output
        )
        assert "reconciliation_duplicates: pairs=0" in output
        assert "reconciliation_census: open_outside_census=0" in output
        assert (
            "extraction_coverage: dates=0 complete=0 incomplete=0 missing=0 "
            "gap=0 gap_first_date=none gap_last_date=none" in output
        )

    def test_gap_bounds_render_as_dates_only(self):
        _discharge_run(ref_date="2026-06-01", total_records=0, attempt_count=1)
        _discharge_run(ref_date="2026-06-03", total_records=0, attempt_count=1)
        output = _run_healthy()
        assert (
            "extraction_coverage: dates=2 complete=0 incomplete=2 missing=0 "
            "gap=2 gap_first_date=2026-06-01 gap_last_date=2026-06-03"
            in output
        )
