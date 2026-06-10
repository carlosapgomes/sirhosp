"""Tests for the shared historical extraction result contract.

Slice S1 requirements (tasks.md 1.1):
- Add tests for a small structured extraction result contract covering
  success and failure metadata.

The contract is a plain Python dataclass, not a DB model, so these
tests do not require django_db.
"""

from __future__ import annotations

from datetime import date

from apps.ingestion.historical_extraction import ExtractionResult


class TestExtractionResultSuccess:
    """Happy path: a successful extraction result."""

    def test_successful_result_has_correct_attributes(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
            metrics={"total_records": 5},
        )

        assert result.extraction_type == "admission_extraction"
        assert result.target_start == date(2026, 6, 1)
        assert result.target_end == date(2026, 6, 1)
        assert result.success is True
        assert result.metrics == {"total_records": 5}
        assert result.failure_reason == ""
        assert result.error_message == ""
        assert result.ingestion_run_id is None

    def test_success_with_period_dates(self):
        """End date can differ from start date for period extractions."""
        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 5, 1),
            target_end=date(2026, 5, 31),
            success=True,
            metrics={"total_records": 42},
        )

        assert result.target_start == date(2026, 5, 1)
        assert result.target_end == date(2026, 5, 31)

    def test_success_with_empty_metrics(self):
        """A successful extraction may have zero records."""
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
            metrics={"total_records": 0},
        )

        assert result.success is True
        assert result.metrics == {"total_records": 0}

    def test_success_with_linked_ingestion_run(self):
        """A successful result may reference an IngestionRun id."""
        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
            metrics={"total_records": 3},
            ingestion_run_id=42,
        )

        assert result.ingestion_run_id == 42

    def test_extraction_type_admission_and_death(self):
        """Extraction types are distinguishable."""
        admission = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )
        death = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        assert admission.extraction_type == "admission_extraction"
        assert death.extraction_type == "death_extraction"
        assert admission.extraction_type != death.extraction_type


class TestExtractionResultFailure:
    """Unhappy path: a failed extraction result."""

    def test_failed_result_with_timeout_reason(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
            error_message="Subprocess timed out after 600 seconds",
        )

        assert result.success is False
        assert result.failure_reason == "timeout"
        assert "timed out" in result.error_message

    def test_failed_result_with_source_unavailable_reason(self):
        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="source_unavailable",
            error_message="Source system returned HTTP 503",
        )

        assert result.success is False
        assert result.failure_reason == "source_unavailable"

    def test_failed_result_with_invalid_payload_reason(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="invalid_payload",
            error_message="JSON parse error at line 1",
        )

        assert result.success is False
        assert result.failure_reason == "invalid_payload"

    def test_failed_result_with_unexpected_exception_reason(self):
        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="unexpected_exception",
            error_message="AttributeError: 'NoneType' object has no attribute 'items'",
        )

        assert result.success is False
        assert result.failure_reason == "unexpected_exception"

    def test_failed_result_has_no_metrics(self):
        """Failed extractions typically have empty metrics."""
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="timeout",
        )

        assert result.metrics == {}

    def test_failed_result_can_have_ingestion_run_id(self):
        """Even failures can be linked to an IngestionRun."""
        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=False,
            failure_reason="source_unavailable",
            error_message="Connection refused",
            ingestion_run_id=99,
        )

        assert result.ingestion_run_id == 99


class TestExtractionResultDefaults:
    """Default values for optional fields."""

    def test_metrics_defaults_to_empty_dict(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        assert result.metrics == {}

    def test_failure_reason_defaults_to_empty_string(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        assert result.failure_reason == ""

    def test_error_message_defaults_to_empty_string(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        assert result.error_message == ""

    def test_ingestion_run_id_defaults_to_none(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        assert result.ingestion_run_id is None

    def test_defaults_do_not_interfere_with_explicit_values(self):
        result = ExtractionResult(
            extraction_type="death_extraction",
            target_start=date(2026, 6, 5),
            target_end=date(2026, 6, 5),
            success=False,
            failure_reason="validation_error",
            error_message="Invalid date range",
            metrics={"attempts": 1},
            ingestion_run_id=7,
        )

        assert result.failure_reason == "validation_error"
        assert result.error_message == "Invalid date range"
        assert result.metrics == {"attempts": 1}
        assert result.ingestion_run_id == 7

    def test_target_dates_are_immutable_date_objects(self):
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        assert isinstance(result.target_start, date)
        assert isinstance(result.target_end, date)

    def test_result_is_dataclass(self):
        """ExtractionResult should be a dataclass for low ceremony."""
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 1),
            success=True,
        )

        # Dataclasses provide __dataclass_fields__
        assert hasattr(result, "__dataclass_fields__")

    def test_result_representation_is_readable(self):
        """The repr of a result should include key fields."""
        result = ExtractionResult(
            extraction_type="admission_extraction",
            target_start=date(2026, 6, 1),
            target_end=date(2026, 6, 10),
            success=True,
            metrics={"total_records": 15},
        )

        rep = repr(result)
        assert "admission_extraction" in rep
        assert "ExtractionResult" in rep
        assert "success=True" in rep
        assert "total_records" in rep
