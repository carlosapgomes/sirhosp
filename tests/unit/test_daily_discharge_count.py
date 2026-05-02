"""Tests for refresh_daily_discharge_counts management command (Slice S2)."""

from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestRefreshDailyDischargeCounts:
    """Tests for refresh_daily_discharge_counts management command."""

    def test_command_populates_counts_from_admissions(self):
        """Command groups discharge_date by day and upserts counts."""
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        # 3 unique patients discharged today, 2 yesterday
        for i in range(3):
            patient = Patient.objects.create(
                patient_source_key=f"PT{i}", source_system="tasy", name=f"P{i}")
            Admission.objects.create(
                patient=patient,
                source_admission_key=f"ADM-T{i}",
                source_system="tasy",
                discharge_date=timezone.make_aware(
                    datetime(today.year, today.month, today.day, 10 + i, 0, 0)),
            )
        for i in range(2):
            patient = Patient.objects.create(
                patient_source_key=f"PY{i}", source_system="tasy", name=f"Y{i}")
            Admission.objects.create(
                patient=patient,
                source_admission_key=f"ADM-Y{i}",
                source_system="tasy",
                discharge_date=timezone.make_aware(
                    datetime(yesterday.year, yesterday.month, yesterday.day, 14 + i, 0, 0)),
            )

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=today).count == 3
        assert DailyDischargeCount.objects.get(date=yesterday).count == 2

    def test_command_upserts_existing_counts(self):
        """Re-running updates existing counts instead of duplicating."""
        today = timezone.localdate()

        # First run: 2 unique patients discharged
        for i in range(2):
            patient = Patient.objects.create(
                patient_source_key=f"PA{i}", source_system="tasy", name=f"A{i}")
            Admission.objects.create(
                patient=patient,
                source_admission_key=f"ADM-A{i}",
                source_system="tasy",
                discharge_date=timezone.make_aware(
                    datetime(today.year, today.month, today.day, 10 + i, 0, 0)),
            )
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 2

        # Second run: 1 more patient discharged → should update to 3
        patient3 = Patient.objects.create(
            patient_source_key="PA3", source_system="tasy", name="A3")
        Admission.objects.create(
            patient=patient3,
            source_admission_key="ADM-A3",
            source_system="tasy",
            discharge_date=timezone.make_aware(
                datetime(today.year, today.month, today.day, 15, 0, 0)),
        )
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 3
        assert DailyDischargeCount.objects.count() == 1  # no duplicates

    def test_command_handles_empty_admissions(self):
        """Command completes without error when no discharge_dates exist."""
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.count() == 0

    def test_command_ignores_null_discharge_dates(self):
        """Admissions without discharge_date are not counted."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A")
        today = timezone.localdate()

        # One with discharge_date, one without
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-D",
            source_system="tasy",
            discharge_date=timezone.make_aware(
                datetime(today.year, today.month, today.day, 10, 0, 0)),
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-N",
            source_system="tasy",
            discharge_date=None,
        )

        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 1


@pytest.mark.django_db
class TestExtractDischargesHook:
    """Smoke tests: verify extract_discharges updates DailyDischargeCount."""

    def test_command_file_contains_daily_discharge_upsert(self):
        """extract_discharges.py contains DailyDischargeCount.update_or_create."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[2]
            / "apps" / "discharges" / "management" / "commands"
            / "extract_discharges.py"
        )
        content = source.read_text()
        assert "DailyDischargeCount" in content
        assert "update_or_create" in content
        # Ensure refresh is no longer called automatically
        assert "call_command" not in content, (
            "extract_discharges should NOT call refresh_daily_discharge_counts; "
            "it should update DailyDischargeCount directly from PDF count."
        )

    def test_upsert_follows_status_succeeded_assignment(self):
        """DailyDischargeCount upsert appears after run.status = 'succeeded'."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[2]
            / "apps" / "discharges" / "management" / "commands"
            / "extract_discharges.py"
        )
        content = source.read_text()
        pos_status = content.find('run.status = "succeeded"')
        pos_upsert = content.find("DailyDischargeCount.objects.update_or_create")
        assert pos_status > 0, "status succeeded line not found"
        assert pos_upsert > 0, "DailyDischargeCount upsert not found"
        assert pos_upsert > pos_status, (
            "DailyDischargeCount upsert must appear AFTER status succeeded"
        )
