"""PSW-S17 corrected: shared failure-classification and terminal-finalization
helpers, plus a true cross-worker lifecycle parity matrix.

Coverage:

- :func:`classify_failure_reason` taxonomy (5 categories, no chain walk).
- :func:`record_final_run_failure` idempotency and field parity.
- :func:`safe_failure_text` returns stable per-category constants.
- A real cross-worker matrix: each R1 category is run through BOTH worker
  commands in the SAME test, in BOTH retryable and terminal modes, with
  exception factories (not stored instances).
- Current-worker characterization tests proving the pre-S17 taxonomy is
  preserved for raw and wrapped Playwright timeouts (R3).
- Sentinel tests proving sensitive values never reach DB error fields,
  command stderr, or logs on the persistent path (R4).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.legacy_navigation import (
    DEADLINE_EXPIRED_MESSAGE,
    NavigationTimeoutError,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    EvolutionPdfError,
    EvolutionPdfTimeoutError,
)
from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)
from apps.ingestion.run_lifecycle import (
    classify_failure_reason,
    record_final_run_failure,
    safe_failure_text,
)

# ---------------------------------------------------------------------------
# Classifier unit tests (no DB)
# ---------------------------------------------------------------------------


class TestClassifyFailureReason:
    """R1-R3: every failure category maps to the same tuple in both workers."""

    def _classify(self, exc: Exception) -> tuple[str, bool]:
        return classify_failure_reason(exc)

    # -- Timeout category (R2, R3) ------------------------------------

    def test_extraction_timeout_classified_as_timeout(self):
        assert self._classify(
            ExtractionTimeoutError("Extraction timed out after 90s")
        ) == ("timeout", True)

    def test_subprocess_timeout_classified_as_timeout(self):
        assert self._classify(
            SubprocessTimeoutError(cmd=["python", "x.py"], timeout=300)
        ) == ("timeout", True)

    def test_navigation_timeout_classified_as_timeout(self):
        assert self._classify(
            NavigationTimeoutError(DEADLINE_EXPIRED_MESSAGE)
        ) == ("timeout", True)

    def test_evolution_pdf_timeout_classified_as_timeout(self):
        assert self._classify(
            EvolutionPdfTimeoutError("Persistent evolution PDF download timed out.")
        ) == ("timeout", True)

    # R3 correction: raw Playwright TimeoutError MUST NOT be reinterpreted
    # by the shared classifier. Source boundaries must map it to a typed
    # domain timeout; if it reaches the classifier raw, it falls through to
    # unexpected_exception (preserving the pre-S17 current-worker taxonomy).
    def test_raw_playwright_timeout_not_reinterpreted(self):
        # PSW-S17 R1 (second closure): use the real Playwright TimeoutError type.
        reason, timed_out = self._classify(
            PlaywrightTimeoutError("Timeout 30000ms")
        )
        assert reason == "unexpected_exception"
        assert timed_out is False

    def test_extraction_error_wrapping_playwright_timeout_is_source_unavailable(self):
        """R3: an ExtractionError that wraps a raw Playwright timeout via
        ``from exc`` is classified by its outer type (ExtractionError ->
        source_unavailable), NOT by walking the cause chain."""

        try:
            try:
                raise PlaywrightTimeoutError("Timeout 30000ms")
            except Exception as exc:
                raise ExtractionError("navigation failed") from exc
        except ExtractionError as wrapped:
            reason, timed_out = self._classify(wrapped)
        assert reason == "source_unavailable"
        assert timed_out is False

    # -- invalid_payload category (R1) --------------------------------

    def test_invalid_json_classified_as_invalid_payload(self):
        assert self._classify(InvalidJsonError("bad json")) == (
            "invalid_payload",
            False,
        )

    def test_snapshot_container_missing_classified_as_invalid_payload(self):
        assert self._classify(
            SnapshotContainerMissingError("container missing")
        ) == ("invalid_payload", False)

    def test_evolution_pdf_error_classified_as_invalid_payload(self):
        assert self._classify(EvolutionPdfError("PDF flow failed")) == (
            "invalid_payload",
            False,
        )

    # -- validation_error category (R1) -------------------------------

    def test_validation_error_classified_as_validation_error(self):
        assert self._classify(ValidationError("invalid")) == (
            "validation_error",
            False,
        )

    # -- source_unavailable category (R1) -----------------------------

    def test_generic_extraction_error_classified_as_source_unavailable(self):
        assert self._classify(ExtractionError("source down")) == (
            "source_unavailable",
            False,
        )

    # -- unexpected_exception category (R1) ---------------------------

    def test_unexpected_exception_classified_as_unexpected(self):
        assert self._classify(ValueError("db pool exhausted")) == (
            "unexpected_exception",
            False,
        )


# ---------------------------------------------------------------------------
# safe_failure_text
# ---------------------------------------------------------------------------


class TestSafeFailureText:
    """R4: stable per-category constants for command failure lines."""

    @pytest.mark.parametrize(
        "reason, expected",
        [
            ("timeout", "source-system action timed out"),
            ("source_unavailable", "source-system action unavailable"),
            ("invalid_payload", "source-system payload invalid or unavailable"),
            ("validation_error", "source-system validation error"),
            ("unexpected_exception", "unexpected worker failure"),
        ],
    )
    def test_returns_stable_constant_per_category(self, reason, expected):
        assert safe_failure_text(reason) == expected

    def test_unknown_category_returns_safe_default(self):
        assert safe_failure_text("nonsense") == "worker failure"

    def test_constants_contain_no_secret_keywords(self):
        for text in [
            safe_failure_text("timeout"),
            safe_failure_text("source_unavailable"),
            safe_failure_text("invalid_payload"),
            safe_failure_text("unexpected_exception"),
        ]:
            lowered = text.lower()
            assert "http" not in lowered
            assert "cookie" not in lowered
            assert "password" not in lowered
            assert "patient" not in lowered
            assert "jsessionid" not in lowered


# ---------------------------------------------------------------------------
# Strict normalized sanitization (D4 / R2 final closure)
# ---------------------------------------------------------------------------


SENSITIVE_PATIENT_SENTINEL = "SENSITIVE-PATIENT-0001"
SENSITIVE_URL_SENTINEL = "https://sensitive.example.test/SENSITIVE_URL"
SENSITIVE_COOKIE_SENTINEL = "SENSITIVE_COOKIE_VALUE"
# PSW-S17 post-31dd3c0 (R5): distinct sentinels injected at realistic
# boundaries (admission snapshot admissionKey; selector carried by a
# Playwright locator/wait error) and asserted absent from every error/
# output/log/cause/context surface.
SENSITIVE_ADMISSION_KEY_SENTINEL = "SENSITIVE-ADM-KEY-0001"
SENSITIVE_SELECTOR_SENTINEL = '[data-rk="SENSITIVE_SELECTOR_X"]'
SENSITIVE_STDOUT_SENTINEL = "SENSITIVE_STDOUT_LEAK"
SENSITIVE_STDERR_SENTINEL = "SENSITIVE_STDERR_LEAK"


class TestStrictNormalizedSanitization:
    """D4/R2 final closure: safe_error_message and safe_error_type derive
    text solely from the normalized category. No ``str(exc)`` or dynamic
    class name may be persisted for ANY exception class."""

    def test_typed_extraction_error_message_is_category_constant(self):
        """ExtractionError with sensitive text must NOT persist str(exc);"""
        from apps.ingestion.run_lifecycle import safe_error_message

        exc = ExtractionError(f"boom at {SENSITIVE_URL_SENTINEL}")
        msg = safe_error_message(exc, "source_unavailable")
        assert msg == safe_failure_text("source_unavailable")
        assert SENSITIVE_URL_SENTINEL not in msg

    def test_typed_extraction_timeout_message_is_category_constant(self):
        """ExtractionTimeoutError with sensitive text must NOT persist str(exc)."""
        from apps.ingestion.run_lifecycle import safe_error_message

        exc = ExtractionTimeoutError(
            f"timed out at {SENSITIVE_URL_SENTINEL} cookie={SENSITIVE_COOKIE_SENTINEL}"
        )
        msg = safe_error_message(exc, "timeout")
        assert msg == safe_failure_text("timeout")
        assert SENSITIVE_URL_SENTINEL not in msg
        assert SENSITIVE_COOKIE_SENTINEL not in msg

    def test_invalid_json_error_message_is_category_constant(self):
        """InvalidJsonError with sensitive text must NOT persist str(exc)."""
        from apps.ingestion.run_lifecycle import safe_error_message

        exc = InvalidJsonError(
            f"bad json at {SENSITIVE_URL_SENTINEL}"
        )
        msg = safe_error_message(exc, "invalid_payload")
        assert msg == safe_failure_text("invalid_payload")
        assert SENSITIVE_URL_SENTINEL not in msg

    def test_unexpected_exception_message_is_category_constant(self):
        """ValueError with sensitive text must NOT persist str(exc)."""
        from apps.ingestion.run_lifecycle import safe_error_message

        exc = ValueError(f"cookie={SENSITIVE_COOKIE_SENTINEL}")
        msg = safe_error_message(exc, "unexpected_exception")
        assert msg == safe_failure_text("unexpected_exception")
        assert SENSITIVE_COOKIE_SENTINEL not in msg

    def test_error_type_never_dynamic_class_name(self):
        """safe_error_type returns the normalized category, never a dynamic
        class name (which could carry misleading context)."""
        from apps.ingestion.run_lifecycle import safe_error_type

        for exc, reason in [
            (ExtractionError("x"), "source_unavailable"),
            (ExtractionTimeoutError("x"), "timeout"),
            (InvalidJsonError("x"), "invalid_payload"),
            (ValueError("x"), "unexpected_exception"),
        ]:
            assert safe_error_type(exc, reason) == reason


# ---------------------------------------------------------------------------
# record_final_run_failure integration tests (DB)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRecordFinalRunFailure:
    """R5: exactly one ``FinalRunFailure`` row under the same conditions and
    fields as the current worker, idempotently."""

    def _make_run(
        self,
        *,
        batch: CensusExecutionBatch | None,
        patient_record: str = "FF_P1",
        intent: str = "admissions_only",
        attempt_count: int = 3,
    ) -> IngestionRun:
        params = {"patient_record": patient_record, "intent": intent}
        return IngestionRun.objects.create(
            status="failed",
            intent=intent,
            batch=batch,
            attempt_count=attempt_count,
            max_attempts=attempt_count,
            parameters_json=params,
        )

    def test_creates_final_run_failure_with_same_fields_as_current_worker(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = self._make_run(batch=batch, patient_record="FF_P1")

        record_final_run_failure(run)

        failure = FinalRunFailure.objects.get(run=run)
        assert failure.batch_id == batch.pk
        assert failure.patient_record == "FF_P1"
        assert failure.intent == "admissions_only"
        assert failure.attempts_exhausted == run.attempt_count
        assert failure.failed_at is not None

    def test_idempotent_exactly_one_row(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = self._make_run(batch=batch)

        record_final_run_failure(run)
        record_final_run_failure(run)

        assert FinalRunFailure.objects.filter(run=run).count() == 1

    def test_no_row_when_batch_missing(self):
        run = self._make_run(batch=None, patient_record="NO_BATCH")
        record_final_run_failure(run)
        assert FinalRunFailure.objects.filter(run=run).count() == 0

    def test_no_row_when_patient_record_missing(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = self._make_run(batch=batch, patient_record="")
        record_final_run_failure(run)
        assert FinalRunFailure.objects.filter(run=run).count() == 0

    def test_intent_falls_back_to_run_intent_when_param_missing(self):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="failed",
            intent="demographics_only",
            batch=batch,
            attempt_count=2,
            max_attempts=2,
            parameters_json={"patient_record": "FF_DEMO"},
        )
        record_final_run_failure(run)
        failure = FinalRunFailure.objects.get(run=run)
        assert failure.intent == "demographics_only"


# ---------------------------------------------------------------------------
# Cross-worker lifecycle parity matrix (R1)
# ---------------------------------------------------------------------------


# Exception FACTORIES (not stored instances) so each parameterized case
# gets a fresh exception with no shared traceback/context state.
def _validation_error_factory() -> ValidationError:
    return ValidationError("patient record format invalid")


def _extraction_error_factory() -> ExtractionError:
    return ExtractionError("source connection refused")


def _invalid_json_factory() -> InvalidJsonError:
    return InvalidJsonError("Expected JSON array, got str")


def _extraction_timeout_factory() -> ExtractionTimeoutError:
    return ExtractionTimeoutError("Extraction timed out after 90s")


def _unexpected_value_error_factory() -> ValueError:
    return ValueError("Database connection pool exhausted")


FAILURE_CATEGORIES: list[tuple[str, Callable[[], Exception], str, bool]] = [
    ("validation_error", _validation_error_factory, "validation_error", False),
    ("source_unavailable", _extraction_error_factory, "source_unavailable", False),
    ("invalid_payload", _invalid_json_factory, "invalid_payload", False),
    ("timeout", _extraction_timeout_factory, "timeout", True),
    ("unexpected_exception", _unexpected_value_error_factory, "unexpected_exception", False),
]
"""Tuple of (id, exception factory, expected_reason, expected_timed_out)."""


@pytest.mark.django_db
class TestCrossWorkerFailureParityMatrix:
    """R1: each of the five categories is run through BOTH worker commands
    in the SAME test, in both retryable and terminal modes, with exception
    factories."""

    def _queue_run(self, *, mode: str, label: str) -> IngestionRun:
        """Create a run that will land in ``mode`` after this attempt.

        ``mode == 'retryable'``: attempt_count=0, max_attempts=3 -> after
        increment attempt_count=1 < 3 -> requeued.

        ``mode == 'terminal'``: attempt_count=2, max_attempts=3 -> after
        increment attempt_count=3 == 3 -> terminal failure.
        """
        batch = CensusExecutionBatch.objects.create(status="running")
        params = {
            "patient_record": f"P-{label}",
            "intent": "admissions_only",
        }
        if mode == "retryable":
            attempt_count = 0
        else:
            attempt_count = 2
            # Seed prior failed attempts so the new attempt is the last.
            run = IngestionRun.objects.create(
                status="queued",
                intent="admissions_only",
                batch=batch,
                attempt_count=attempt_count,
                max_attempts=3,
                parameters_json=params,
            )
            for i in range(1, 3):
                IngestionRunAttempt.objects.create(
                    run=run,
                    attempt_number=i,
                    status="failed",
                    failure_reason="source_unavailable",
                    finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
                )
            return run
        return IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=attempt_count,
            max_attempts=3,
            parameters_json=params,
        )

    def _patch_current(self, exc: Exception):
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = exc
        mock_ext.extract_evolutions.return_value = []
        return patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        )

    def _patch_persistent(self, exc: Exception):
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        mock_adapter = MagicMock()
        mock_adapter.get_admission_snapshot.side_effect = exc
        mock_adapter.get_demographics.return_value = {}
        mock_adapter.extract_evolutions.return_value = []
        mock_adapter.ensure_session_ready.return_value = True
        mock_adapter.controller = MagicMock()
        mock_adapter.controller.restart_required.return_value = False
        return patch.object(
            PersistentWorkerCommand,
            "_create_adapter",
            return_value=mock_adapter,
        )

    @pytest.mark.parametrize(
        "category_id, exc_factory, expected_reason, expected_timed_out",
        FAILURE_CATEGORIES,
        ids=[c[0] for c in FAILURE_CATEGORIES],
    )
    @pytest.mark.parametrize("mode", ["retryable", "terminal"])
    def test_both_workers_match_for_each_category_and_mode(
        self,
        category_id,
        exc_factory,
        expected_reason,
        expected_timed_out,
        mode,
    ):
        """Single test that runs BOTH workers with the same failure and
        compares externally observable state."""
        # --- Current worker ---
        run_current = self._queue_run(mode=mode, label=f"cur-{category_id}")
        with self._patch_current(exc_factory()):
            call_command("process_ingestion_runs")
        run_current.refresh_from_db()

        # --- Persistent worker ---
        run_persistent = self._queue_run(
            mode=mode, label=f"per-{category_id}"
        )
        with self._patch_persistent(exc_factory()):
            call_command("process_ingestion_runs_persistent_session")
        run_persistent.refresh_from_db()

        # --- Parity assertions ---
        # Classification on both run and latest attempt must match.
        assert run_current.failure_reason == expected_reason
        assert run_current.timed_out is expected_timed_out
        assert run_persistent.failure_reason == expected_reason
        assert run_persistent.timed_out is expected_timed_out

        # Attempt taxonomy parity.
        for run in (run_current, run_persistent):
            latest = (
                IngestionRunAttempt.objects.filter(run=run)
                .order_by("-attempt_number")
                .first()
            )
            assert latest is not None
            assert latest.status == "failed"
            assert latest.failure_reason == expected_reason
            assert latest.timed_out is expected_timed_out
            assert latest.finished_at is not None

        # Mode-specific parity.
        if mode == "retryable":
            for run in (run_current, run_persistent):
                assert run.status == "queued"
                assert run.next_retry_at is not None
                # next_retry_at ~= failure time + 60s (bounded).
                now = timezone.now()
                lower = now + timedelta(seconds=45)
                upper = now + timedelta(seconds=90)
                assert lower <= run.next_retry_at <= upper
                assert run.finished_at is None
                # No terminal record on retry.
                assert FinalRunFailure.objects.filter(run=run).count() == 0
                # Attached batch stays running.
                run.batch.refresh_from_db()
                assert run.batch.status == "running"
                assert run.batch.finished_at is None
        else:  # terminal
            for run in (run_current, run_persistent):
                assert run.status == "failed"
                assert run.finished_at is not None
                assert run.next_retry_at is None
                # Exactly one FinalRunFailure with correct fields.
                failures = list(FinalRunFailure.objects.filter(run=run))
                assert len(failures) == 1
                failure = failures[0]
                assert failure.batch_id == run.batch_id
                assert failure.attempts_exhausted == run.attempt_count
                # PSW-S17 R7 (second closure): FinalRunFailure field parity.
                params = run.parameters_json or {}
                assert failure.patient_record == params.get("patient_record", "")
                assert failure.intent == "admissions_only"

        # PSW-S17 post-ce2c494 (D15): EXACT normalized snapshot parity
        # between workers. Compares exact run/attempt error messages (not
        # just presence), stage metric details, and batch state.
        from apps.ingestion.run_lifecycle import safe_failure_text

        def _snap(run):
            latest = (
                IngestionRunAttempt.objects.filter(run=run)
                .order_by("-attempt_number")
                .first()
            )
            stage = IngestionRunStageMetric.objects.filter(
                run=run, stage_name="admissions_capture"
            ).first()
            batch = run.batch
            return {
                "run_status": run.status,
                "attempt_count": run.attempt_count,
                "failure_reason": run.failure_reason,
                "timed_out": run.timed_out,
                "run_error_message": run.error_message or "",
                "run_finished_at_present": run.finished_at is not None,
                "next_retry_at_present": run.next_retry_at is not None,
                "attempt_status": latest.status if latest else None,
                "attempt_number": latest.attempt_number if latest else None,
                "attempt_failure_reason": latest.failure_reason if latest else None,
                "attempt_timed_out": latest.timed_out if latest else None,
                "attempt_error_message": (latest.error_message if latest else "") or "",
                "attempt_finished_at_present": bool(latest and latest.finished_at),
                "stage_status": stage.status if stage else None,
                "stage_error_type": (stage.details_json or {}).get("error_type")
                if stage else None,
                "stage_error_message": (stage.details_json or {}).get("error_message")
                if stage else None,
                "final_failure_count": FinalRunFailure.objects.filter(run=run).count(),
                "batch_status": batch.status if batch else None,
                "batch_finished_at_present": bool(batch and batch.finished_at),
            }

        snap_current = _snap(run_current)
        snap_persistent = _snap(run_persistent)
        assert snap_current == snap_persistent, (
            f"Worker snapshot mismatch ({category_id}/{mode}):\n"
            f"current={snap_current}\npersistent={snap_persistent}"
        )

        # Exact normalized error messages equal the category constant.
        expected_msg = safe_failure_text(expected_reason)
        assert run_current.error_message == expected_msg
        assert run_persistent.error_message == expected_msg

        # PSW-S17 post-cbf50c1 (D15/R5): INDEPENDENT assertions on BOTH
        # workers for attempt and stage fields — not only worker-to-worker
        # equality (both could otherwise share the same wrong value).
        for run in (run_current, run_persistent):
            latest = (
                IngestionRunAttempt.objects.filter(run=run)
                .order_by("-attempt_number")
                .first()
            )
            assert latest is not None
            assert latest.error_message == expected_msg
            stage = IngestionRunStageMetric.objects.filter(
                run=run, stage_name="admissions_capture"
            ).first()
            assert stage is not None
            assert stage.status == "failed"
            assert (stage.details_json or {}).get("error_type") == expected_reason
            assert (
                (stage.details_json or {}).get("error_message") == expected_msg
            )
            # R4: independent stage timing semantics on BOTH workers.
            assert stage.started_at is not None
            assert stage.finished_at is not None

        # Idempotency: re-finalizing the persistent run does not duplicate.
        if mode == "terminal":
            # D15: explicit FinalRunFailure field snapshot.
            for run in (run_current, run_persistent):
                ff = FinalRunFailure.objects.filter(run=run).first()
                assert ff is not None
                params = run.parameters_json or {}
                assert ff.batch_id == run.batch_id
                assert ff.run_id == run.id
                assert ff.patient_record == params.get("patient_record", "")
                assert ff.intent == "admissions_only"
                assert ff.attempts_exhausted == run.attempt_count
                assert ff.failed_at is not None
            record_final_run_failure(run_persistent)
            assert FinalRunFailure.objects.filter(run=run_persistent).count() == 1

    def test_terminal_drained_batch_closes_as_failed(self):
        """R6: a terminal failure on the last drained batch closes it."""
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            max_attempts=3,
            parameters_json={"patient_record": "DRAIN-P", "intent": "admissions_only"},
        )
        with self._patch_persistent(_extraction_error_factory()):
            call_command("process_ingestion_runs_persistent_session")
        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "failed"
        assert batch.status == "failed"
        assert batch.finished_at is not None

    def test_terminal_batch_with_other_active_run_stays_open(self):
        """R6: a terminal failure does not close a batch with another
        queued/running run."""
        batch = CensusExecutionBatch.objects.create(status="running")
        run_a = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            max_attempts=3,
            parameters_json={"patient_record": "A-P", "intent": "admissions_only"},
        )
        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=0,
            max_attempts=3,
            parameters_json={"patient_record": "B-P", "intent": "admissions_only"},
        )
        # Select only run_a via --run-id so the other stays queued.
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        mock_adapter = MagicMock()
        mock_adapter.get_admission_snapshot.side_effect = _extraction_error_factory()
        mock_adapter.get_demographics.return_value = {}
        mock_adapter.extract_evolutions.return_value = []
        mock_adapter.ensure_session_ready.return_value = True
        mock_adapter.controller = MagicMock()
        mock_adapter.controller.restart_required.return_value = False
        with patch.object(
            PersistentWorkerCommand,
            "_create_adapter",
            return_value=mock_adapter,
        ):
            call_command(
                "process_ingestion_runs_persistent_session",
                run_id=run_a.pk,
                max_runs=1,
            )
        run_a.refresh_from_db()
        batch.refresh_from_db()
        assert run_a.status == "failed"
        assert batch.status == "running"
        assert batch.finished_at is None


# ---------------------------------------------------------------------------
# Current-worker pre/post behavior characterization (R3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCurrentWorkerPreservation:
    """R3: prove the current worker retains its pre-S17 taxonomy for raw
    and wrapped Playwright timeouts (the chain walker that changed this was
    removed)."""

    def _queue_run(self) -> IngestionRun:
        return IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            attempt_count=2,
            max_attempts=3,
            parameters_json={
                "patient_record": "CWP-P",
                "intent": "admissions_only",
            },
        )

    def test_direct_raw_playwright_timeout_is_unexpected_exception(self):
        """A raw Playwright TimeoutError reaching the current worker
        directly (not mapped to a typed domain timeout) classifies as
        unexpected_exception — pre-S17 behavior."""

        run = self._queue_run()
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = PlaywrightTimeoutError(
            "Timeout 30000ms"
        )
        mock_ext.extract_evolutions.return_value = []
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")
        run.refresh_from_db()
        assert run.failure_reason == "unexpected_exception"
        assert run.timed_out is False

    def test_extraction_error_wrapping_playwright_timeout_is_source_unavailable(self):
        """An ExtractionError that happens to wrap a Playwright timeout
        classifies by its outer type — source_unavailable — preserving the
        pre-S17 current-worker taxonomy (no cause/context chain walk)."""

        def side_effect(*args, **kwargs):
            try:
                raise PlaywrightTimeoutError("Timeout 30000ms")
            except Exception as exc:
                raise ExtractionError("navigation failed") from exc

        run = self._queue_run()
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = side_effect
        mock_ext.extract_evolutions.return_value = []
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ):
            call_command("process_ingestion_runs")
        run.refresh_from_db()
        assert run.failure_reason == "source_unavailable"
        assert run.timed_out is False


# ---------------------------------------------------------------------------
# Sentinel sanitization tests (R4)
# ---------------------------------------------------------------------------

SENSITIVE_PATIENT_SENTINEL_ALREADY_DEFINED = True  # sentinels moved up


@pytest.mark.django_db
class TestSentinelSanitizationPersistent:
    """R4: synthetic sensitive values injected at source boundaries must
    NOT reach DB error fields, command stderr, or logs on the persistent
    path."""

    def _queue_run(self, *, intent: str = "admissions_only") -> IngestionRun:
        return IngestionRun.objects.create(
            status="queued",
            intent=intent,
            attempt_count=2,
            max_attempts=3,
            parameters_json={
                "patient_record": SENSITIVE_PATIENT_SENTINEL,
                "intent": intent,
            },
        )

    def test_admissions_navigation_timeout_does_not_leak_patient_record(
        self, caplog, capsys
    ):
        """The real bridge/adapter admissions-navigation deadline timeout
        surfaces as a typed NavigationTimeoutError with a constant message;
        the patient record stored in ``parameters_json`` does NOT leak
        into any DB error field, command stderr, or log.

        This models the realistic persistent timeout path: the source
        boundary raises a typed exception with a CONSTANT sanitized
        message (``DEADLINE_EXPIRED_MESSAGE``), so ``str(exc)`` stored in
        ``error_message`` is the constant, not the patient record.
        """
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        class _FakePage:
            pass

        timeout_handle = MagicMock()
        timeout_handle.ensure_current_page.return_value = _FakePage()
        timeout_handle.is_connected.return_value = True
        timeout_handle.get_page_html.return_value = (
            "<html><body>"
            '<div id="tempoSessao" class="tempo-sessao">'
            "Tempo: <span>00</span>:<span>29</span>:<span>01</span>"
            "</div></body></html>"
        )

        run = self._queue_run()
        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        bridge = RealHandleBridge(timeout_handle)
        adapter = PersistentExtractionAdapter(session=bridge)
        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=adapter
        ), patch(
            "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen",
            side_effect=NavigationTimeoutError(DEADLINE_EXPIRED_MESSAGE),
        ), caplog.at_level("WARNING"):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.failure_reason == "timeout"
        assert run.timed_out is True

        # The patient record sentinel (stored only in parameters_json) must
        # NOT reach any DB error field or log.
        for blob in [
            run.error_message or "",
            run.attempts.order_by("-attempt_number").first().error_message or "",
        ]:
            assert SENSITIVE_PATIENT_SENTINEL not in blob
        for metric in IngestionRunStageMetric.objects.filter(run=run):
            text = str(metric.details_json or {})
            assert SENSITIVE_PATIENT_SENTINEL not in text
        for record in caplog.records:
            log_text = record.getMessage()
            assert SENSITIVE_PATIENT_SENTINEL not in log_text
        # D16: command stdout AND stderr must not leak the sentinel.
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            assert SENSITIVE_PATIENT_SENTINEL not in stream

    def test_pdf_download_timeout_does_not_leak_sentinels(self, caplog):
        """The real PDF flow download timeout surfaces as a typed
        EvolutionPdfTimeoutError with a constant message; no sentinel
        leaks into DB fields or logs."""
        from apps.ingestion.extractors.errors import is_playwright_timeout_error
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            EvolutionPdfFlow,
            EvolutionPdfTimeoutError,
        )
        from apps.ingestion.extractors.persistent_evolution_pdf import (
            _deadline_s as _pdf_deadline_s,
        )

        # Sanity: detection helper recognises the duck-typed class.
        assert is_playwright_timeout_error(PlaywrightTimeoutError("x"))

        # A minimal fake page whose context.request.get raises a Playwright
        # timeout carrying sensitive content.
        sentinel_msg = (
            f"Timeout 30000ms at {SENSITIVE_URL_SENTINEL} "
            f"cookie={SENSITIVE_COOKIE_SENTINEL}"
        )

        class _FakeRequest:
            def get(self, url, timeout):  # noqa: ARG002
                raise PlaywrightTimeoutError(sentinel_msg)

        class _FakeContext:
            request = _FakeRequest()

        class _FakePage:
            context = _FakeContext()
            url = "about:blank"
            frames: list = []

            def content(self):
                return ""

        flow = EvolutionPdfFlow(_FakePage())
        # Force the download path: pre-resolve a fake PDF URL so _download is
        # reached directly.
        with pytest.raises(EvolutionPdfTimeoutError) as exc_info, caplog.at_level(
            "WARNING"
        ):
            flow._download(SENSITIVE_URL_SENTINEL, _pdf_deadline_s(30))

        # The typed exception message is a constant; the sentinel never
        # appears in str(exc) or in logs.
        assert SENSITIVE_URL_SENTINEL not in str(exc_info.value)
        assert SENSITIVE_COOKIE_SENTINEL not in str(exc_info.value)
        for record in caplog.records:
            log_text = record.getMessage()
            assert SENSITIVE_URL_SENTINEL not in log_text
            assert SENSITIVE_COOKIE_SENTINEL not in log_text


# ---------------------------------------------------------------------------
# Persistent source-boundary typed-timeout propagation (R2)
# ---------------------------------------------------------------------------


class TestPersistentSourceBoundaryTimeouts:
    """R2: persistent source boundaries raise typed timeouts at the
    adapter/command boundary — not generic ExtractionError."""

    def test_open_tab_raises_extraction_timeout_on_playwright_timeout(self):
        """PlaywrightSessionHandle.open_tab raises ExtractionTimeoutError
        when page.goto raises a Playwright timeout (no False return), and
        the typed message is a constant (no URL/raw text leak)."""
        import pytest

        from apps.ingestion.extractors.errors import ExtractionTimeoutError
        from apps.ingestion.extractors.playwright_session_handle import (
            PlaywrightSessionHandle,
        )

        handle = PlaywrightSessionHandle.__new__(PlaywrightSessionHandle)

        class _FakePage:
            def goto(self, url, *, timeout, wait_until):  # noqa: ARG002
                raise PlaywrightTimeoutError(
                    f"Timeout at {SENSITIVE_URL_SENTINEL} "
                    f"cookie={SENSITIVE_COOKIE_SENTINEL}"
                )

        class _FakeContext:
            def new_page(self):
                return _FakePage()

        handle._context = _FakeContext()
        with pytest.raises(ExtractionTimeoutError) as exc_info:
            handle.open_tab(SENSITIVE_URL_SENTINEL, timeout=5)
        message = str(exc_info.value)
        assert SENSITIVE_URL_SENTINEL not in message
        assert SENSITIVE_COOKIE_SENTINEL not in message

    def test_navigate_to_admissions_propagates_navigation_timeout(self):
        """RealHandleBridge.navigate_to_admissions re-raises a
        NavigationTimeoutError instead of collapsing it to False."""
        import pytest

        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        class _FakePage:
            pass

        class _TimeoutHandle:
            def ensure_current_page(self):
                return _FakePage()

        bridge = RealHandleBridge(_TimeoutHandle())
        with patch(
            "apps.ingestion.extractors.real_handle_bridge.ensure_search_screen",
            side_effect=NavigationTimeoutError(DEADLINE_EXPIRED_MESSAGE),
        ):
            with pytest.raises(NavigationTimeoutError):
                bridge.navigate_to_admissions(SENSITIVE_PATIENT_SENTINEL)

    def test_bridge_download_pdf_raises_evolution_timeout_with_constant_message(self):
        """RealHandleBridge._download_pdf raises EvolutionPdfTimeoutError
        on a Playwright download timeout, with a constant message (no URL
        or raw text leak)."""
        import pytest

        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge

        class _FakeRequest:
            def get(self, url, timeout):  # noqa: ARG002
                raise PlaywrightTimeoutError(
                    f"Timeout at {SENSITIVE_URL_SENTINEL} "
                    f"cookie={SENSITIVE_COOKIE_SENTINEL}"
                )

        class _FakeContext:
            request = _FakeRequest()

        class _FakePage:
            context = _FakeContext()

        bridge = RealHandleBridge.__new__(RealHandleBridge)
        with pytest.raises(EvolutionPdfTimeoutError) as exc_info:
            bridge._download_pdf(_FakePage(), SENSITIVE_URL_SENTINEL, 1000)
        message = str(exc_info.value)
        assert SENSITIVE_URL_SENTINEL not in message
        assert SENSITIVE_COOKIE_SENTINEL not in message


# ---------------------------------------------------------------------------
# Current-worker subprocess sentinel tests (R5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCurrentWorkerSubprocessSentinels:
    """R5: current-worker subprocess failures must not leak sensitive
    cmd/output content into persisted error_message or command output."""

    def _queue_run(self) -> IngestionRun:
        return IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            attempt_count=2,
            max_attempts=3,
            parameters_json={
                "patient_record": SENSITIVE_PATIENT_SENTINEL,
                "intent": "admissions_only",
            },
        )

    def test_subprocess_timeout_does_not_leak_cmd_or_patient_record(
        self, capsys, caplog
    ):
        """SubprocessTimeoutError carrying a sensitive cmd (incl. patient
        record) must NOT propagate that cmd into run/attempt error_message,
        command stdout, command stderr, or logs."""
        import logging

        from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError

        run = self._queue_run()
        sensitive_cmd = [
            "python",
            "path2.py",
            "--patient-record",
            SENSITIVE_PATIENT_SENTINEL,
        ]
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = SubprocessTimeoutError(
            cmd=sensitive_cmd,
            timeout=120,
            output=f"leaked {SENSITIVE_STDOUT_SENTINEL}",
            stderr=f"leaked {SENSITIVE_STDERR_SENTINEL}",
        )
        mock_ext.extract_evolutions.return_value = []
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), caplog.at_level(logging.WARNING):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.failure_reason == "timeout"
        assert run.timed_out is True
        latest = run.attempts.order_by("-attempt_number").first()
        for blob in [
            run.error_message or "",
            latest.error_message if latest else "",
        ]:
            assert SENSITIVE_PATIENT_SENTINEL not in blob
            assert SENSITIVE_STDOUT_SENTINEL not in blob
            assert SENSITIVE_STDERR_SENTINEL not in blob
        for metric in IngestionRunStageMetric.objects.filter(run=run):
            text = str(metric.details_json or {})
            assert SENSITIVE_PATIENT_SENTINEL not in text
            assert SENSITIVE_STDOUT_SENTINEL not in text
            assert SENSITIVE_STDERR_SENTINEL not in text
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            assert SENSITIVE_PATIENT_SENTINEL not in stream
            assert SENSITIVE_STDOUT_SENTINEL not in stream
            assert SENSITIVE_STDERR_SENTINEL not in stream
        for record in caplog.records:
            text = record.getMessage()
            assert SENSITIVE_PATIENT_SENTINEL not in text
            assert SENSITIVE_STDOUT_SENTINEL not in text
            assert SENSITIVE_STDERR_SENTINEL not in text

    def test_arbitrary_value_error_sanitized_to_constant(self, capsys, caplog):
        """An arbitrary ValueError carrying a sentinel cannot reach run,
        attempt, stage, command stdout, command stderr, or logs."""
        import logging

        run = self._queue_run()
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = ValueError(
            f"cookie={SENSITIVE_COOKIE_SENTINEL}"
        )
        mock_ext.extract_evolutions.return_value = []
        with patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        ), caplog.at_level(logging.WARNING):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.failure_reason == "unexpected_exception"
        latest = run.attempts.order_by("-attempt_number").first()
        assert SENSITIVE_COOKIE_SENTINEL not in (run.error_message or "")
        assert SENSITIVE_COOKIE_SENTINEL not in (
            latest.error_message if latest else ""
        )
        for metric in IngestionRunStageMetric.objects.filter(run=run):
            text = str(metric.details_json or {})
            assert SENSITIVE_COOKIE_SENTINEL not in text
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            assert SENSITIVE_COOKIE_SENTINEL not in stream
        for record in caplog.records:
            assert SENSITIVE_COOKIE_SENTINEL not in record.getMessage()


# ---------------------------------------------------------------------------
# D7: Cross-worker stage metric + batch closure parity (final closure)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossWorkerStageMetricParity:
    """D7: both workers produce identical normalized stage details for each
    failure category. Compares exact stage error_type and error_message."""

    @pytest.mark.parametrize(
        "category_id, exc_factory, expected_reason",
        [
            ("validation_error", _validation_error_factory, "validation_error"),
            ("source_unavailable", _extraction_error_factory, "source_unavailable"),
            ("invalid_payload", _invalid_json_factory, "invalid_payload"),
            ("timeout", _extraction_timeout_factory, "timeout"),
            ("unexpected_exception", _unexpected_value_error_factory, "unexpected_exception"),
        ],
        ids=[c[0] for c in FAILURE_CATEGORIES],
    )
    def test_both_workers_same_stage_details(
        self, category_id, exc_factory, expected_reason
    ):
        """The admissions_capture stage metric details (error_type,
        error_message) are identical between both workers for the same
        failure category."""
        from apps.ingestion.run_lifecycle import safe_failure_text

        batch_c = CensusExecutionBatch.objects.create(status="running")
        run_c = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch_c,
            attempt_count=0,
            max_attempts=1,
            parameters_json={"patient_record": f"SMC-{category_id}", "intent": "admissions_only"},
        )
        with _PatchCurrent(exc_factory()):
            call_command("process_ingestion_runs")
        run_c.refresh_from_db()

        batch_p = CensusExecutionBatch.objects.create(status="running")
        run_p = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch_p,
            attempt_count=0,
            max_attempts=1,
            parameters_json={"patient_record": f"SMP-{category_id}", "intent": "admissions_only"},
        )
        with _PatchPersistent(exc_factory()):
            call_command("process_ingestion_runs_persistent_session")
        run_p.refresh_from_db()

        expected_msg = safe_failure_text(expected_reason)
        for run in (run_c, run_p):
            stage = IngestionRunStageMetric.objects.get(
                run=run, stage_name="admissions_capture"
            )
            assert stage.status == "failed"
            assert stage.details_json["error_type"] == expected_reason
            assert stage.details_json["error_message"] == expected_msg


class _PatchCurrent:
    """Context manager patching the current worker extractor."""

    def __init__(self, exc):
        self._exc = exc

    def __enter__(self):
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = self._exc
        mock_ext.extract_evolutions.return_value = []
        self._patch = patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        )
        return self._patch.__enter__()

    def __exit__(self, *args):
        self._patch.__exit__(*args)


class _PatchPersistent:
    """Context manager patching the persistent worker adapter."""

    def __init__(self, exc):
        self._exc = exc

    def __enter__(self):
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )
        mock_adapter = MagicMock()
        mock_adapter.get_admission_snapshot.side_effect = self._exc
        mock_adapter.get_demographics.return_value = {}
        mock_adapter.extract_evolutions.return_value = []
        mock_adapter.ensure_session_ready.return_value = True
        mock_adapter.controller = MagicMock()
        mock_adapter.controller.restart_required.return_value = False
        self._patch = patch.object(
            PersistentWorkerCommand,
            "_create_adapter",
            return_value=mock_adapter,
        )
        return self._patch.__enter__()

    def __exit__(self, *args):
        self._patch.__exit__(*args)


@pytest.mark.django_db
class TestCrossWorkerBatchClosureParity:
    """D7: batch closure semantics are identical for both workers — drained
    terminal batches close as failed; batches with another active run stay
    open."""

    def _seed_drained_batch(self, worker_label: str):
        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            max_attempts=3,
            parameters_json={
                "patient_record": f"DB-{worker_label}",
                "intent": "admissions_only",
            },
        )
        return batch, run

    def _seed_active_sibling_batch(self, worker_label: str):
        batch = CensusExecutionBatch.objects.create(status="running")
        run_a = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            max_attempts=3,
            parameters_json={
                "patient_record": f"AC-{worker_label}",
                "intent": "admissions_only",
            },
        )
        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=0,
            max_attempts=3,
            parameters_json={
                "patient_record": f"AC2-{worker_label}",
                "intent": "admissions_only",
            },
        )
        return batch, run_a

    def test_current_drained_terminal_batch_closes_as_failed(self):
        batch, run = self._seed_drained_batch("cur-d")
        with _PatchCurrent(_extraction_error_factory()):
            call_command("process_ingestion_runs")
        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "failed"
        assert batch.status == "failed"
        assert batch.finished_at is not None

    def test_persistent_drained_terminal_batch_closes_as_failed(self):
        batch, run = self._seed_drained_batch("per-d")
        with _PatchPersistent(_extraction_error_factory()):
            call_command("process_ingestion_runs_persistent_session")
        run.refresh_from_db()
        batch.refresh_from_db()
        assert run.status == "failed"
        assert batch.status == "failed"
        assert batch.finished_at is not None

    def test_current_batch_with_other_active_run_stays_open(self):
        batch, run_a = self._seed_active_sibling_batch("cur-a")
        with _PatchCurrent(_extraction_error_factory()):
            call_command("process_ingestion_runs")
        run_a.refresh_from_db()
        batch.refresh_from_db()
        assert run_a.status == "failed"
        assert batch.status == "running"
        assert batch.finished_at is None

    def test_persistent_batch_with_other_active_run_stays_open(self):
        batch, run_a = self._seed_active_sibling_batch("per-a")
        with _PatchPersistent(_extraction_error_factory()):
            call_command("process_ingestion_runs_persistent_session")
        run_a.refresh_from_db()
        batch.refresh_from_db()
        assert run_a.status == "failed"
        assert batch.status == "running"
        assert batch.finished_at is None


# ---------------------------------------------------------------------------
# D8: Command-level persistent PDF download timeout
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCommandLevelPersistentPdfTimeout:
    """D8: a persistent full_sync run whose PDF download times out records
    failure_reason=timeout, timed_out=True, through the real
    PersistentExtractionAdapter -> RealHandleBridge -> EvolutionPdfFlow chain.

    The timeout originates as the public real
    ``playwright.sync_api.TimeoutError`` type from a synthetic browser-like
    fake request. No Chromium is launched."""

    def test_pdf_download_timeout_records_timeout_category(
        self, caplog, capsys
    ):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        class _FakeRequest:
            def get(self, url, timeout):  # noqa: ARG002
                raise PlaywrightTimeoutError(
                    f"Timeout at {SENSITIVE_URL_SENTINEL} "
                    f"cookie={SENSITIVE_COOKIE_SENTINEL}"
                )

        class _FakeContext:
            request = _FakeRequest()

        class _FakePdfPage:
            context = _FakeContext()
            url = "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
            frames: list = []
            content_calls = 0

            def content(self):
                _FakePdfPage.content_calls += 1
                raise AssertionError("page.content() must not be called")

            def locator(self, selector):  # noqa: ARG002
                from apps.ingestion.extractors.persistent_evolution_pdf import (
                    _PDF_OBJECT_SELECTOR,
                )

                if selector == _PDF_OBJECT_SELECTOR:
                    obj = MagicMock()
                    obj.count.return_value = 1
                    obj.first.get_attribute.return_value = (
                        f"{SENSITIVE_URL_SENTINEL}/report.pdf"
                    )
                    return obj
                # Other selectors (date/generate probes) are absent.
                loc = MagicMock()
                loc.count.return_value = 0
                return loc

        class _FakeHandle:
            def __init__(self):
                self._html = _build_admissions_html()

            def ensure_current_page(self):
                return _FakePdfPage()

            def is_connected(self):
                return True

            def get_page_html(self):
                return self._html

            def set_html(self, html):
                self._html = html

            def open_tab(self, url, *, timeout=120):  # noqa: ARG002
                return True

            def click_selector(self, selector):  # noqa: ARG002
                pass

            def get_tab_classes(self):
                return []

            def close_last_non_root_tab(self):
                pass

            def restart_browser(self):
                pass

            def shutdown(self):
                pass

        handle = _FakeHandle()
        bridge = RealHandleBridge(handle)
        adapter = PersistentExtractionAdapter(session=bridge)

        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            batch=batch,
            attempt_count=0,
            max_attempts=1,
            parameters_json={
                "patient_record": SENSITIVE_PATIENT_SENTINEL,
                "intent": "full_sync",
                "start_date": "2026-01-01",
                "end_date": "2026-01-15",
            },
        )

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=adapter
        ), patch.object(
            RealHandleBridge, "navigate_to_admissions", return_value=True
        ), patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs_persistent_session.persist_admissions_snapshot",
            return_value=(MagicMock(), {"seen": 1, "created": 1, "updated": 0}),
        ), caplog.at_level("WARNING"):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        # Command-level: timeout category with timed_out=True.
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True

        latest = (
            IngestionRunAttempt.objects.filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        assert latest is not None
        assert latest.failure_reason == "timeout"
        assert latest.timed_out is True

        # Stage metric uses normalized timeout category and constant message.
        ev_stage = IngestionRunStageMetric.objects.get(
            run=run, stage_name="evolution_extraction"
        )
        assert ev_stage.status == "failed"
        assert ev_stage.details_json["error_type"] == "timeout"
        assert ev_stage.details_json["error_message"] == safe_failure_text("timeout")

        # Sentinel assertions: no sensitive URL, cookie, patient, stdout, or
        # stderr text reaches run/attempt/stage/stdout/stderr/logs.
        for blob in [
            run.error_message or "",
            latest.error_message or "",
            str(ev_stage.details_json or {}),
        ]:
            assert SENSITIVE_URL_SENTINEL not in blob
            assert SENSITIVE_COOKIE_SENTINEL not in blob
            assert SENSITIVE_PATIENT_SENTINEL not in blob
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            assert SENSITIVE_URL_SENTINEL not in stream
            assert SENSITIVE_COOKIE_SENTINEL not in stream
            assert SENSITIVE_PATIENT_SENTINEL not in stream
        for record in caplog.records:
            text = record.getMessage()
            assert SENSITIVE_URL_SENTINEL not in text
            assert SENSITIVE_COOKIE_SENTINEL not in text
            assert SENSITIVE_PATIENT_SENTINEL not in text

    def test_command_pdf_timeout_sentinels_admission_key_and_selector_absent(
        self, caplog, capsys
    ):
        """R5: distinct admission-key and selector sentinels injected at
        realistic boundaries (admission snapshot admissionKey; selector
        carried by a Playwright locator-timeout error) never reach any
        run/attempt/stage error field, stdout, stderr, or log."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        class _TimeoutAttrLocator:
            first = property(lambda self: self)

            def count(self) -> int:
                return 1

            def get_attribute(self, name, **kwargs):  # noqa: ARG002
                # Realistic: the raw Playwright locator error carries the
                # CSS selector and the URL/cookie; the typed wrapper must
                # strip all of it.
                raise PlaywrightTimeoutError(
                    f"Timeout {SENSITIVE_SELECTOR_SENTINEL} at "
                    f"{SENSITIVE_URL_SENTINEL} "
                    f"cookie={SENSITIVE_COOKIE_SENTINEL}"
                )

        class _FakePdfPage:
            context = MagicMock()
            url = "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
            frames: list = []
            content_calls = 0

            def locator(self, selector):  # noqa: ARG002
                return _TimeoutAttrLocator()

            def content(self):  # type: ignore[no-untyped-def]
                _FakePdfPage.content_calls += 1
                raise AssertionError("page.content() must not be called")

        class _FakeHandle:
            def __init__(self):
                self._html = _build_admissions_html(
                    SENSITIVE_ADMISSION_KEY_SENTINEL
                )

            def ensure_current_page(self):
                return _FakePdfPage()

            def is_connected(self):
                return True

            def get_page_html(self):
                return self._html

            def set_html(self, html):
                self._html = html

            def open_tab(self, url, *, timeout=120):  # noqa: ARG002
                return True

            def click_selector(self, selector):  # noqa: ARG002
                pass

            def get_tab_classes(self):
                return []

            def close_last_non_root_tab(self):
                pass

            def restart_browser(self):
                pass

            def shutdown(self):
                pass

        handle = _FakeHandle()
        bridge = RealHandleBridge(handle)
        adapter = PersistentExtractionAdapter(session=bridge)

        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            batch=batch,
            attempt_count=0,
            max_attempts=1,
            parameters_json={
                "patient_record": SENSITIVE_PATIENT_SENTINEL,
                "intent": "full_sync",
                "start_date": "2026-01-01",
                "end_date": "2026-01-15",
            },
        )

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=adapter
        ), patch.object(
            RealHandleBridge, "navigate_to_admissions", return_value=True
        ), patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs_persistent_session.persist_admissions_snapshot",
            return_value=(MagicMock(), {"seen": 1, "created": 1, "updated": 0}),
        ), caplog.at_level("WARNING"):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.failure_reason == "timeout"
        assert _FakePdfPage.content_calls == 0

        latest = (
            IngestionRunAttempt.objects.filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        assert latest is not None
        ev_stage = IngestionRunStageMetric.objects.get(
            run=run, stage_name="evolution_extraction"
        )

        sentinels = [
            SENSITIVE_URL_SENTINEL,
            SENSITIVE_COOKIE_SENTINEL,
            SENSITIVE_PATIENT_SENTINEL,
            SENSITIVE_ADMISSION_KEY_SENTINEL,
            SENSITIVE_SELECTOR_SENTINEL,
        ]
        for blob in [
            run.error_message or "",
            latest.error_message or "",
            str(ev_stage.details_json or {}),
        ]:
            for s in sentinels:
                assert s not in blob
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            for s in sentinels:
                assert s not in stream
        for record in caplog.records:
            text = record.getMessage()
            for s in sentinels:
                assert s not in text

    def test_pdf_url_resolution_timeout_records_timeout_category(
        self, caplog, capsys
    ):
        """D19/R3: a full command -> adapter -> bridge -> EvolutionPdfFlow
        chain whose PDF URL-resolution (bounded object attribute read) times
        out records failure_reason=timeout, timed_out=True. The timeout
        originates as the public real ``playwright.sync_api.TimeoutError``
        from a synthetic locator fake. No Chromium is launched."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        from apps.ingestion.extractors.persistent_extraction_adapter import (
            PersistentExtractionAdapter,
        )
        from apps.ingestion.extractors.real_handle_bridge import RealHandleBridge
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        class _TimeoutAttrLocator:
            first = property(lambda self: self)

            def count(self) -> int:
                return 1

            def get_attribute(self, name, **kwargs):  # noqa: ARG002
                raise PlaywrightTimeoutError(
                    f"Timeout at {SENSITIVE_URL_SENTINEL} "
                    f"cookie={SENSITIVE_COOKIE_SENTINEL}"
                )

        class _FakePdfPage:
            context = MagicMock()
            url = "https://legacy/relatorioAnaEvoInternacaoPdf.xhtml"
            frames: list = []
            content_calls = 0

            def locator(self, selector):  # noqa: ARG002
                return _TimeoutAttrLocator()

            def content(self):  # type: ignore[no-untyped-def]
                _FakePdfPage.content_calls += 1
                raise AssertionError("page.content() must not be called")

        class _FakeHandle:
            def __init__(self):
                self._html = _build_admissions_html()

            def ensure_current_page(self):
                return _FakePdfPage()

            def is_connected(self):
                return True

            def get_page_html(self):
                return self._html

            def set_html(self, html):
                self._html = html

            def open_tab(self, url, *, timeout=120):  # noqa: ARG002
                return True

            def click_selector(self, selector):  # noqa: ARG002
                pass

            def get_tab_classes(self):
                return []

            def close_last_non_root_tab(self):
                pass

            def restart_browser(self):
                pass

            def shutdown(self):
                pass

        handle = _FakeHandle()
        bridge = RealHandleBridge(handle)
        adapter = PersistentExtractionAdapter(session=bridge)

        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            batch=batch,
            attempt_count=0,
            max_attempts=1,
            parameters_json={
                "patient_record": SENSITIVE_PATIENT_SENTINEL,
                "intent": "full_sync",
                "start_date": "2026-01-01",
                "end_date": "2026-01-15",
            },
        )

        with patch.object(
            PersistentWorkerCommand, "_create_adapter", return_value=adapter
        ), patch.object(
            RealHandleBridge, "navigate_to_admissions", return_value=True
        ), patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs_persistent_session.persist_admissions_snapshot",
            return_value=(MagicMock(), {"seen": 1, "created": 1, "updated": 0}),
        ), caplog.at_level("WARNING"):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True
        # The bounded locator path was used; the unbounded content() trap was
        # never tripped.
        assert _FakePdfPage.content_calls == 0

        latest = (
            IngestionRunAttempt.objects.filter(run=run)
            .order_by("-attempt_number")
            .first()
        )
        assert latest is not None
        assert latest.failure_reason == "timeout"
        assert latest.timed_out is True
        assert latest.error_message == safe_failure_text("timeout")

        ev_stage = IngestionRunStageMetric.objects.get(
            run=run, stage_name="evolution_extraction"
        )
        assert ev_stage.details_json["error_type"] == "timeout"
        assert ev_stage.details_json["error_message"] == safe_failure_text("timeout")

        for blob in [
            run.error_message or "",
            latest.error_message or "",
            str(ev_stage.details_json or {}),
        ]:
            assert SENSITIVE_URL_SENTINEL not in blob
            assert SENSITIVE_COOKIE_SENTINEL not in blob
            assert SENSITIVE_PATIENT_SENTINEL not in blob
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            assert SENSITIVE_URL_SENTINEL not in stream
            assert SENSITIVE_COOKIE_SENTINEL not in stream
            assert SENSITIVE_PATIENT_SENTINEL not in stream
        for record in caplog.records:
            text = record.getMessage()
            assert SENSITIVE_URL_SENTINEL not in text
            assert SENSITIVE_COOKIE_SENTINEL not in text
            assert SENSITIVE_PATIENT_SENTINEL not in text


def _build_admissions_html(admission_key: str = "ADM1") -> str:
    """Synthetic legacy page HTML with a valid session counter and an
    admission snapshot container (used by D8 command-level test)."""
    return (
        "<html><body>\n"
        '<div id="tempoSessao">'
        "Tempo: <span>00</span>:<span>29</span>:<span>01</span>"
        "</div>\n"
        '<div id="admission-snapshot-data">\n'
        f'[{{"admissionKey":"{admission_key}",'
        '"admissionStart":"2026-01-01",'
        '"admissionEnd":"","ward":"UTI","bed":"1"}]\n'
        "</div>\n"
        "</body></html>"
    )
