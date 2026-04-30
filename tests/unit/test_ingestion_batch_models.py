"""RED: Unit tests for CensusExecutionBatch, IngestionRunAttempt,
FinalRunFailure, and new IngestionRun retry/batch fields."""

from datetime import datetime, timezone

import pytest

from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
)

# ---------------------------------------------------------------------------
# CensusExecutionBatch
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCensusExecutionBatchCreation:
    """RED: CensusExecutionBatch can be created with lifecycle fields."""

    def test_create_batch_with_running_status(self):
        batch = CensusExecutionBatch.objects.create(status="running")

        assert batch.pk is not None
        assert batch.status == "running"
        assert batch.started_at is not None

    def test_create_batch_with_succeeded_status(self):
        batch = CensusExecutionBatch.objects.create(status="succeeded")

        assert batch.status == "succeeded"

    def test_create_batch_with_failed_status(self):
        batch = CensusExecutionBatch.objects.create(status="failed")

        assert batch.status == "failed"

    def test_batch_status_choices(self):
        field = CensusExecutionBatch._meta.get_field("status")
        assert hasattr(field, "choices")
        actual = [c[0] for c in field.choices]
        expected = ["running", "succeeded", "failed"]
        assert actual == expected

    def test_enqueue_finished_at_nullable(self):
        batch = CensusExecutionBatch.objects.create(status="running")

        assert batch.enqueue_finished_at is None

    def test_finished_at_nullable(self):
        batch = CensusExecutionBatch.objects.create(status="running")

        assert batch.finished_at is None

    def test_notes_json_default_empty_dict(self):
        batch = CensusExecutionBatch.objects.create(status="running")

        assert batch.notes_json == {}

    def test_notes_json_persists_dict(self):
        batch = CensusExecutionBatch.objects.create(
            status="running",
            notes_json={"snapshot_id": 42, "admissions_count": 10},
        )
        batch.refresh_from_db()

        assert batch.notes_json == {"snapshot_id": 42, "admissions_count": 10}


@pytest.mark.django_db
class TestCensusExecutionBatchDuration:
    """RED: Derived duration from enqueue_finished_at to finished_at."""

    def test_total_duration_none_when_not_finished(self):
        batch = CensusExecutionBatch.objects.create(status="running")

        assert batch.total_duration_seconds is None

    def test_total_duration_none_when_enqueue_not_set(self):
        batch = CensusExecutionBatch.objects.create(
            status="running",
            finished_at=datetime(2026, 1, 1, 10, 10, 0, tzinfo=timezone.utc),
        )

        assert batch.total_duration_seconds is None

    def test_total_duration_returns_seconds(self):
        enqueue = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 1, 1, 10, 5, 30, tzinfo=timezone.utc)
        batch = CensusExecutionBatch.objects.create(status="running")
        CensusExecutionBatch.objects.filter(pk=batch.pk).update(
            enqueue_finished_at=enqueue,
            finished_at=finished,
        )
        batch.refresh_from_db()

        assert batch.total_duration_seconds == 330.0

    def test_str_representation(self):
        batch = CensusExecutionBatch.objects.create(status="running")

        assert str(batch) == f"CensusExecutionBatch #{batch.pk} [running]"


