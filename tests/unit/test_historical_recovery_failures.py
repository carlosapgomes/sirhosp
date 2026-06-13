"""Tests for historical recovery failure aggregation, dry-run, and fail-fast.

Slice C3-S3 requirements (tasks.md 3.1-3.4):
- Dry-run planning: no services called, skipped steps with success=True.
- Default continue-on-failure aggregation across all dates/extractors.
- Fail-fast stops after the first failed step.
- Unexpected service exceptions become safe failed steps.
- Credential values are not leaked in error messages.

All extractor services are mocked. No Playwright subprocesses are launched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from apps.ingestion.historical_extraction import ExtractionResult
from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    RecoveryPlan,
    execute_recovery_plan,
)

# ---------------------------------------------------------------------------
# Fake service helpers
# ---------------------------------------------------------------------------


@dataclass
class CallRecord:
    """Record of a single fake service invocation."""

    date_str: str
    headless: bool


class FakeService:
    """Callable that records invocations and returns a canned result."""

    def __init__(self, name: str, result: ExtractionResult | None = None):
        self.name = name
        self.calls: list[CallRecord] = []
        self._result = result or ExtractionResult(
            extraction_type=f"{name}_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

    def __call__(self, date_str: str, headless: bool = True) -> ExtractionResult:
        self.calls.append(CallRecord(date_str=date_str, headless=headless))
        return self._result


def make_service_registry_for_test(
    results: dict[str, ExtractionResult] | None = None,
) -> tuple[dict[str, FakeService], dict[str, Callable]]:
    """Build a service registry of FakeService instances for testing.

    Returns (fake_services_by_name, registry_dict) so tests can inspect
    call records via the ``fake_services`` dict keyed by extractor name.
    """
    fakes: dict[str, FakeService] = {}
    registry: dict[str, Callable] = {}
    for name in DEFAULT_EXTRACTOR_ORDER:
        result = (results or {}).get(name)
        fakes[name] = FakeService(name=name, result=result)
        registry[name] = fakes[name]
    return fakes, registry


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


class TestDryRun:
    """Dry-run must never call extractor services."""

    def test_dry_run_returns_skipped_steps(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # All steps should be present
        assert result.total_steps == 4

        # All steps should be skipped with success=True
        for step in result.steps:
            assert step.skipped is True
            assert step.success is True

        # No service should have been called
        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 0, (
                f"Service '{name}' was called during dry run"
            )

    def test_dry_run_steps_have_empty_metrics(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        for step in result.steps:
            assert step.metrics == {}, f"Step {step.extractor} has non-empty metrics"

    def test_dry_run_steps_have_no_ingestion_run_id(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        for step in result.steps:
            assert step.ingestion_run_id is None

    def test_dry_run_over_multiple_dates(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 8  # 2 dates x 4 extractors
        for step in result.steps:
            assert step.skipped is True
            assert step.success is True

        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 0

    def test_dry_run_results_in_success(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is True
        assert result.skipped_steps == 4

    def test_dry_run_date_labels_are_correct(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        for step in result.steps:
            assert step.date_label == "01/06/2026"
            assert step.date == date(2026, 6, 1)

    def test_dry_run_with_subset_extractors(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["admissions", "deaths"],
            dry_run=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 2
        for step in result.steps:
            assert step.skipped is True
            assert step.success is True

        # Verify no services were called
        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 0

    def test_dry_run_skips_are_not_counted_as_failures(self):
        """Skipped dry-run steps should not make the result unsuccessful."""
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            dry_run=True,
        )
        fakes, registry = make_service_registry_for_test()
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is True
        assert result.failed_steps == 0


# ---------------------------------------------------------------------------
# Continue-on-failure tests (default behaviour)
# ---------------------------------------------------------------------------


class TestContinueOnFailure:
    """Default execution continues after failed service results."""

    def test_continues_after_single_failure(self):
        ok_result = ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )
        fail_result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
            error_message="Timed out",
        )
        results = {
            "discharges": ok_result,
            "admissions": fail_result,
            "deaths": ok_result,
            "official_census": ok_result,
        }
        fakes, registry = make_service_registry_for_test(results=results)
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # All 4 steps should have been executed
        assert result.total_steps == 4
        # Only admissions should be failed
        assert result.failed_steps == 1
        assert result.successful_steps == 3
        assert result.success is False

        # Verify the failed step
        fail_step = result.steps[1]
        assert fail_step.extractor == "admissions"
        assert fail_step.success is False
        assert fail_step.failure_reason == "timeout"

    def test_continues_after_multiple_failures(self):
        fail_result = ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="source_unavailable",
            error_message="Source system unavailable",
        )
        results = {
            "discharges": fail_result,
            "admissions": fail_result,
            "deaths": ExtractionResult(
                extraction_type="death_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            ),
            "official_census": fail_result,
        }
        fakes, registry = make_service_registry_for_test(results=results)
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 4
        assert result.failed_steps == 3
        assert result.successful_steps == 1
        assert result.success is False

    def test_continues_across_multiple_dates(self):
        # First date: first extractor fails; second date: all succeed
        # Use a call-counter pattern to control per-call results.
        call_counts: dict[str, int] = {}

        def make_service(
            name: str,
        ) -> Callable:
            def service_fn(date_str: str, headless: bool = True) -> ExtractionResult:
                call_counts.setdefault(name, 0)
                call_counts[name] += 1
                if name == "discharges" and call_counts[name] == 1:
                    return ExtractionResult(
                        extraction_type="discharge_extraction",
                        target_start=date(2026, 6, 1),
                        target_end=date(2026, 6, 1),
                        success=False,
                        failure_reason="timeout",
                        error_message="Timed out",
                    )
                return ExtractionResult(
                    extraction_type=f"{name}_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=True,
                )

            return service_fn

        registry: dict[str, Callable] = {
            name: make_service(name) for name in DEFAULT_EXTRACTOR_ORDER
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            max_retries=0,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # All 8 steps should have been executed despite the failure
        assert result.total_steps == 8
        assert result.failed_steps == 1
        assert result.successful_steps == 7
        assert result.success is False
        assert result.retry_rounds_used == 0
        assert result.retry_attempts == 0

    def test_all_succeed_is_successful(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is True
        assert result.failed_steps == 0


# ---------------------------------------------------------------------------
# Fail-fast tests
# ---------------------------------------------------------------------------


class TestFailFast:
    """Fail-fast stops after the first failed step."""

    def test_fail_fast_stops_after_service_failure(self):
        ok_result = ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )
        fail_result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
            error_message="Timed out",
        )
        results = {
            "discharges": ok_result,
            "admissions": fail_result,
            "deaths": ok_result,
            "official_census": ok_result,
        }
        fakes, registry = make_service_registry_for_test(results=results)
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Only 2 steps should have been executed (discharges succeeded, admissions failed -> stop)
        assert result.total_steps == 2
        assert result.failed_steps == 1
        assert result.successful_steps == 1

        # The remaining services after the failure should NOT have been called
        assert len(fakes["deaths"].calls) == 0
        assert len(fakes["official_census"].calls) == 0

    def test_fail_fast_with_first_step_failure(self):
        fail_result = ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="validation_error",
            error_message="Invalid date",
        )
        fakes, registry = make_service_registry_for_test(
            results={"discharges": fail_result}
        )
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Only 1 step (the failing one) should have been executed
        assert result.total_steps == 1
        assert result.failed_steps == 1
        assert result.successful_steps == 0

        # No other services called
        for name in ["admissions", "deaths", "official_census"]:
            assert len(fakes[name].calls) == 0

    def test_fail_fast_all_succeed_completes_all_steps(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # All 4 steps should complete when none fail
        assert result.total_steps == 4
        assert result.success is True
        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 1

    def test_fail_fast_across_multiple_dates(self):
        """Fail-fast should stop at the first failure even across dates."""
        call_count: dict[str, int] = {}

        def make_service(
            name: str,
        ) -> Callable:
            def service_fn(date_str: str, headless: bool = True) -> ExtractionResult:
                call_count.setdefault(name, 0)
                call_count[name] += 1
                # Second date, discharges fails
                if date_str == "02/06/2026" and name == "discharges":
                    return ExtractionResult(
                        extraction_type="discharge_extraction",
                        target_start=date(2026, 6, 2),
                        target_end=date(2026, 6, 2),
                        success=False,
                        failure_reason="timeout",
                        error_message="Timed out",
                    )
                return ExtractionResult(
                    extraction_type=f"{name}_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=True,
                )

            return service_fn

        registry: dict[str, Callable] = {
            name: make_service(name) for name in DEFAULT_EXTRACTOR_ORDER
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Day 1: all 4 successful. Day 2: discharges fails -> stop
        assert result.total_steps == 5
        assert result.failed_steps == 1
        assert result.successful_steps == 4

    def test_fail_fast_returns_nonzero_exit_equivalent(self):
        """Fail-fast result should indicate overall failure."""
        fail_result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
            error_message="Timed out",
        )
        results = {
            "discharges": ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            ),
            "admissions": fail_result,
        }
        fakes, registry = make_service_registry_for_test(results=results)
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges", "admissions"],
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)
        assert result.success is False


# ---------------------------------------------------------------------------
# Unexpected exception handling
# ---------------------------------------------------------------------------


class TestUnexpectedExceptions:
    """Unexpected Python exceptions become safe failed steps."""

    def test_exception_becomes_failed_step(self):
        def failing_service(date_str: str, headless: bool = True):
            raise RuntimeError("Something went wrong")

        registry = {"discharges": failing_service}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert len(result.steps) == 1
        step = result.steps[0]
        assert step.success is False
        assert step.failure_reason == "unexpected_error"

    def test_unexpected_exception_has_safe_message(self):
        def failing_service(date_str: str, headless: bool = True):
            raise RuntimeError("Something went wrong")

        registry = {"discharges": failing_service}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        # Must use a generic safe message, not raw traceback
        assert "RuntimeError" not in step.error_message
        assert "Something went wrong" not in step.error_message
        assert step.error_message == "Unexpected extractor failure."

    def test_exception_step_has_no_ingestion_run_id(self):
        def failing_service(date_str: str, headless: bool = True):
            raise ValueError("bad data")

        registry = {"discharges": failing_service}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert step.ingestion_run_id is None

    def test_exception_step_has_empty_metrics(self):
        def failing_service(date_str: str, headless: bool = True):
            raise ValueError("bad data")

        registry = {"discharges": failing_service}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert step.metrics == {}

    def test_exception_continues_by_default(self):
        """Default behaviour: continue after exception."""

        def failing_service(date_str: str, headless: bool = True):
            raise RuntimeError("fail")

        def ok_service(date_str: str, headless: bool = True):
            return ExtractionResult(
                extraction_type="admission_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry: dict[str, Callable] = {
            "discharges": failing_service,
            "admissions": ok_service,
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges", "admissions"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 2
        assert result.steps[0].success is False
        assert result.steps[1].success is True

    def test_exception_with_fail_fast_stops(self):
        """Fail-fast should stop after an exception."""

        def failing_service(date_str: str, headless: bool = True):
            raise RuntimeError("fail")

        def ok_service(date_str: str, headless: bool = True):
            return ExtractionResult(
                extraction_type="admission_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry: dict[str, Callable] = {
            "discharges": failing_service,
            "admissions": ok_service,
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges", "admissions"],
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 1
        assert result.steps[0].success is False
        assert result.steps[0].failure_reason == "unexpected_error"


# ---------------------------------------------------------------------------
# Credential safety tests
# ---------------------------------------------------------------------------


class TestCredentialSafety:
    """Exception messages must not leak credential-like values."""

    def test_credential_url_is_redacted(self):
        """A URL with embedded credentials must not appear in step error."""

        def service_with_credential_url(date_str: str, headless: bool = True):
            raise RuntimeError(
                "auth failed for postgresql://user:SECRET@host with --password SECRET"
            )

        registry = {"discharges": service_with_credential_url}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert step.success is False
        assert step.failure_reason == "unexpected_error"
        # The raw credential URL must NOT appear in error_message
        assert "SECRET" not in step.error_message
        assert "--password SECRET" not in step.error_message
        assert "postgresql://user:SECRET" not in step.error_message
        # The message should be the generic safe one
        assert step.error_message == "Unexpected extractor failure."

    def test_credential_in_exception_message_is_redacted(self):
        """Exception containing password in message must be redacted."""

        def service_with_password(date_str: str, headless: bool = True):
            raise RuntimeError(
                "Connection failed: password=supersecret, host=example.com"
            )

        registry = {"discharges": service_with_password}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert "supersecret" not in step.error_message
        assert step.error_message == "Unexpected extractor failure."

    def test_credential_in_env_var_name_is_redacted(self):
        """Exception containing env var with password must be redacted."""

        def service_with_env_credential(date_str: str, headless: bool = True):
            raise RuntimeError(
                "SOURCE_SYSTEM_PASSWORD=my_secret_key leaked in exception"
            )

        registry = {"discharges": service_with_env_credential}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert "my_secret_key" not in step.error_message
        assert step.error_message == "Unexpected extractor failure."

    def test_exception_with_sensitive_data_uses_generic_message(self):
        """All unexpected exceptions use the generic safe message."""

        def service_with_api_key(date_str: str, headless: bool = True):
            raise RuntimeError("API Key: sk-live-abcdef123456")

        registry = {"discharges": service_with_api_key}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert "sk-live-abcdef123456" not in step.error_message
        assert step.error_message == "Unexpected extractor failure."

    def test_different_exception_types_all_safe(self):
        """Multiple exception types all get generic safe messages."""

        def service_fn_factory(exception: Exception):
            def fn(date_str: str, headless: bool = True):
                raise exception

            return fn

        for exc_cls, exc_args in [
            (ValueError, ("invalid value",)),
            (KeyError, ("missing_key",)),
            (ConnectionError, ("connection refused",)),
            (TimeoutError, ("timed out",)),
            (RuntimeError, ("something broke",)),
            (OSError, ("permission denied",)),
        ]:
            registry = {"discharges": service_fn_factory(exc_cls(*exc_args))}
            plan = RecoveryPlan(
                dates=[date(2026, 6, 1)],
                extractors=["discharges"],
            )
            result = execute_recovery_plan(plan, service_registry=registry)

            step = result.steps[0]
            assert step.failure_reason == "unexpected_error"
            assert step.error_message == "Unexpected extractor failure."


# ---------------------------------------------------------------------------
# Combined scenarios
# ---------------------------------------------------------------------------


class TestCombinedScenarios:
    """Integration scenarios combining multiple failure modes."""

    def test_fail_fast_with_exception_stops_immediately(self):
        """Fail-fast and an exception in the second service stops execution."""

        def ok_service(date_str: str, headless: bool = True):
            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        def crash_service(date_str: str, headless: bool = True):
            raise RuntimeError("crash")

        def never_called(date_str: str, headless: bool = True):
            raise AssertionError("This service should not have been called")

        registry: dict[str, Callable] = {
            "discharges": ok_service,
            "admissions": crash_service,
            "deaths": never_called,
            "official_census": never_called,
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 2
        assert result.steps[0].success is True
        assert result.steps[1].success is False
        assert result.steps[1].failure_reason == "unexpected_error"
        assert result.steps[1].error_message == "Unexpected extractor failure."

    def test_fail_fast_with_service_failure_stops(self):
        """Fail-fast and a failed service result stops execution."""

        def ok_service(date_str: str, headless: bool = True):
            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        def fail_service(date_str: str, headless: bool = True):
            return ExtractionResult(
                extraction_type="admission_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=False,
                failure_reason="timeout",
                error_message="Timed out",
            )

        def never_called(date_str: str, headless: bool = True):
            raise AssertionError("This service should not have been called")

        registry: dict[str, Callable] = {
            "discharges": ok_service,
            "admissions": fail_service,
            "deaths": never_called,
            "official_census": never_called,
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 2
        assert result.steps[0].success is True
        assert result.steps[1].success is False
        assert result.steps[1].failure_reason == "timeout"

    def test_dry_run_is_not_affected_by_fail_fast(self):
        """Dry-run should produce all steps even when fail_fast is True."""
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=True,
            fail_fast=True,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 4
        for step in result.steps:
            assert step.skipped is True
        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 0


# ---------------------------------------------------------------------------
# Retry round tests
# ---------------------------------------------------------------------------


class TestRetryRounds:
    """End-of-batch retry for failed steps."""

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _make_persistent_fail(
        name: str,
    ) -> Callable[..., ExtractionResult]:
        """Create a service that always returns failure."""
        fail_result = ExtractionResult(
            extraction_type=f"{name}_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
            error_message="Timed out",
        )

        def fn(date_str: str, headless: bool = True) -> ExtractionResult:
            return fail_result

        return fn

    # -- test: retry after full batch ---------------------------------------

    def test_retry_failed_steps_after_full_batch(self):
        """Failed steps are retried after the full initial batch completes."""
        call_counts: dict[str, int] = {}

        def make_service(name: str) -> Callable:
            def fn(date_str: str, headless: bool = True) -> ExtractionResult:
                call_counts.setdefault(name, 0)
                call_counts[name] += 1
                # Fail only on first call for "admissions"
                if name == "admissions" and call_counts[name] == 1:
                    return ExtractionResult(
                        extraction_type="admission_extraction",
                        target_start=date(2026, 6, 1),
                        target_end=date(2026, 6, 1),
                        success=False,
                        failure_reason="timeout",
                        error_message="Timed out",
                    )
                return ExtractionResult(
                    extraction_type=f"{name}_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=True,
                )

            return fn

        registry: dict[str, Callable] = {
            name: make_service(name) for name in DEFAULT_EXTRACTOR_ORDER
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Initial batch: 4 steps. Retry round: 1 step (admissions).
        assert result.total_steps == 4
        assert result.success is True
        assert result.failed_steps == 0
        assert result.retry_rounds_used == 1
        assert result.retry_attempts == 1

        # Verify admissions was called twice (initial + retry)
        assert call_counts.get("admissions", 0) == 2
        # All other services called once
        for name in ["discharges", "deaths", "official_census"]:
            assert call_counts.get(name, 0) == 1, (
                f"{name} was called {call_counts.get(name, 0)} times"
            )

    def test_retry_does_not_rerun_successful_steps(self):
        """Successful steps are never retried, only failed ones."""
        call_counts: dict[str, int] = {}

        def make_service(name: str) -> Callable:
            def fn(date_str: str, headless: bool = True) -> ExtractionResult:
                call_counts.setdefault(name, 0)
                call_counts[name] += 1
                if name == "discharges" and call_counts[name] == 1:
                    return ExtractionResult(
                        extraction_type="discharge_extraction",
                        target_start=date(2026, 6, 1),
                        target_end=date(2026, 6, 1),
                        success=False,
                        failure_reason="timeout",
                        error_message="Timed out",
                    )
                return ExtractionResult(
                    extraction_type=f"{name}_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=True,
                )

            return fn

        registry: dict[str, Callable] = {
            name: make_service(name) for name in DEFAULT_EXTRACTOR_ORDER
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Only discharges was retried (once)
        assert result.retry_rounds_used == 1
        assert result.retry_attempts == 1
        assert call_counts.get("discharges", 0) == 2
        # Admissions, deaths, census called once each (initial batch only)
        for name in ["admissions", "deaths", "official_census"]:
            assert call_counts.get(name, 0) == 1, (
                f"{name} should not be retried, called {call_counts.get(name, 0)} times"
            )

    # -- test: retry success makes final result successful ------------------

    def test_retry_success_makes_final_result_successful(self):
        """When a retry succeeds, the final result is successful."""
        call_counts: dict[str, int] = {}

        def flaky_service(date_str: str, headless: bool = True) -> ExtractionResult:
            call_counts.setdefault("discharges", 0)
            call_counts["discharges"] += 1
            if call_counts["discharges"] == 1:
                return ExtractionResult(
                    extraction_type="discharge_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=False,
                    failure_reason="source_unavailable",
                    error_message="Source temporarily unavailable",
                )
            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry = {"discharges": flaky_service}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is True
        assert result.failed_steps == 0
        assert result.retry_rounds_used == 1
        # The final step in the list reflects the retry outcome (success)
        assert result.steps[0].success is True

    # -- test: failures after retry exhaustion ------------------------------

    def test_failures_after_retry_exhaustion_still_fail(self):
        """Failures persisting after all retry rounds still exit non-zero."""
        registry: dict[str, Callable] = {
            "discharges": self._make_persistent_fail("discharges"),
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is False
        assert result.failed_steps == 1
        # Initial batch (1) + 3 retry rounds = 4 attempts
        assert result.retry_rounds_used == 3
        assert result.retry_attempts == 3

    def test_retry_exhaustion_still_shows_failed_step(self):
        """After retry exhaustion, the step remains failed with correct reason."""
        registry: dict[str, Callable] = {
            "admissions": self._make_persistent_fail("admissions"),
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["admissions"],
            max_retries=2,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is False
        assert result.failed_steps == 1
        assert result.retry_rounds_used == 2
        # Final step still shows failure reason
        assert result.steps[0].success is False
        assert result.steps[0].failure_reason == "timeout"

    # -- test: max_retries 0 ------------------------------------------------

    def test_max_retries_zero_disables_retries(self):
        """max_retries=0 preserves original no-retry behavior."""
        registry: dict[str, Callable] = {
            "discharges": self._make_persistent_fail("discharges"),
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            max_retries=0,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is False
        assert result.failed_steps == 1
        assert result.retry_rounds_used == 0
        assert result.retry_attempts == 0

    # -- test: dry-run does not retry ---------------------------------------

    def test_dry_run_does_not_run_retries(self):
        """Dry-run must not execute retry rounds."""
        registry: dict[str, Callable] = {
            "discharges": self._make_persistent_fail("discharges"),
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            dry_run=True,
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Dry-run produces skipped steps, no failures, no retries
        assert result.total_steps == 1
        assert result.steps[0].skipped is True
        assert result.success is True
        assert result.retry_rounds_used == 0
        assert result.retry_attempts == 0

    # -- test: fail-fast does not retry -------------------------------------

    def test_fail_fast_does_not_run_retries(self):
        """Fail-fast must not execute retry rounds after a failure."""
        registry: dict[str, Callable] = {
            "discharges": self._make_persistent_fail("discharges"),
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            fail_fast=True,
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 1
        assert result.success is False
        assert result.failed_steps == 1
        assert result.retry_rounds_used == 0
        assert result.retry_attempts == 0

    # -- test: unexpected exception can be retried --------------------------

    def test_unexpected_exception_can_be_retried(self):
        """Unexpected exceptions on first call can succeed on retry."""
        call_counts: dict[str, int] = {}

        def flaky_crash_service(
            date_str: str, headless: bool = True
        ) -> ExtractionResult:
            call_counts.setdefault("deaths", 0)
            call_counts["deaths"] += 1
            if call_counts["deaths"] == 1:
                raise RuntimeError("Temporary crash")
            return ExtractionResult(
                extraction_type="death_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry = {"deaths": flaky_crash_service}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["deaths"],
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is True
        assert result.failed_steps == 0
        assert result.retry_rounds_used == 1
        assert result.retry_attempts == 1
        # Final step reflects retry success
        assert result.steps[0].success is True
        assert result.steps[0].failure_reason == ""

    def test_unexpected_exception_on_retry_still_credential_safe(self):
        """Exceptions during retry round are still credential-safe."""
        call_counts: dict[str, int] = {}

        def always_crash(
            date_str: str, headless: bool = True
        ) -> ExtractionResult:
            call_counts.setdefault("deaths", 0)
            call_counts["deaths"] += 1
            raise RuntimeError("password=secret_leaked")

        registry = {"deaths": always_crash}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["deaths"],
            max_retries=2,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is False
        assert result.failed_steps == 1
        assert result.retry_rounds_used == 2
        assert result.retry_attempts == 2
        # The error message must be safe
        for step in result.steps:
            assert "password" not in step.error_message.lower()
            assert "secret_leaked" not in step.error_message

    # -- test: retry over multiple dates ------------------------------------

    def test_retry_multiple_dates_fails_on_one_date(self):
        """Retry across multiple dates: only failed date steps are retried."""
        call_counts: dict[tuple[str, str], int] = {}

        def make_flaky(name: str) -> Callable:
            def fn(date_str: str, headless: bool = True) -> ExtractionResult:
                key = (date_str, name)
                call_counts[key] = call_counts.get(key, 0) + 1
                # Fail only on first call for discharges on 01/06
                if name == "discharges" and date_str == "01/06/2026":
                    if call_counts[key] == 1:
                        return ExtractionResult(
                            extraction_type="discharge_extraction",
                            target_start=date(2026, 6, 1),
                            target_end=date(2026, 6, 1),
                            success=False,
                            failure_reason="timeout",
                            error_message="Timed out",
                        )
                return ExtractionResult(
                    extraction_type=f"{name}_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=True,
                )

            return fn

        registry: dict[str, Callable] = {
            name: make_flaky(name) for name in DEFAULT_EXTRACTOR_ORDER
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Initial: 8 steps, 1 failure. Retry: 1 step (discharges on 01/06).
        assert result.total_steps == 8
        assert result.success is True
        assert result.failed_steps == 0
        assert result.retry_rounds_used == 1
        assert result.retry_attempts == 1

        # Verify only the failed step was retried
        assert call_counts.get(("01/06/2026", "discharges"), 0) == 2
        assert call_counts.get(("02/06/2026", "discharges"), 0) == 1
        for name in ["admissions", "deaths", "official_census"]:
            assert call_counts.get(("01/06/2026", name), 0) == 1
            assert call_counts.get(("02/06/2026", name), 0) == 1

    # -- test: retry rounds count -------------------------------------------

    def test_multiple_retry_rounds_accuracy(self):
        """Retry stops after max_retries rounds when failure persists."""
        registry: dict[str, Callable] = {
            "discharges": self._make_persistent_fail("discharges"),
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            max_retries=5,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is False
        assert result.failed_steps == 1
        assert result.retry_rounds_used == 5
        assert result.retry_attempts == 5

    def test_retry_stops_early_when_all_succeed(self):
        """Retry rounds stop early if all failed steps succeed on one round."""
        call_counts: dict[str, int] = {}

        def twice_fail_then_ok(
            date_str: str, headless: bool = True
        ) -> ExtractionResult:
            call_counts.setdefault("discharges", 0)
            call_counts["discharges"] += 1
            if call_counts["discharges"] <= 3:
                # Fail on initial batch + first 2 retry rounds
                return ExtractionResult(
                    extraction_type="discharge_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=False,
                    failure_reason="timeout",
                    error_message="Timed out",
                )
            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry = {"discharges": twice_fail_then_ok}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            max_retries=5,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Initial (fail) + 3 retries (fail, fail, succeed) = 4 calls total
        assert result.success is True
        assert result.failed_steps == 0
        assert result.retry_rounds_used == 3
        assert result.retry_attempts == 3
        assert call_counts.get("discharges", 0) == 4

    # -- test: summary includes retry info ----------------------------------

    def test_summary_includes_retry_info_when_retried(self):
        """Summary string includes retry rounds and attempts when retries occurred."""
        call_counts: dict[str, int] = {}

        def flaky(date_str: str, headless: bool = True) -> ExtractionResult:
            call_counts.setdefault("discharges", 0)
            call_counts["discharges"] += 1
            if call_counts["discharges"] == 1:
                return ExtractionResult(
                    extraction_type="discharge_extraction",
                    target_start=date(2026, 6, 1),
                    target_end=date(2026, 6, 1),
                    success=False,
                    failure_reason="timeout",
                    error_message="Timed out",
                )
            return ExtractionResult(
                extraction_type="discharge_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry = {"discharges": flaky}
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        summary = result.summary
        assert "Retry rounds:" in summary
        assert "Retry attempts:" in summary

    def test_summary_no_retry_info_when_not_retried(self):
        """Summary string does not include retry info when no retries occurred."""
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            max_retries=3,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        summary = result.summary
        assert "Retry" not in summary
