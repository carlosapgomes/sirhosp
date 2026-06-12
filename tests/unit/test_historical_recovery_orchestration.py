"""Tests for historical recovery service orchestration.

Slice C3-S2 requirements (tasks.md 2.1-2.4):
- Tests proving the orchestrator calls the four extractor services directly
  in default order.
- Tests proving selected extractor subsets run in deterministic default order.
- Tests proving no management-command boundary is used.
- Tests verifying correct date parameter passing per service.

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
    make_service_registry,
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
# Orchestration: default order
# ---------------------------------------------------------------------------


class TestDefaultOrder:
    """All four extractors in default order for a single date."""

    def test_all_extractors_called_for_single_date(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.success is True
        assert result.total_steps == 4

        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 1

    def test_calls_in_default_order(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Discharges first, then admissions, etc.
        step_extractors = [s.extractor for s in result.steps]
        assert step_extractors == DEFAULT_EXTRACTOR_ORDER

    def test_each_service_receives_correct_date_string(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        execute_recovery_plan(plan, service_registry=registry)

        for name in DEFAULT_EXTRACTOR_ORDER:
            records = fakes[name].calls
            assert len(records) == 1
            assert records[0].date_str == "01/06/2026"
            assert records[0].headless is True

    def test_headless_passed_through(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        execute_recovery_plan(plan, headless=False, service_registry=registry)

        for name in DEFAULT_EXTRACTOR_ORDER:
            assert fakes[name].calls[0].headless is False

    def test_result_contains_step_for_each_extractor(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert len(result.steps) == 4
        for i, name in enumerate(DEFAULT_EXTRACTOR_ORDER):
            step = result.steps[i]
            assert step.date == date(2026, 6, 1)
            assert step.date_label == "01/06/2026"
            assert step.extractor == name
            assert step.success is True
            assert step.skipped is False

    def test_result_preserves_extraction_type_from_service(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # FakeService generates extraction_type = f"{name}_extraction"
        expected_types = {
            "discharges": "discharges_extraction",
            "admissions": "admissions_extraction",
            "deaths": "deaths_extraction",
            "official_census": "official_census_extraction",
        }
        for step in result.steps:
            assert step.extraction_type == expected_types[step.extractor]


# ---------------------------------------------------------------------------
# Orchestration: selected subset
# ---------------------------------------------------------------------------


class TestSelectedSubset:
    """Selected extractor subset runs in deterministic default order."""

    def test_single_extractor(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["deaths"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 1
        assert result.steps[0].extractor == "deaths"
        assert len(fakes["deaths"].calls) == 1
        # Other services not called
        for name in ["discharges", "admissions", "official_census"]:
            assert len(fakes[name].calls) == 0

    def test_subset_preserves_default_order(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["official_census", "admissions"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Selected subset sorted by DEFAULT_EXTRACTOR_ORDER: admissions, then official_census
        assert len(result.steps) == 2
        assert result.steps[0].extractor == "admissions"
        assert result.steps[1].extractor == "official_census"

    def test_subset_with_two_consecutive_extractors(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["admissions", "discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert len(result.steps) == 2
        assert result.steps[0].extractor == "discharges"
        assert result.steps[1].extractor == "admissions"


# ---------------------------------------------------------------------------
# Orchestration: multiple dates
# ---------------------------------------------------------------------------


class TestMultipleDates:
    """Orchestration across multiple dates."""

    def test_two_dates_all_extractors(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 8  # 2 dates x 4 extractors
        assert result.success is True

        for name in DEFAULT_EXTRACTOR_ORDER:
            assert len(fakes[name].calls) == 2

    def test_two_dates_correct_date_strings(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        execute_recovery_plan(plan, service_registry=registry)

        # Each service should receive both dates in order
        for name in DEFAULT_EXTRACTOR_ORDER:
            records = fakes[name].calls
            assert records[0].date_str == "01/06/2026"
            assert records[1].date_str == "02/06/2026"

    def test_two_dates_step_order(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        # Steps: day1 discharges, day1 admissions, ..., day2 discharges, ...
        # i.e. for each date, iterate over extractors
        assert result.steps[0].date == date(2026, 6, 1)
        assert result.steps[0].extractor == "discharges"
        assert result.steps[1].date == date(2026, 6, 1)
        assert result.steps[1].extractor == "admissions"
        assert result.steps[4].date == date(2026, 6, 2)
        assert result.steps[4].extractor == "discharges"

    def test_run_result_dates_from_plan(self):
        fakes, registry = make_service_registry_for_test()
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 3)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)
        assert result.start_date == date(2026, 6, 1)
        assert result.end_date == date(2026, 6, 3)


# ---------------------------------------------------------------------------
# Orchestration: no management command boundary
# ---------------------------------------------------------------------------


class TestNoManagementCommandBoundary:
    """Orchestrator calls service functions directly, not management commands."""

    def test_does_not_import_management_modules(self):
        """The orchestrator should not reference call_command or subprocess."""
        import inspect

        import apps.ingestion.historical_recovery as mod

        source = inspect.getsource(mod)
        assert "call_command" not in source
        assert "subprocess" not in source
        assert "management" not in source.lower() or "call_command" not in source

    def test_registry_contains_callables_not_management_commands(self):
        """Each entry in the default registry is a callable function."""
        registry = make_service_registry()
        for name in DEFAULT_EXTRACTOR_ORDER:
            assert callable(registry[name])
            assert not hasattr(registry[name], "add_arguments")


# ---------------------------------------------------------------------------
# Orchestration: service result passthrough
# ---------------------------------------------------------------------------


class TestResultPassthrough:
    """Orchestrator faithfully passes ExtractionResult fields to RecoveryStepResult."""

    def test_failed_service_result_maps_to_failed_step(self):
        fail_result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
            error_message="Subprocess timed out",
            metrics={"attempts": 1},
        )
        fakes, registry = make_service_registry_for_test(
            results={"admissions": fail_result}
        )
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["admissions"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert len(result.steps) == 1
        step = result.steps[0]
        assert step.success is False
        assert step.failure_reason == "timeout"
        assert step.error_message == "Subprocess timed out"

    def test_service_metrics_preserved_in_step(self):
        ok_result = ExtractionResult(
            extraction_type="discharge_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
            metrics={"total_records": 42, "parse_errors": 0},
            ingestion_run_id=99,
        )
        fakes, registry = make_service_registry_for_test(
            results={"discharges": ok_result}
        )
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        step = result.steps[0]
        assert step.success is True
        assert step.metrics == {"total_records": 42, "parse_errors": 0}
        assert step.ingestion_run_id == 99

    def test_default_result_not_modified(self):
        """Orchestrator should not mutate the service result object."""
        from copy import deepcopy

        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
            metrics={"total_records": 5},
        )
        result_copy = deepcopy(result)
        fakes, registry = make_service_registry_for_test(
            results={"deaths": result}
        )
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["deaths"],
        )
        execute_recovery_plan(plan, service_registry=registry)

        # Original result unchanged
        assert result.extraction_type == result_copy.extraction_type
        assert result.success == result_copy.success
        assert result.metrics == result_copy.metrics


# ---------------------------------------------------------------------------
# Service registry construction
# ---------------------------------------------------------------------------


class TestMakeServiceRegistry:
    """Default service registry lazily imports real service functions."""

    def test_returns_dict_with_all_extractors(self):
        registry = make_service_registry()
        assert set(registry.keys()) == set(DEFAULT_EXTRACTOR_ORDER)

    def test_each_entry_is_callable(self):
        registry = make_service_registry()
        for name in DEFAULT_EXTRACTOR_ORDER:
            assert callable(registry[name])

    def test_registry_not_empty(self):
        registry = make_service_registry()
        assert len(registry) == 4


# ---------------------------------------------------------------------------
# Error handling: exceptions
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    """Unexpected exceptions from services are caught and recorded."""

    def test_exception_in_service_becomes_failed_step(self):
        def failing_service(date_str: str, headless: bool = True):
            raise RuntimeError("Unexpected error")

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
        assert step.error_message == "Unexpected extractor failure."

    def test_exception_does_not_abort_other_steps(self):
        """Default behaviour: continue after exception."""
        def ok(date_str: str, headless: bool = True):
            return ExtractionResult(
                extraction_type="admission_extraction",
                target_start=date(2026, 6, 1),
                target_end=date(2026, 6, 1),
                success=True,
            )

        registry = {
            "discharges": lambda date_str, **kw: (_ for _ in ()).throw(  # noqa: E731
                RuntimeError("fail")
            ),
            "admissions": ok,
        }
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=["discharges", "admissions"],
        )
        result = execute_recovery_plan(plan, service_registry=registry)

        assert result.total_steps == 2
        assert result.steps[0].success is False
        assert result.steps[1].success is True
        assert result.failed_steps == 1
        assert result.success is False  # at least one failure
