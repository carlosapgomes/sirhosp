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
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # All 8 steps should have been executed despite the failure
        assert result.total_steps == 8
        assert result.failed_steps == 1
        assert result.successful_steps == 7
        assert result.success is False

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
