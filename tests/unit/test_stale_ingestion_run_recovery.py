"""Tests for stale IngestionRun recovery service and command."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.models import CensusExecutionBatch, IngestionRun, IngestionRunAttempt
from apps.ingestion.stale_recovery import (
    StaleRunCandidate,
    find_stale_run_candidates,
    recover_stale_ingestion_runs,
)


@pytest.fixture
def fixed_now():
    return timezone.now().replace(microsecond=0)


def _running_run(now, *, intent="admissions_only", age_minutes=30, heartbeat=None, **kwargs):
    defaults = {
        "status": "running",
        "intent": intent,
        "queued_at": now - timedelta(minutes=age_minutes + 1),
        "processing_started_at": now - timedelta(minutes=age_minutes),
        "worker_heartbeat_at": heartbeat,
        "parameters_json": {"patient_record": "SECRET_PATIENT", "intent": intent},
    }
    defaults.update(kwargs)
    return IngestionRun.objects.create(**defaults)


@pytest.mark.django_db
class TestStaleRecoveryCandidateDetection:
    def test_detects_only_old_running_runs_with_missing_or_stale_heartbeat(self, fixed_now):
        stale = _running_run(fixed_now, intent="admissions_only", age_minutes=21)
        _running_run(
            fixed_now,
            intent="admissions_only",
            age_minutes=90,
            heartbeat=fixed_now - timedelta(minutes=2),
        )
        _running_run(fixed_now, intent="admissions_only", age_minutes=19)
        _running_run(fixed_now, intent="admissions_only", age_minutes=90, status="succeeded")

        candidates = find_stale_run_candidates(now=fixed_now)

        assert [candidate.run_id for candidate in candidates] == [stale.pk]
        assert candidates[0].intent == "admissions_only"
        assert candidates[0].worker_heartbeat_at is None

    def test_uses_per_intent_limits_and_default_for_unknown_intent(self, fixed_now):
        demographics = _running_run(fixed_now, intent="demographics_only", age_minutes=21)
        _running_run(fixed_now, intent="full_sync", age_minutes=59)
        full_sync = _running_run(fixed_now, intent="full_sync", age_minutes=61)
        census = _running_run(fixed_now, intent="census_extraction", age_minutes=121)
        unknown = _running_run(fixed_now, intent="custom_intent", age_minutes=61)
        empty = _running_run(fixed_now, intent="", age_minutes=61)

        candidate_ids = {
            candidate.run_id for candidate in find_stale_run_candidates(now=fixed_now)
        }

        assert candidate_ids == {
            demographics.pk,
            full_sync.pk,
            census.pk,
            unknown.pk,
            empty.pk,
        }


@pytest.mark.django_db
class TestStaleRecoveryDryRunAndApply:
    def test_command_dry_run_reports_candidates_without_mutation_or_sensitive_data(self, fixed_now):
        run = _running_run(fixed_now, intent="admissions_only", age_minutes=25)
        out = StringIO()

        call_command("recover_stale_ingestion_runs", "--dry-run", stdout=out, now=fixed_now)

        run.refresh_from_db()
        output = out.getvalue()
        assert run.status == "running"
        assert f"run_id={run.pk}" in output
        assert "admissions_only" in output
        assert "SECRET_PATIENT" not in output
        assert "clinical" not in output.lower()

    def test_apply_marks_abandoned_run_failed_terminally_without_requeue(self, fixed_now):
        run = _running_run(
            fixed_now,
            intent="admissions_only",
            age_minutes=25,
            attempt_count=2,
            next_retry_at=fixed_now + timedelta(minutes=5),
        )
        IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="failed",
            failure_reason="source_unavailable",
        )

        result = recover_stale_ingestion_runs(apply=True, now=fixed_now)

        run.refresh_from_db()
        assert result.marked_failed_run_ids == [run.pk]
        assert run.status == "failed"
        assert run.finished_at == fixed_now
        assert run.timed_out is True
        assert run.failure_reason == "timeout"
        assert run.next_retry_at is None
        assert run.attempt_count == 2
        assert IngestionRunAttempt.objects.filter(run=run).count() == 1
        assert "stale recovery" in run.error_message.lower()
        assert "SECRET_PATIENT" not in run.error_message

    def test_apply_skips_candidate_that_is_no_longer_running(self, fixed_now):
        """Race safety: do not overwrite a run that became terminal."""
        run = _running_run(fixed_now, intent="admissions_only", age_minutes=25)
        run.status = "succeeded"
        run.finished_at = fixed_now - timedelta(minutes=1)
        run.save(update_fields=["status", "finished_at"])
        candidate = StaleRunCandidate(
            run_id=run.pk,
            batch_id=None,
            intent="admissions_only",
            status="running",
            worker_label="worker:1",
            reference_at=fixed_now - timedelta(minutes=25),
            age_seconds=25 * 60,
            worker_heartbeat_at=None,
            stale_limit_seconds=20 * 60,
        )

        with patch(
            "apps.ingestion.stale_recovery.find_stale_run_candidates",
            return_value=[candidate],
        ):
            result = recover_stale_ingestion_runs(apply=True, now=fixed_now)

        run.refresh_from_db()
        assert result.marked_failed_run_ids == []
        assert result.skipped_run_ids == [run.pk]
        assert run.status == "succeeded"
        assert run.finished_at == fixed_now - timedelta(minutes=1)


@pytest.mark.django_db
class TestStaleRecoveryBatchClosureAndCircuitBreaker:
    def test_apply_closes_drained_batch_as_failed_after_recovery(self, fixed_now):
        batch = CensusExecutionBatch.objects.create(
            status="running",
            enqueue_finished_at=fixed_now - timedelta(minutes=40),
        )
        run = _running_run(
            fixed_now,
            intent="admissions_only",
            age_minutes=25,
            batch=batch,
        )

        result = recover_stale_ingestion_runs(apply=True, now=fixed_now)

        run.refresh_from_db()
        batch.refresh_from_db()
        assert result.closed_batch_ids == [batch.pk]
        assert run.status == "failed"
        assert batch.finished_at == fixed_now
        assert batch.status == "failed"

    def test_apply_keeps_batch_open_when_other_active_runs_remain(self, fixed_now):
        batch = CensusExecutionBatch.objects.create(status="running")
        stale = _running_run(
            fixed_now,
            intent="admissions_only",
            age_minutes=25,
            batch=batch,
        )
        IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            batch=batch,
            queued_at=fixed_now,
            parameters_json={"patient_record": "OTHER_SECRET"},
        )

        result = recover_stale_ingestion_runs(apply=True, now=fixed_now)

        stale.refresh_from_db()
        batch.refresh_from_db()
        assert result.closed_batch_ids == []
        assert stale.status == "failed"
        assert batch.finished_at is None
        assert batch.status == "running"

    def test_circuit_breaker_aborts_without_mutation_when_candidates_exceed_limit(self, fixed_now):
        run1 = _running_run(fixed_now, intent="admissions_only", age_minutes=25)
        run2 = _running_run(fixed_now, intent="demographics_only", age_minutes=25)

        result = recover_stale_ingestion_runs(
            apply=True,
            now=fixed_now,
            max_runs_per_sweep=1,
        )

        run1.refresh_from_db()
        run2.refresh_from_db()
        assert result.aborted is True
        assert result.abort_reason == "candidate_count_exceeded_limit"
        assert result.marked_failed_run_ids == []
        assert run1.status == "running"
        assert run2.status == "running"