# ---------------------------------------------------------------------------
# IngestionRun — new retry/batch fields
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIngestionRunRetryFields:
    """RED: IngestionRun gains attempt_count, max_attempts, next_retry_at, batch."""

    def test_attempt_count_default_zero(self):
        run = IngestionRun.objects.create()

        assert run.attempt_count == 0

    def test_max_attempts_default_three(self):
        run = IngestionRun.objects.create()

        assert run.max_attempts == 3

    def test_next_retry_at_nullable_by_default(self):
        run = IngestionRun.objects.create()

        assert run.next_retry_at is None

    def test_next_retry_at_persists_datetime(self):
        future = datetime(2026, 1, 1, 10, 1, 0, tzinfo=timezone.utc)
        run = IngestionRun.objects.create(next_retry_at=future)
        run.refresh_from_db()

        assert run.next_retry_at == future

    def test_batch_nullable_by_default(self):
        run = IngestionRun.objects.create()

        assert run.batch is None

    def test_batch_fk_persists(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(batch=batch)
        run.refresh_from_db()

        assert run.batch == batch
        assert run.batch_id == batch.pk

    def test_attempt_count_and_max_attempts_custom(self):
        run = IngestionRun.objects.create(attempt_count=1, max_attempts=5)
        run.refresh_from_db()

        assert run.attempt_count == 1
        assert run.max_attempts == 5


# ---------------------------------------------------------------------------
# IngestionRunAttempt
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestIngestionRunAttemptCreation:
    """RED: IngestionRunAttempt tracks each retry attempt of a run."""

    def test_create_attempt_linked_to_run(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        assert attempt.pk is not None
        assert attempt.run == run
        assert attempt.run_id == run.pk

    def test_attempt_number_range(self):
        run = IngestionRun.objects.create()
        for n in (1, 2, 3):
            attempt = IngestionRunAttempt.objects.create(
                run=run,
                attempt_number=n,
                status="succeeded",
            )
            assert attempt.attempt_number == n

    def test_status_choices(self):
        field = IngestionRunAttempt._meta.get_field("status")
        assert hasattr(field, "choices")
        actual = [c[0] for c in field.choices]
        expected = ["succeeded", "failed"]
        assert actual == expected

    def test_failed_attempt_stores_failure_context(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="failed",
            failure_reason="timeout",
            timed_out=True,
            error_message="Connection timed out after 30s",
        )
        attempt.refresh_from_db()

        assert attempt.status == "failed"
        assert attempt.failure_reason == "timeout"
        assert attempt.timed_out is True
        assert attempt.error_message == "Connection timed out after 30s"

    def test_started_at_auto_set(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        assert attempt.started_at is not None

    def test_finished_at_nullable(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        assert attempt.finished_at is None

    def test_failure_reason_blank_default(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        assert attempt.failure_reason == ""

    def test_timed_out_default_false(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        assert attempt.timed_out is False

    def test_error_message_blank_default(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        assert attempt.error_message == ""

    def test_str_representation(self):
        run = IngestionRun.objects.create()
        attempt = IngestionRunAttempt.objects.create(
            run=run,
            attempt_number=1,
            status="succeeded",
        )

        expected = (
            f"IngestionRunAttempt #{attempt.pk} "
            f"run={run.pk} "
            f"attempt=1 "
            f"[succeeded]"
        )
        assert str(attempt) == expected

    def test_ordering_by_started_at(self):
        run = IngestionRun.objects.create()
        a1 = IngestionRunAttempt.objects.create(
            run=run, attempt_number=1, status="failed",
        )
        a2 = IngestionRunAttempt.objects.create(
            run=run, attempt_number=2, status="succeeded",
        )

        attempts = list(IngestionRunAttempt.objects.filter(run=run))
        assert attempts[0].pk == a1.pk
        assert attempts[1].pk == a2.pk

    def test_related_name_from_run(self):
        run = IngestionRun.objects.create()
        a1 = IngestionRunAttempt.objects.create(
            run=run, attempt_number=1, status="failed",
        )
        a2 = IngestionRunAttempt.objects.create(
            run=run, attempt_number=2, status="succeeded",
        )

        assert list(run.attempts.all()) == [a1, a2]


@pytest.mark.django_db
class TestIngestionRunAttemptFailureReasonChoices:
    """RED: IngestionRunAttempt failure_reason mirrors IngestionRun choices."""

    def test_failure_reason_choices(self):
        field = IngestionRunAttempt._meta.get_field("failure_reason")
        assert hasattr(field, "choices")
        actual = [c[0] for c in field.choices if c[0]]
        expected = [
            "timeout",
            "source_unavailable",
            "invalid_payload",
            "unexpected_exception",
            "validation_error",
        ]
        assert actual == expected


# ---------------------------------------------------------------------------
# FinalRunFailure
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestFinalRunFailureCreation:
    """RED: FinalRunFailure materialises exhausted attempts per patient/intent."""

    def test_create_final_failure(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(batch=batch)
        failure = FinalRunFailure.objects.create(
            batch=batch,
            run=run,
            patient_record="12345",
            intent="admissions_only",
            attempts_exhausted=3,
        )

        assert failure.pk is not None
        assert failure.batch == batch
        assert failure.run == run
        assert failure.patient_record == "12345"
        assert failure.intent == "admissions_only"
        assert failure.attempts_exhausted == 3

    def test_failed_at_auto_set(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(batch=batch)
        failure = FinalRunFailure.objects.create(
            batch=batch,
            run=run,
            patient_record="67890",
            intent="full_sync",
            attempts_exhausted=3,
        )

        assert failure.failed_at is not None

    def test_patient_record_max_length(self):
        field = FinalRunFailure._meta.get_field("patient_record")
        assert field.max_length is not None
        assert field.max_length >= 50  # at least 50 chars

    def test_intent_max_length(self):
        field = FinalRunFailure._meta.get_field("intent")
        assert field.max_length is not None
        assert field.max_length >= 50

    def test_str_representation(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(batch=batch)
        failure = FinalRunFailure.objects.create(
            batch=batch,
            run=run,
            patient_record="12345",
            intent="admissions_only",
            attempts_exhausted=3,
        )

        expected = (
            f"FinalRunFailure #{failure.pk} "
            f"patient=12345 "
            f"intent=admissions_only"
        )
        assert str(failure) == expected

    def test_ordering_by_failed_at_desc(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run1 = IngestionRun.objects.create(batch=batch)
        run2 = IngestionRun.objects.create(batch=batch)

        f1 = FinalRunFailure.objects.create(
            batch=batch,
            run=run1,
            patient_record="111",
            intent="admissions_only",
            attempts_exhausted=3,
        )
        f2 = FinalRunFailure.objects.create(
            batch=batch,
            run=run2,
            patient_record="222",
            intent="demographics_only",
            attempts_exhausted=3,
        )

        failures = list(FinalRunFailure.objects.all())
        # f2 created after f1, should appear first due to -failed_at
        assert failures[0].pk == f2.pk
        assert failures[1].pk == f1.pk

    def test_unique_constraint_batch_run(self):
        """RED: Each run can only have one final failure record (OneToOneField)."""
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(batch=batch)
        FinalRunFailure.objects.create(
            batch=batch,
            run=run,
            patient_record="111",
            intent="admissions_only",
            attempts_exhausted=3,
        )

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            FinalRunFailure.objects.create(
                batch=batch,
                run=run,
                patient_record="222",
                intent="demographics_only",
                attempts_exhausted=3,
            )
