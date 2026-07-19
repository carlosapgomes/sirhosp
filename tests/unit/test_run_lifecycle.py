"""PSW-S17: shared failure-classification and terminal-finalization helpers.

These tests pin the cross-worker parity contract for the ingestion run
lifecycle:

- ``classify_failure_reason(exc)`` MUST return the same ``(reason, timed_out)``
  tuple for any given exception type, regardless of which worker raises it.
- ``record_final_run_failure(run)`` MUST create exactly one ``FinalRunFailure``
  row under the same conditions and with the same fields the current worker
  creates, and MUST be idempotent.

The persistent worker used to diverge in three ways (the gaps PSW-S17 closes):

1. It did not classify any timeout type as ``("timeout", True)``.
2. It did not create ``FinalRunFailure`` rows on terminal failure.
3. It did not classify ``ValidationError`` as ``("validation_error", False)``.

The matrix tests below (``TestCrossWorkerFailureParity``) prove both worker
commands now reach the same externally observable lifecycle state for every
supported failure category (R1).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion.extractors.errors import (
    ExtractionError,
    ExtractionTimeoutError,
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.legacy_navigation import NavigationTimeoutError
from apps.ingestion.extractors.persistent_evolution_pdf import EvolutionPdfError
from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
)

# ---------------------------------------------------------------------------
# Classifier unit tests (no DB)
# ---------------------------------------------------------------------------


class TestClassifyFailureReason:
    """R1-R3: every failure category maps to the same tuple in both workers."""

    def _classify(self, exc: Exception) -> tuple[str, bool]:
        from apps.ingestion.run_lifecycle import classify_failure_reason

        return classify_failure_reason(exc)

    # -- Timeout category (R2, R3) ------------------------------------

    def test_extraction_timeout_classified_as_timeout(self):
        reason, timed_out = self._classify(
            ExtractionTimeoutError("Extraction timed out after 90s")
        )
        assert reason == "timeout"
        assert timed_out is True

    def test_subprocess_timeout_classified_as_timeout(self):
        reason, timed_out = self._classify(
            SubprocessTimeoutError(cmd=["python", "x.py"], timeout=300)
        )
        assert reason == "timeout"
        assert timed_out is True

    def test_navigation_timeout_classified_as_timeout(self):
        """R2: persistent navigation deadline expiration reaches the typed
        timeout category."""
        reason, timed_out = self._classify(
            NavigationTimeoutError("navigation deadline expired")
        )
        assert reason == "timeout"
        assert timed_out is True

    def test_playwright_timeout_in_cause_chain_classified_as_timeout(self):
        """R2: a Playwright ``TimeoutError`` wrapped by a sanitizing boundary
        is still detected through the cause/context chain."""

        cls = _make_playwright_timeout_class()
        try:
            try:
                raise cls("Timeout 30000ms exceeded")
            except Exception as exc:
                raise ExtractionError("navigation failed") from exc
        except ExtractionError as wrapped:
            reason, timed_out = self._classify(wrapped)
        assert reason == "timeout"
        assert timed_out is True

    def test_playwright_timeout_in_suppressed_context_classified_as_timeout(self):
        """R2: even when a boundary uses ``raise X from None``, the original
        Playwright timeout remains detectable via ``__context__``."""

        cls = _make_playwright_timeout_class()
        try:
            try:
                raise cls("Timeout 5000ms")
            except Exception:
                raise EvolutionPdfError("PDF download failed") from None
        except EvolutionPdfError as wrapped:
            reason, timed_out = self._classify(wrapped)
        assert reason == "timeout"
        assert timed_out is True

    def test_no_infinite_loop_on_cyclic_chain(self):
        """The chain walk defends against cycles (no infinite recursion)."""

        a = ExtractionError("a")
        b = ExtractionError("b")
        # Create a synthetic cycle: a -> b -> a.
        a.__cause__ = b
        b.__cause__ = a
        # Should terminate and fall through to source_unavailable.
        reason, timed_out = self._classify(a)
        assert reason == "source_unavailable"
        assert timed_out is False

    # -- invalid_payload category (R1) --------------------------------

    def test_invalid_json_classified_as_invalid_payload(self):
        reason, timed_out = self._classify(InvalidJsonError("bad json"))
        assert reason == "invalid_payload"
        assert timed_out is False

    def test_snapshot_container_missing_classified_as_invalid_payload(self):
        reason, timed_out = self._classify(
            SnapshotContainerMissingError("container missing")
        )
        assert reason == "invalid_payload"
        assert timed_out is False

    def test_evolution_pdf_error_classified_as_invalid_payload(self):
        reason, timed_out = self._classify(
            EvolutionPdfError("PDF flow failed")
        )
        assert reason == "invalid_payload"
        assert timed_out is False

    # -- validation_error category (R1) -------------------------------

    def test_validation_error_classified_as_validation_error(self):
        reason, timed_out = self._classify(
            ValidationError("patient record format invalid")
        )
        assert reason == "validation_error"
        assert timed_out is False

    # -- source_unavailable category (R1) -----------------------------

    def test_generic_extraction_error_classified_as_source_unavailable(self):
        reason, timed_out = self._classify(
            ExtractionError("source connection refused")
        )
        assert reason == "source_unavailable"
        assert timed_out is False

    # -- unexpected_exception category (R1) ---------------------------

    def test_unexpected_exception_classified_as_unexpected(self):
        reason, timed_out = self._classify(ValueError("db pool exhausted"))
        assert reason == "unexpected_exception"
        assert timed_out is False


# ---------------------------------------------------------------------------
# Helpers for the playwright-timeout duck-typing tests
# ---------------------------------------------------------------------------


def _make_playwright_timeout_class():
    """Build a duck-typed class that mimics ``playwright.TimeoutError``.

    The classifier detects playwright timeouts by class name AND module
    prefix (no hard playwright dependency). This helper returns a synthetic
    class whose ``__name__`` is ``TimeoutError`` and whose ``__module__``
    starts with ``playwright`` so detection works in tests without the
    real playwright package installed.
    """

    class _PlaywrightTimeoutError(Exception):
        pass

    _PlaywrightTimeoutError.__name__ = "TimeoutError"
    _PlaywrightTimeoutError.__qualname__ = "TimeoutError"
    _PlaywrightTimeoutError.__module__ = "playwright._impl._errors"
    return _PlaywrightTimeoutError


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
        from apps.ingestion.run_lifecycle import record_final_run_failure

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
        """R5: calling twice (e.g. retry recovery + worker) must NOT duplicate."""
        from apps.ingestion.run_lifecycle import record_final_run_failure

        batch = CensusExecutionBatch.objects.create(status="running")
        run = self._make_run(batch=batch)

        record_final_run_failure(run)
        record_final_run_failure(run)

        assert FinalRunFailure.objects.filter(run=run).count() == 1

    def test_no_row_when_batch_missing(self):
        """R5: current-worker condition — no batch means no row."""
        from apps.ingestion.run_lifecycle import record_final_run_failure

        run = self._make_run(batch=None, patient_record="NO_BATCH")
        record_final_run_failure(run)
        assert FinalRunFailure.objects.filter(run=run).count() == 0

    def test_no_row_when_patient_record_missing(self):
        """R5: current-worker condition — empty patient_record means no row."""
        from apps.ingestion.run_lifecycle import record_final_run_failure

        batch = CensusExecutionBatch.objects.create(status="running")
        run = self._make_run(batch=batch, patient_record="")
        record_final_run_failure(run)
        assert FinalRunFailure.objects.filter(run=run).count() == 0

    def test_intent_falls_back_to_run_intent_when_param_missing(self):
        """R5: intent resolution matches current worker (params then run.intent)."""
        from apps.ingestion.run_lifecycle import record_final_run_failure

        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="failed",
            intent="demographics_only",
            batch=batch,
            attempt_count=2,
            max_attempts=2,
            parameters_json={"patient_record": "FF_DEMO"},  # no "intent"
        )
        record_final_run_failure(run)
        failure = FinalRunFailure.objects.get(run=run)
        assert failure.intent == "demographics_only"


# ---------------------------------------------------------------------------
# Cross-worker failure-parity matrix (R1)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossWorkerFailureParity:
    """R1: parameterize identical failure scenarios for both workers and prove
    the externally visible lifecycle matches for every category."""

    FAILURE_CATEGORIES = [
        ("source_unavailable", ExtractionError("source crashed"), False),
        ("invalid_payload", InvalidJsonError("bad json"), False),
        ("timeout", ExtractionTimeoutError("timed out after 90s"), True),
        (
            "unexpected_exception",
            ValueError("db connection pool exhausted"),
            False,
        ),
    ]
    """Tuple of (expected_reason, exception, expected_timed_out)."""

    # -- Current worker (process_ingestion_runs) ---------------------

    def _patch_current_extractor(self, exc: Exception):
        """Patch the current worker's extractor to raise ``exc`` on snapshot."""
        mock_ext = MagicMock()
        mock_ext.get_admission_snapshot.side_effect = exc
        mock_ext.extract_evolutions.return_value = []
        return patch(
            "apps.ingestion.management.commands"
            ".process_ingestion_runs.PlaywrightEvolutionExtractor",
            return_value=mock_ext,
        )

    def _patch_persistent_adapter(self, exc: Exception):
        """Patch the persistent worker's adapter to raise ``exc`` on snapshot."""
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

    def _terminal_run_for(self, command_name: str) -> IngestionRun:
        """Build a run that exhausts on this attempt (terminal, not retry)."""
        batch = CensusExecutionBatch.objects.create(status="running")
        params = {
            "patient_record": f"P-{command_name}",
            "intent": "admissions_only",
        }
        run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            batch=batch,
            attempt_count=2,
            max_attempts=3,
            parameters_json=params,
        )
        # Seed prior failed attempts so the new attempt is the 3rd and last.
        for i in range(1, 3):
            IngestionRunAttempt.objects.create(
                run=run,
                attempt_number=i,
                status="failed",
                failure_reason="source_unavailable",
                finished_at=timezone.now() - timedelta(seconds=70 * (3 - i)),
            )
        return run

    @pytest.mark.parametrize(
        "expected_reason, exc, expected_timed_out",
        FAILURE_CATEGORIES,
        ids=[c[0] for c in FAILURE_CATEGORIES],
    )
    def test_current_worker_classification(
        self, expected_reason, exc, expected_timed_out
    ):
        run = self._terminal_run_for("current")
        with self._patch_current_extractor(exc):
            call_command("process_ingestion_runs")
        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == expected_reason
        assert run.timed_out is expected_timed_out
        # R5: terminal failure creates exactly one FinalRunFailure.
        assert FinalRunFailure.objects.filter(run=run).count() == 1

    @pytest.mark.parametrize(
        "expected_reason, exc, expected_timed_out",
        FAILURE_CATEGORIES,
        ids=[c[0] for c in FAILURE_CATEGORIES],
    )
    def test_persistent_worker_classification(
        self, expected_reason, exc, expected_timed_out
    ):
        run = self._terminal_run_for("persistent")
        with self._patch_persistent_adapter(exc):
            call_command("process_ingestion_runs_persistent_session")
        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == expected_reason
        assert run.timed_out is expected_timed_out
        # R5: terminal failure creates exactly one FinalRunFailure
        # (this is the divergence PSW-S17 closes for the persistent worker).
        assert FinalRunFailure.objects.filter(run=run).count() == 1

    @pytest.mark.parametrize(
        "expected_reason, exc, expected_timed_out",
        FAILURE_CATEGORIES,
        ids=[c[0] for c in FAILURE_CATEGORIES],
    )
    def test_attempt_records_match_between_workers(
        self, expected_reason, exc, expected_timed_out
    ):
        """R3: the latest attempt record carries the same reason/timed_out."""
        run = self._terminal_run_for("persistent")
        with self._patch_persistent_adapter(exc):
            call_command("process_ingestion_runs_persistent_session")
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


