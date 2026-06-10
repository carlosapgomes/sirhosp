"""Tests for death persistence hardening — idempotency and empty-output safety.

Slice S6 requirements (tasks.md 6.1-6.2):
- Repeated death extraction persistence must not duplicate individual records.
- Empty death output must persist a successful zero-count result with no stale records.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from apps.deaths.models import DailyDeathCount, DeathRecord
from apps.deaths.services import process_deaths

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RECORDS = [
    {
        "PRONTUARIO": "PRT0001",
        "NOME": "Paciente A",
        "OBITO": "01/06/2026",
        "DATA OBITO": "01/06/2026",
    },
    {
        "PRONTUARIO": "PRT0002",
        "NOME": "Paciente B",
        "OBITO": "01/06/2026",
        "DATA OBITO": "01/06/2026",
    },
    {
        "PRONTUARIO": "PRT0003",
        "NOME": "Paciente C",
        "OBITO": "01/06/2026",
        "DATA OBITO": "01/06/2026",
    },
]

REF_DATE = date(2026, 6, 1)
ANOTHER_DATE = date(2026, 6, 2)


@pytest.fixture(autouse=True)
def _clean_db():
    """Ensure clean state before each test."""
    DailyDeathCount.objects.all().delete()
    DeathRecord.objects.all().delete()


# =========================================================================
# Tests: Idempotent re-execution
# =========================================================================


@pytest.mark.django_db
class TestIdempotentReExecution:
    """Repeated calls to process_deaths with same data must not duplicate records."""

    def test_repeat_same_records_produces_same_count(self):
        """Running twice with the same records produces the same count, not doubled."""
        result1 = process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)
        assert result1["total_records"] == 3

        # Verify first run state
        daily1 = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily1.count == 3
        assert daily1.records.count() == 3

        # Second run with same records
        result2 = process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)
        assert result2["total_records"] == 3

        # Verify no duplication
        daily2 = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily2.count == 3
        assert daily2.records.count() == 3

    def test_repeat_with_different_records_replaces_old(self):
        """Running with different records for the same date replaces old records."""
        # First run: 3 records
        process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)

        # Second run: different set (2 records)
        updated_records = [
            {
                "PRONTUARIO": "PRT0001",
                "NOME": "Paciente A",
                "OBITO": "01/06/2026",
                "DATA OBITO": "01/06/2026",
            },
            {
                "PRONTUARIO": "PRT0099",
                "NOME": "Paciente Novo",
                "OBITO": "01/06/2026",
                "DATA OBITO": "01/06/2026",
            },
        ]

        result = process_deaths(updated_records, reference_date=REF_DATE)
        assert result["total_records"] == 2

        # Verify old records replaced
        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.count == 2
        assert daily.records.count() == 2

        # Verify the old record PRT0002 is gone
        prontuarios = set(daily.records.values_list("prontuario", flat=True))
        assert "PRT0002" not in prontuarios
        assert "PRT0099" in prontuarios

    def test_repeat_empty_records_after_having_records_clears_them(self):
        """Running with empty list after having records removes old records."""
        # First run: populate
        process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)
        assert DailyDeathCount.objects.get(date=REF_DATE).records.count() == 3

        # Second run: empty
        result = process_deaths([], reference_date=REF_DATE)
        assert result["total_records"] == 0

        # Verify records cleared
        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.count == 0
        assert daily.records.count() == 0

    def test_multiple_runs_are_deterministic(self):
        """Three runs with same data produce identical final state."""
        for _ in range(3):
            process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)

        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.count == 3
        assert daily.records.count() == 3

        prontuarios = sorted(daily.records.values_list("prontuario", flat=True))
        assert prontuarios == ["PRT0001", "PRT0002", "PRT0003"]

    def test_different_dates_do_not_interfere(self):
        """Records for different dates are independent."""
        process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)
        process_deaths(SAMPLE_RECORDS, reference_date=ANOTHER_DATE)

        daily1 = DailyDeathCount.objects.get(date=REF_DATE)
        daily2 = DailyDeathCount.objects.get(date=ANOTHER_DATE)

        assert daily1.count == 3
        assert daily2.count == 3
        assert daily1.records.count() == 3
        assert daily2.records.count() == 3

        # Different DailyDeathCount instances
        assert daily1.pk != daily2.pk


# =========================================================================
# Tests: Empty output behavior
# =========================================================================


@pytest.mark.django_db
class TestEmptyOutputPersistence:
    """Empty death output must produce zero-count, no stale records."""

    def test_empty_records_creates_zero_daily_count(self):
        """Calling process_deaths with empty list creates a zero-count entry."""
        result = process_deaths([], reference_date=REF_DATE)

        assert result["total_records"] == 0

        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.count == 0
        assert daily.raw_data == []

    def test_empty_records_leaves_no_stale_records(self):
        """Calling process_deaths with empty list has no records."""
        process_deaths([], reference_date=REF_DATE)

        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.records.count() == 0

    def test_empty_records_after_existing_clears_stale(self):
        """If records existed for a date and then empty is persisted, stale records vanish.

        This simulates: first extraction produces 3 records, second extraction
        produces no output (empty JSON) — the system should clear the 3 records.
        """
        # First: populate
        process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)

        # Verify records exist
        assert DailyDeathCount.objects.get(date=REF_DATE).records.count() == 3

        # Second: clear with empty
        process_deaths([], reference_date=REF_DATE)

        # Verify records gone
        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.count == 0
        assert daily.records.count() == 0

    def test_different_date_empty_preserves_other_dates(self):
        """Empty output for one date does not affect other dates."""
        process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)
        process_deaths([], reference_date=ANOTHER_DATE)

        # First date unaffected
        daily1 = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily1.count == 3
        assert daily1.records.count() == 3

        # Second date empty
        daily2 = DailyDeathCount.objects.get(date=ANOTHER_DATE)
        assert daily2.count == 0
        assert daily2.records.count() == 0

    def test_empty_records_update_or_create_semantics(self):
        """Even for a date with no prior data, empty records create a valid entry."""
        # No prior data for this date
        process_deaths([], reference_date=REF_DATE)

        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.count == 0
        assert daily.raw_data == []
        assert daily.records.count() == 0

    def test_empty_output_does_not_raise(self):
        """Empty output should not raise any exceptions."""
        result = process_deaths([], reference_date=REF_DATE)
        assert result["total_records"] == 0


# =========================================================================
# Tests: Transaction safety
# =========================================================================


@pytest.mark.django_db
class TestTransactionSafety:
    """process_deaths must be safe under partial failure scenarios."""

    def test_atomicity_on_failure_midway(self):
        """If an error occurs mid-way through record creation, no partial state remains.

        This is the key transaction safety test: the atomic block must roll back
        all changes (update_or_create, delete, partially created records) when
        a mid-way failure occurs.
        """
        # First, populate with 3 records (committed, outside our failing scope)
        process_deaths(SAMPLE_RECORDS, reference_date=REF_DATE)

        # Verify initial state
        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.records.count() == 3
        orig_pk = daily.pk
        orig_count = daily.count

        # Now simulate a failure on the SECOND record creation of a 2-record batch
        # The first create should succeed, the second should raise.
        # Since everything is inside transaction.atomic(), the first create,
        # the delete, and the update_or_create should all be rolled back.
        call_count = [0]
        real_create = DeathRecord.objects.create

        def _failing_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("Simulated DB failure mid-way")
            return real_create(**kwargs)

        with patch.object(DeathRecord.objects, "create", _failing_create):
            with pytest.raises(RuntimeError):
                process_deaths(
                    [
                        {
                            "PRONTUARIO": "NEW1", "NOME": "New 1",
                            "OBITO": "01/06/2026", "DATA OBITO": "01/06/2026",
                        },
                        {
                            "PRONTUARIO": "NEW2", "NOME": "New 2",
                            "OBITO": "01/06/2026", "DATA OBITO": "01/06/2026",
                        },
                    ],
                    reference_date=REF_DATE,
                )

        # Verify rollback: the original 3 records must still exist because
        # the transaction was rolled back entirely, restoring the DailyDeathCount
        # and its records to pre-call state.
        daily = DailyDeathCount.objects.get(date=REF_DATE)
        assert daily.pk == orig_pk, "DailyDeathCount should be the same instance"
        assert daily.count == orig_count, "Count should have been rolled back to original"
        assert daily.records.count() == 3, (
            "Original records should remain after rollback"
        )
