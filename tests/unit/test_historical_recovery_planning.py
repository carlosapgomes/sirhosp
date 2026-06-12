"""Tests for historical recovery planning and result contracts.

Slice C3-S1 requirements (tasks.md 1.1):
- Tests for date parsing (DD/MM/AAAA) and inclusive range planning
- Tests for invalid date input and end-before-start ranges
- Tests for ambiguous date argument detection
- Tests for extractor selection ordering (default + subset)

These tests do NOT call extractor services. They operate purely on
planning and contract dataclasses.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    RecoveryPlan,
    RecoveryRunResult,
    RecoveryStepResult,
    _parse_date,
    build_date_range,
    validate_extractors,
)

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


class TestParseDate:
    """Parsing DD/MM/AAAA format strings to datetime.date."""

    def test_parses_valid_date(self):
        assert _parse_date("01/06/2026") == date(2026, 6, 1)

    def test_parses_end_of_month(self):
        assert _parse_date("30/04/2026") == date(2026, 4, 30)

    def test_parses_february_leap_year(self):
        assert _parse_date("29/02/2024") == date(2024, 2, 29)

    def test_parses_first_day_of_year(self):
        assert _parse_date("01/01/2026") == date(2026, 1, 1)

    def test_parses_last_day_of_year(self):
        assert _parse_date("31/12/2026") == date(2026, 12, 31)

    def test_rejects_invalid_date(self):
        with pytest.raises(ValueError, match="31/02/2026"):
            _parse_date("31/02/2026")

    def test_rejects_garbage_string(self):
        with pytest.raises(ValueError, match="not-a-date"):
            _parse_date("not-a-date")

    def test_rejects_wrong_format(self):
        with pytest.raises(ValueError, match="2026-06-01"):
            _parse_date("2026-06-01")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            _parse_date("")

    def test_rejects_non_leap_february_29(self):
        with pytest.raises(ValueError, match="29/02/2023"):
            _parse_date("29/02/2023")

    def test_rejects_day_out_of_range(self):
        with pytest.raises(ValueError, match="32/01/2026"):
            _parse_date("32/01/2026")

    def test_rejects_month_out_of_range(self):
        with pytest.raises(ValueError, match="01/13/2026"):
            _parse_date("01/13/2026")


# ---------------------------------------------------------------------------
# Date range planning (inclusive)
# ---------------------------------------------------------------------------


class TestBuildDateRange:
    """Inclusive date range generation."""

    def test_single_date_range(self):
        d = date(2026, 6, 1)
        assert build_date_range(d, d) == [d]

    def test_inclusive_range_multiple_days(self):
        start = date(2026, 6, 1)
        end = date(2026, 6, 3)
        expected = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]
        assert build_date_range(start, end) == expected

    def test_range_across_month_boundary(self):
        start = date(2026, 1, 30)
        end = date(2026, 2, 2)
        expected = [
            date(2026, 1, 30),
            date(2026, 1, 31),
            date(2026, 2, 1),
            date(2026, 2, 2),
        ]
        assert build_date_range(start, end) == expected

    def test_range_across_year_boundary(self):
        start = date(2026, 12, 30)
        end = date(2027, 1, 2)
        expected = [
            date(2026, 12, 30),
            date(2026, 12, 31),
            date(2027, 1, 1),
            date(2027, 1, 2),
        ]
        assert build_date_range(start, end) == expected

    def test_rejects_end_before_start(self):
        start = date(2026, 6, 10)
        end = date(2026, 6, 1)
        with pytest.raises(ValueError, match="before start"):
            build_date_range(start, end)


# ---------------------------------------------------------------------------
# RecoveryStepResult contract
# ---------------------------------------------------------------------------


class TestRecoveryStepResult:
    """Per-date/per-extractor step result contract."""

    def test_successful_step(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="discharges",
            success=True,
            extraction_type="discharge_extraction",
        )
        assert result.date == date(2026, 6, 1)
        assert result.date_label == "01/06/2026"
        assert result.extractor == "discharges"
        assert result.success is True
        assert result.extraction_type == "discharge_extraction"
        assert result.skipped is False
        assert result.failure_reason == ""
        assert result.error_message == ""
        assert result.ingestion_run_id is None

    def test_failed_step(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="deaths",
            success=False,
            extraction_type="death_extraction",
            failure_reason="timeout",
            error_message="Subprocess timed out",
        )
        assert result.success is False
        assert result.failure_reason == "timeout"
        assert result.error_message == "Subprocess timed out"
        assert result.skipped is False

    def test_skipped_dry_run_step(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="admissions",
            success=True,
            extraction_type="admission_extraction",
            skipped=True,
        )
        assert result.success is True
        assert result.skipped is True

    def test_step_with_ingestion_run_id(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="official_census",
            success=True,
            extraction_type="official_census_extraction",
            ingestion_run_id=42,
        )
        assert result.ingestion_run_id == 42

    def test_step_is_dataclass(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="discharges",
            success=True,
            extraction_type="discharge_extraction",
        )
        assert hasattr(result, "__dataclass_fields__")

    def test_repr_includes_key_fields(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="admissions",
            success=True,
            extraction_type="admission_extraction",
        )
        rep = repr(result)
        assert "RecoveryStepResult" in rep
        assert "admissions" in rep
        assert "01/06/2026" in rep
        assert "success=True" in rep

    def test_metrics_defaults_to_empty_dict(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="discharges",
            success=True,
            extraction_type="discharge_extraction",
        )
        assert result.metrics == {}
        assert isinstance(result.metrics, dict)

    def test_default_metrics_instances_are_independent(self):
        a = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="discharges",
            success=True,
            extraction_type="discharge_extraction",
        )
        b = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="admissions",
            success=True,
            extraction_type="admission_extraction",
        )
        # Frozen dataclass + field(default_factory=dict) guarantees
        # each instance gets its own empty dict.
        assert a.metrics is not b.metrics

    def test_explicit_metrics_are_preserved(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="official_census",
            success=True,
            extraction_type="official_census_extraction",
            metrics={"total_records": 15},
        )
        assert result.metrics == {"total_records": 15}

    def test_metrics_can_include_multiple_counters(self):
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="deaths",
            success=True,
            extraction_type="death_extraction",
            metrics={"total_records": 3, "parse_errors": 0},
        )
        assert result.metrics["total_records"] == 3
        assert result.metrics["parse_errors"] == 0

    def test_metrics_on_failed_step(self):
        """A failed step can carry partial metrics from the service result."""
        result = RecoveryStepResult(
            date=date(2026, 6, 1),
            date_label="01/06/2026",
            extractor="admissions",
            success=False,
            extraction_type="admission_extraction",
            failure_reason="timeout",
            metrics={"attempts": 1},
        )
        assert result.metrics == {"attempts": 1}


# ---------------------------------------------------------------------------
# RecoveryRunResult contract
# ---------------------------------------------------------------------------


class TestRecoveryRunResult:
    """Aggregated run result with per-step details."""

    def test_all_successful_steps(self):
        steps = [
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="discharges",
                success=True,
                extraction_type="discharge_extraction",
            ),
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="admissions",
                success=True,
                extraction_type="admission_extraction",
            ),
        ]
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=steps,
        )
        assert result.success is True
        assert result.total_steps == 2
        assert result.successful_steps == 2
        assert result.failed_steps == 0
        assert result.skipped_steps == 0

    def test_some_failed_steps(self):
        steps = [
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="discharges",
                success=True,
                extraction_type="discharge_extraction",
            ),
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="admissions",
                success=False,
                extraction_type="admission_extraction",
                failure_reason="timeout",
                error_message="Timed out",
            ),
        ]
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=steps,
        )
        assert result.success is False
        assert result.total_steps == 2
        assert result.successful_steps == 1
        assert result.failed_steps == 1
        assert result.skipped_steps == 0

    def test_with_skipped_dry_run_steps(self):
        steps = [
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="discharges",
                success=True,
                extraction_type="discharge_extraction",
                skipped=True,
            ),
        ]
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=steps,
        )
        assert result.success is True
        assert result.total_steps == 1
        assert result.successful_steps == 1
        assert result.skipped_steps == 1

    def test_mixed_skipped_and_failed(self):
        steps = [
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="discharges",
                success=True,
                extraction_type="discharge_extraction",
            ),
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="admissions",
                success=False,
                extraction_type="admission_extraction",
                failure_reason="timeout",
                error_message="Timed out",
            ),
            RecoveryStepResult(
                date=date(2026, 6, 2),
                date_label="02/06/2026",
                extractor="deaths",
                success=True,
                extraction_type="death_extraction",
                skipped=True,
            ),
        ]
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            steps=steps,
        )
        assert result.success is False  # at least one real failure
        assert result.total_steps == 3
        assert result.successful_steps == 2
        assert result.failed_steps == 1
        assert result.skipped_steps == 1

    def test_empty_steps_is_successful(self):
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=[],
        )
        assert result.success is True
        assert result.total_steps == 0

    def test_range_dates(self):
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 3),
            steps=[],
        )
        assert result.start_date == date(2026, 6, 1)
        assert result.end_date == date(2026, 6, 3)

    def test_summary_string(self):
        steps = [
            RecoveryStepResult(
                date=date(2026, 6, 1),
                date_label="01/06/2026",
                extractor="discharges",
                success=True,
                extraction_type="discharge_extraction",
            ),
        ]
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=steps,
        )
        summary = result.summary
        assert "Days: 1" in summary
        assert "Succeeded: 1" in summary
        assert isinstance(summary, str)
        assert len(summary) > 0


# ---------------------------------------------------------------------------
# Extractor ordering
# ---------------------------------------------------------------------------


class TestExtractorDefaultOrder:
    """Default extractor order and subset ordering."""

    def test_default_order_is_correct(self):
        assert DEFAULT_EXTRACTOR_ORDER == [
            "discharges",
            "admissions",
            "deaths",
            "official_census",
        ]

    def test_all_extractors_validated_and_ordered(self):
        result = validate_extractors(["admissions", "discharges"])
        assert result == ["discharges", "admissions"]

    def test_subset_preserves_default_order(self):
        result = validate_extractors(["official_census", "admissions"])
        assert result == ["admissions", "official_census"]

    def test_single_extractor(self):
        result = validate_extractors(["deaths"])
        assert result == ["deaths"]

    def test_all_four_extractors_in_default_order(self):
        result = validate_extractors(["deaths", "admissions", "discharges", "official_census"])
        assert result == DEFAULT_EXTRACTOR_ORDER

    def test_empty_list_returns_all(self):
        result = validate_extractors([])
        assert result == DEFAULT_EXTRACTOR_ORDER

    def test_none_returns_all(self):
        result = validate_extractors(None)
        assert result == DEFAULT_EXTRACTOR_ORDER

    def test_rejects_unknown_extractor(self):
        with pytest.raises(ValueError, match="Unknown extractor"):
            validate_extractors(["admissions", "invalid_extractor"])

    def test_rejects_all_unknown(self):
        with pytest.raises(ValueError, match="Unknown extractor"):
            validate_extractors(["bogus"])


# ---------------------------------------------------------------------------
# RecoveryPlan contract
# ---------------------------------------------------------------------------


class TestRecoveryPlan:
    """Immutable plan describing what to execute."""

    def test_plan_with_single_date_all_extractors(self):
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=False,
            fail_fast=False,
        )
        assert plan.dates == [date(2026, 6, 1)]
        assert plan.extractors == DEFAULT_EXTRACTOR_ORDER
        assert plan.dry_run is False
        assert plan.fail_fast is False

    def test_plan_with_date_range_and_subset(self):
        dates = [date(2026, 6, 1), date(2026, 6, 2)]
        plan = RecoveryPlan(
            dates=dates,
            extractors=["discharges", "admissions"],
            dry_run=True,
            fail_fast=True,
        )
        assert plan.dates == dates
        assert plan.extractors == ["discharges", "admissions"]
        assert plan.dry_run is True
        assert plan.fail_fast is True

    def test_plan_with_single_date(self):
        """A plan with only one date should report that."""
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=False,
            fail_fast=False,
        )
        assert plan.total_dates == 1
        assert plan.date_count_label == "1 day"

    def test_plan_with_multiple_dates(self):
        plan = RecoveryPlan(
            dates=[date(2026, 6, 1), date(2026, 6, 2)],
            extractors=DEFAULT_EXTRACTOR_ORDER,
            dry_run=False,
            fail_fast=False,
        )
        assert plan.total_dates == 2
        assert plan.date_count_label == "2 days"
