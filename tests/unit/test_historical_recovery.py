"""Unit tests for RPSA-S7 recovery integration with zero confirmation.

Proves, with mocked extractor services only, that the existing recovery
orchestrator already satisfies the confirmed-zero contract with ZERO
structural changes:

- an unconfirmed zero surfaces as ``success=False``
  (``failure_reason="zero_unconfirmed"``) and is therefore a failed step
  with normal retry limits;
- a confirmed-zero result is a successful step and is never re-run by
  retry rounds;
- the new zero metadata propagates aggregate-safely through the existing
  ``metrics`` pass-through (``zero_confirmed`` / ``attempt_count`` keys);
- failure metadata stays structured and credential-safe.

All extractor services are mocked. No Playwright subprocesses and no
database are required.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from apps.ingestion.historical_extraction import ExtractionResult
from apps.ingestion.historical_recovery import (
    RecoveryPlan,
    execute_recovery_plan,
)

_TARGET = date(2026, 6, 1)
_DATE_LABEL = "01/06/2026"


# ---------------------------------------------------------------------------
# Fake service helpers
# ---------------------------------------------------------------------------


class ScriptedService:
    """Callable returning a scripted result per invocation and counting calls."""

    def __init__(self, name: str, results: list[ExtractionResult]):
        self.name = name
        self.results = list(results)
        self.calls = 0

    def __call__(self, date_str: str, headless: bool = True) -> ExtractionResult:
        self.calls += 1
        index = min(self.calls - 1, len(self.results) - 1)
        return self.results[index]


def _unconfirmed_zero_result() -> ExtractionResult:
    return ExtractionResult(
        extraction_type="discharge_extraction",
        target_start=_TARGET,
        target_end=_TARGET,
        success=False,
        failure_reason="zero_unconfirmed",
        error_message=(
            "Zero-row discharge report could not be confirmed by an "
            "independent second attempt."
        ),
        metrics={},
        ingestion_run_id=11,
        zero_confirmed=False,
        attempt_count=2,
    )


def _confirmed_zero_result() -> ExtractionResult:
    return ExtractionResult(
        extraction_type="discharge_extraction",
        target_start=_TARGET,
        target_end=_TARGET,
        success=True,
        metrics={"total_records": 0, "zero_confirmed": True, "attempt_count": 2},
        ingestion_run_id=12,
        zero_confirmed=True,
        attempt_count=2,
    )


def _rows_result() -> ExtractionResult:
    return ExtractionResult(
        extraction_type="discharge_extraction",
        target_start=_TARGET,
        target_end=_TARGET,
        success=True,
        metrics={"total_records": 3, "zero_confirmed": False, "attempt_count": 1},
        ingestion_run_id=13,
        zero_confirmed=False,
        attempt_count=1,
    )


def _plan(extractors: list[str], **kwargs) -> RecoveryPlan:
    return RecoveryPlan(dates=[_TARGET], extractors=extractors, **kwargs)


# =========================================================================
# Unconfirmed zero is a failed step
# =========================================================================


class TestUnconfirmedZeroIsFailedStep:
    """``success=False`` keeps the spec scenario 'unconfirmed zero is failed'."""

    def test_unconfirmed_zero_maps_to_failed_step(self):
        service = ScriptedService("discharges", [_unconfirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"]),
            service_registry={"discharges": service},
        )

        assert result.success is False
        assert result.failed_steps == 1
        step = result.steps[0]
        assert step.success is False
        assert step.failure_reason == "zero_unconfirmed"
        assert step.extraction_type == "discharge_extraction"

    def test_unconfirmed_zero_normal_retry_limits_apply(self):
        """The unconfirmed-zero step is retried per max_retries and stays failed."""
        service = ScriptedService("discharges", [_unconfirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"], max_retries=2),
            service_registry={"discharges": service},
        )

        assert result.success is False
        assert result.failed_steps == 1
        assert result.retry_rounds_used == 2
        assert result.retry_attempts == 2
        assert service.calls == 3  # initial + 2 retries

    def test_unconfirmed_zero_recovered_by_retry_succeeds(self):
        """A retry that returns confirmed zero turns the run successful."""
        service = ScriptedService(
            "discharges", [_unconfirmed_zero_result(), _confirmed_zero_result()]
        )
        result = execute_recovery_plan(
            _plan(["discharges"], max_retries=3),
            service_registry={"discharges": service},
        )

        assert result.success is True
        assert result.failed_steps == 0
        assert result.retry_rounds_used == 1
        assert service.calls == 2
        # The final step reflects the confirmed-zero retry outcome.
        assert result.steps[0].success is True
        assert result.steps[0].failure_reason == ""
        assert result.steps[0].metrics["zero_confirmed"] is True

    def test_unconfirmed_zero_does_not_fail_unrelated_steps(self):
        """A failed discharge step continues the batch (partial-failure)."""
        ok_admissions = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=_TARGET,
            target_end=_TARGET,
            success=True,
            metrics={"total_records": 5},
        )
        registry: dict[str, Callable] = {
            "discharges": ScriptedService("discharges", [_unconfirmed_zero_result()]),
            "admissions": ScriptedService("admissions", [ok_admissions]),
        }
        result = execute_recovery_plan(
            _plan(["discharges", "admissions"], max_retries=0),
            service_registry=registry,
        )

        assert result.total_steps == 2
        assert result.steps[0].success is False
        assert result.steps[1].success is True
        assert result.successful_steps == 1
        assert result.failed_steps == 1


# =========================================================================
# Confirmed zero is successful and never retried
# =========================================================================


class TestConfirmedZeroNotRetried:
    """A confirmed-zero success must not be re-run by retry rounds."""

    def test_confirmed_zero_is_successful_step(self):
        service = ScriptedService("discharges", [_confirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"]),
            service_registry={"discharges": service},
        )

        assert result.success is True
        assert result.failed_steps == 0
        assert result.steps[0].success is True
        assert service.calls == 1

    def test_confirmed_zero_never_triggers_retry_rounds(self):
        """Retry machinery stays idle when the only step confirmed zero."""
        service = ScriptedService("discharges", [_confirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"], max_retries=3),
            service_registry={"discharges": service},
        )

        assert result.retry_rounds_used == 0
        assert result.retry_attempts == 0
        assert service.calls == 1

    def test_retry_round_does_not_rerun_confirmed_zero_step(self):
        """With other failures present, the confirmed-zero step is skipped."""
        fail_admissions = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=_TARGET,
            target_end=_TARGET,
            success=False,
            failure_reason="timeout",
            error_message="Timed out",
        )
        registry: dict[str, Callable] = {
            "discharges": ScriptedService("discharges", [_confirmed_zero_result()]),
            "admissions": ScriptedService(
                "admissions", [fail_admissions, fail_admissions]
            ),
        }
        result = execute_recovery_plan(
            _plan(["discharges", "admissions"], max_retries=2),
            service_registry=registry,
        )

        # Only the failed admissions step was retried.
        assert result.retry_rounds_used == 2
        assert result.retry_attempts == 2
        assert registry["discharges"].calls == 1
        assert registry["admissions"].calls == 3  # initial + 2 retries
        assert result.steps[0].metrics["zero_confirmed"] is True
        assert result.success is False


# =========================================================================
# Aggregate-safe metadata propagation
# =========================================================================


class TestZeroMetadataPropagation:
    """New metadata reaches step summaries via the existing pass-through."""

    def test_confirmed_zero_metadata_passthrough(self):
        service = ScriptedService("discharges", [_confirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"]),
            service_registry={"discharges": service},
        )

        step = result.steps[0]
        assert step.metrics["zero_confirmed"] is True
        assert step.metrics["attempt_count"] == 2
        assert step.metrics["total_records"] == 0
        assert step.ingestion_run_id == 12

    def test_unconfirmed_zero_metadata_passthrough(self):
        service = ScriptedService("discharges", [_unconfirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"], max_retries=0),
            service_registry={"discharges": service},
        )

        step = result.steps[0]
        # The real unconfirmed-zero ExtractionResult carries metrics={}
        # (durable metadata lives in stage metrics, not on the result);
        # the orchestrator copies it verbatim.
        assert step.metrics == {}
        assert step.ingestion_run_id == 11

    def test_rows_metadata_passthrough(self):
        service = ScriptedService("discharges", [_rows_result()])
        result = execute_recovery_plan(
            _plan(["discharges"]),
            service_registry={"discharges": service},
        )

        step = result.steps[0]
        assert step.metrics["zero_confirmed"] is False
        assert step.metrics["attempt_count"] == 1
        assert step.metrics["total_records"] == 3

    def test_unconfirmed_zero_error_message_is_structured_and_safe(self):
        """Failure metadata stays structured and credential-safe."""
        service = ScriptedService("discharges", [_unconfirmed_zero_result()])
        result = execute_recovery_plan(
            _plan(["discharges"], max_retries=0),
            service_registry={"discharges": service},
        )

        step = result.steps[0]
        assert "zero_unconfirmed" == step.failure_reason
        assert "password" not in step.error_message.lower()
        assert "secret" not in step.error_message.lower()