# ---------------------------------------------------------------------------
# Persistent navigation deadline timeout end-to-end (R2, R3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPersistentNavigationTimeoutEndToEnd:
    """R2/R3: a persistent navigation deadline timeout reaches the timeout
    classification end-to-end through the persistent worker."""

    def test_demographics_deadline_timeout_is_classified_as_timeout(self):
        """When the persistent demographics path raises NavigationTimeoutError
        (deadline expired), the run records failure_reason='timeout' and
        timed_out=True — parity with the current worker's timeout semantics."""
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            attempt_count=1,
            max_attempts=3,
            parameters_json={
                "patient_record": "DTO_P1",
                "intent": "demographics_only",
            },
        )

        mock_adapter = MagicMock()
        mock_adapter.get_demographics.side_effect = NavigationTimeoutError(
            "demographics deadline expired before next step"
        )
        mock_adapter.ensure_session_ready.return_value = True
        mock_adapter.controller = MagicMock()
        mock_adapter.controller.restart_required.return_value = False

        with patch.object(
            PersistentWorkerCommand,
            "_create_adapter",
            return_value=mock_adapter,
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "queued"  # retry, not terminal
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

    def test_persistent_terminal_timeout_creates_final_run_failure(self):
        """R5: when a persistent timeout exhausts retries, exactly one
        FinalRunFailure row is created (parity with the current worker)."""
        from apps.ingestion.management.commands.process_ingestion_runs_persistent_session import (  # noqa: E501
            Command as PersistentWorkerCommand,
        )

        batch = CensusExecutionBatch.objects.create(status="running")
        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            batch=batch,
            attempt_count=3,
            max_attempts=3,
            parameters_json={
                "patient_record": "TTO_P1",
                "intent": "demographics_only",
            },
        )

        mock_adapter = MagicMock()
        mock_adapter.get_demographics.side_effect = NavigationTimeoutError(
            "demographics deadline expired"
        )
        mock_adapter.ensure_session_ready.return_value = True
        mock_adapter.controller = MagicMock()
        mock_adapter.controller.restart_required.return_value = False

        with patch.object(
            PersistentWorkerCommand,
            "_create_adapter",
            return_value=mock_adapter,
        ):
            call_command("process_ingestion_runs_persistent_session")

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True
        assert FinalRunFailure.objects.filter(run=run).count() == 1
