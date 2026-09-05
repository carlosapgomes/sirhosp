"""Tests for refresh_daily_discharge_counts management command.

RPSA-S8: the command rebuilds ``DailyDischargeCount`` from canonical
effective hospital exits (``Admission.discharge_date`` grouped by explicit
``America/Bahia`` local dates, latest reconciled ``ReconciliationEvent``
provenance ``hospital_discharge``). Deaths and merged duplicates are
excluded. Apply is the default; ``--dry-run`` previews without mutating.
Apply upserts affected dates with ``raw_data=[]`` (legacy patient rows
leave aggregate storage). All fixtures are synthetic.
"""

from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.patients.models import (
    EXIT_DEATH,
    EXIT_HOSPITAL_DISCHARGE,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

BAHIA = ZoneInfo("America/Bahia")


def _bahia(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Pin a wall-clock datetime to ``America/Bahia`` explicitly."""
    return datetime(year, month, day, hour, minute, tzinfo=BAHIA)


def _mark_reconciled(
    admission: Admission, exit_type: str
) -> ReconciliationEvent:
    """Append a reconciled exit event for the admission.

    ``source_id`` is a synthetic evidence reference; the classification
    reads only the admission link, status and exit type.
    """
    return ReconciliationEvent.objects.create(
        source_kind="discharge_record",
        source_id=admission.pk,
        admission=admission,
        status=RECONCILIATION_STATUS_RECONCILED,
        exit_type=exit_type,
    )


def _seed_exit(
    key: str, when: datetime, exit_type: str = EXIT_HOSPITAL_DISCHARGE
) -> Admission:
    """Create a canonical closed admission with reconciled exit provenance."""
    patient = Patient.objects.create(
        patient_source_key=key, source_system="tasy", name=f"Patient {key}")
    admission = Admission.objects.create(
        patient=patient,
        source_admission_key=f"ADM-{key}",
        source_system="tasy",
        discharge_date=when,
    )
    _mark_reconciled(admission, exit_type)
    return admission


@pytest.mark.django_db
class TestRefreshDailyDischargeCounts:
    """Tests for refresh_daily_discharge_counts management command."""

    def test_command_populates_counts_from_admissions(self):
        """Command groups canonical discharge_date by day and upserts counts."""
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        # 3 canonical hospital exits today, 2 yesterday
        for i in range(3):
            _seed_exit(
                f"PT{i}",
                _bahia(today.year, today.month, today.day, 10 + i, 0),
            )
        for i in range(2):
            _seed_exit(
                f"PY{i}",
                _bahia(yesterday.year, yesterday.month, yesterday.day, 14 + i, 0),
            )

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=today).count == 3
        assert DailyDischargeCount.objects.get(date=yesterday).count == 2

    def test_command_upserts_existing_counts(self):
        """Re-running updates existing counts instead of duplicating."""
        today = timezone.localdate()

        # First run: 2 canonical hospital exits
        for i in range(2):
            _seed_exit(
                f"PA{i}",
                _bahia(today.year, today.month, today.day, 10 + i, 0),
            )
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 2

        # Second run: 1 more canonical exit → should update to 3
        _seed_exit("PA3", _bahia(today.year, today.month, today.day, 15, 0))
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 3
        assert DailyDischargeCount.objects.count() == 1  # no duplicates

    def test_command_handles_empty_admissions(self):
        """Command completes without error when no discharge_dates exist."""
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.count() == 0

    def test_command_ignores_null_discharge_dates(self):
        """Admissions without discharge_date are not counted."""
        today = timezone.localdate()

        # One with discharge_date, one without
        _seed_exit("ADM-D", _bahia(today.year, today.month, today.day, 10, 0))
        Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="Patient P1")
        Admission.objects.create(
            patient=Patient.objects.get(patient_source_key="P1"),
            source_admission_key="ADM-N",
            source_system="tasy",
            discharge_date=None,
        )

        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 1


@pytest.mark.django_db
class TestCanonicalExitClassification:
    """Canonical classification: latest reconciled event decides exit type."""

    def test_death_exit_is_excluded_from_hospital_counts(self):
        """Death-closed episodes are not hospital discharges."""
        day = date(2026, 3, 10)
        _seed_exit("H1", _bahia(2026, 3, 10, 8, 0))
        _seed_exit("H2", _bahia(2026, 3, 10, 9, 0))
        _seed_exit(
            "DEATH1", _bahia(2026, 3, 10, 12, 0), exit_type=EXIT_DEATH
        )

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=day).count == 2

    def test_latest_reconciled_event_decides_classification(self):
        """The latest reconciled event's exit_type wins, not the first."""
        # hospital_discharge first, death latest → excluded
        closed_as_death = _seed_exit("L1", _bahia(2026, 3, 11, 8, 0))
        _mark_reconciled(closed_as_death, EXIT_DEATH)
        # death first, hospital_discharge latest → included
        closed_as_exit = _seed_exit(
            "L2", _bahia(2026, 3, 11, 9, 0), exit_type=EXIT_DEATH
        )
        _mark_reconciled(closed_as_exit, EXIT_HOSPITAL_DISCHARGE)

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=date(2026, 3, 11)).count == 1

    def test_merged_duplicate_is_counted_once(self):
        """Only the canonical episode counts; the merged duplicate is hidden."""
        day = date(2026, 3, 12)
        canonical = _seed_exit("C1", _bahia(2026, 3, 12, 8, 0))
        duplicate = _seed_exit("DUP1", _bahia(2026, 3, 12, 8, 30))
        duplicate.merged_into = canonical
        duplicate.save(update_fields=["merged_into"])

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=day).count == 1

    def test_exit_without_reconciled_event_is_not_counted(self):
        """``discharge_date`` alone is not enough: provenance is required."""
        Patient.objects.create(
            patient_source_key="UNEV", source_system="tasy", name="Patient UNEV")
        Admission.objects.create(
            patient=Patient.objects.get(patient_source_key="UNEV"),
            source_admission_key="ADM-UNEVR",
            source_system="tasy",
            discharge_date=_bahia(2026, 3, 13, 10, 0),
        )

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.count() == 0


@pytest.mark.django_db
class TestBahiaMidnightGrouping:
    """Grouping by explicit ``America/Bahia`` local date."""

    def test_exit_at_2355_stays_on_local_date(self):
        _seed_exit("M1", _bahia(2026, 3, 7, 23, 55))

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=date(2026, 3, 7)).count == 1
        assert not DailyDischargeCount.objects.filter(
            date=date(2026, 3, 8)
        ).exists()

    def test_exit_at_0005_moves_to_next_date(self):
        _seed_exit("M2", _bahia(2026, 3, 8, 0, 5))

        call_command("refresh_daily_discharge_counts")

        assert not DailyDischargeCount.objects.filter(
            date=date(2026, 3, 7)
        ).exists()
        assert DailyDischargeCount.objects.get(date=date(2026, 3, 8)).count == 1


@pytest.mark.django_db
class TestSummaryTimeDoesNotAffectExits:
    """``alta_em`` never shifts the exit aggregate."""

    def test_alta_em_does_not_shift_exit_count(self):
        """A cross-midnight pair is counted on the ``saida_em`` date only."""
        alta_day = date(2026, 3, 13)
        saida_day = date(2026, 3, 14)
        _seed_exit("X1", _bahia(2026, 3, 14, 0, 10))
        DischargeRecord.objects.create(
            prontuario="555",
            data_internacao="INT-555",
            alta_em=_bahia(2026, 3, 13, 18, 0),
            saida_em=_bahia(2026, 3, 14, 0, 10),
        )

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=saida_day).count == 1
        assert not DailyDischargeCount.objects.filter(date=alta_day).exists()


@pytest.mark.django_db
class TestDryRunAndApplyProvenance:
    """Apply is the default; ``--dry-run`` mutates nothing. Both report
    aggregate before/after provenance without patient identity."""

    def test_dry_run_reports_and_mutates_nothing(self):
        today = timezone.localdate()
        _seed_exit("DR1", _bahia(today.year, today.month, today.day, 9, 0))
        legacy_row = DailyDischargeCount.objects.create(
            date=today,
            count=7,
            raw_data=[{"prontuario": "777", "nome": "PACIENTE SETE"}],
        )

        out = StringIO()
        call_command(
            "refresh_daily_discharge_counts", "--dry-run", stdout=out
        )

        legacy_row.refresh_from_db()
        assert legacy_row.count == 7  # zero mutation
        assert legacy_row.raw_data == [
            {"prontuario": "777", "nome": "PACIENTE SETE"}
        ]
        assert DailyDischargeCount.objects.count() == 1  # nothing created
        output = out.getvalue()
        # Before/after provenance is reported…
        assert f"{today.isoformat()}: 7 -> 1" in output
        assert "before=7" in output
        assert "after=1" in output
        # …and the preview is explicit about not applying.
        assert "dry-run" in output.lower()

    def test_dry_run_leaves_raw_data_untouched(self):
        today = timezone.localdate()
        legacy_row = DailyDischargeCount.objects.create(
            date=today,
            count=5,
            raw_data=[{"prontuario": "888", "nome": "PACIENTE OITO"}],
        )

        call_command(
            "refresh_daily_discharge_counts", "--dry-run", stdout=StringIO()
        )

        legacy_row.refresh_from_db()
        assert legacy_row.raw_data == [
            {"prontuario": "888", "nome": "PACIENTE OITO"}
        ]
        assert legacy_row.count == 5

    def test_apply_is_default_and_reports_before_after(self):
        """No flags means apply (the S7 automatic refresh calls it bare)."""
        today = timezone.localdate()
        _seed_exit("AP1", _bahia(today.year, today.month, today.day, 9, 0))
        _seed_exit("AP2", _bahia(today.year, today.month, today.day, 10, 0))
        DailyDischargeCount.objects.create(
            date=today,
            count=7,
            raw_data=[{"prontuario": "777", "nome": "PACIENTE SETE"}],
        )

        out = StringIO()
        call_command("refresh_daily_discharge_counts", stdout=out)

        row = DailyDischargeCount.objects.get(date=today)
        assert row.count == 2
        assert row.raw_data == []  # legacy patient rows cleared on apply
        output = out.getvalue()
        assert f"{today.isoformat()}: 7 -> 2" in output
        assert "before=7" in output
        assert "after=2" in output

    def test_apply_output_contains_no_patient_identity(self):
        """Aggregate provenance output never carries name or prontuário."""
        today = timezone.localdate()
        _seed_exit("AP3", _bahia(today.year, today.month, today.day, 9, 0))
        DailyDischargeCount.objects.create(
            date=today,
            count=3,
            raw_data=[
                {"prontuario": "9999999", "nome": "PACIENTE NOVE MILHOES"}
            ],
        )

        out = StringIO()
        call_command("refresh_daily_discharge_counts", stdout=out)

        output = out.getvalue()
        assert "PACIENTE NOVE MILHOES" not in output
        assert "9999999" not in output

    def test_stale_date_is_zeroed_when_exits_move(self):
        """A legacy date without canonical exits no longer double counts."""
        old_day = date(2026, 3, 20)
        new_day = date(2026, 3, 21)
        DailyDischargeCount.objects.create(
            date=old_day, count=3, raw_data=[{"prontuario": "1"}]
        )
        _seed_exit("MV1", _bahia(2026, 3, 21, 7, 0))

        call_command("refresh_daily_discharge_counts")

        old_row = DailyDischargeCount.objects.get(date=old_day)
        assert old_row.count == 0
        assert old_row.raw_data == []
        assert DailyDischargeCount.objects.get(date=new_day).count == 1


@pytest.mark.django_db
class TestExtractDischargesHook:
    """Smoke tests: verify extract_discharges command delegates to service."""

    def test_command_delegates_to_service(self):
        """extract_discharges.py imports run_discharge_extraction."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[2]
            / "apps" / "discharges" / "management" / "commands"
            / "extract_discharges.py"
        )
        content = source.read_text()
        assert "run_discharge_extraction" in content
        assert "from apps.discharges.extraction_service import run_discharge_extraction" in content
        # The command must NOT contain the old orchestration logic
        assert "DailyDischargeCount" not in content

    def test_service_module_contains_persistence_logic(self):
        """extraction_service.py persists evidence WITHOUT the daily aggregate.

        RPSA-S2 (controller-authorized fixture update): evidence
        persistence is decoupled from ``DailyDischargeCount`` — the
        aggregate must never be written from report persistence. The
        canonical reconciliation boundary must be present instead.
        """
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[2]
            / "apps" / "discharges" / "extraction_service.py"
        )
        content = source.read_text()
        # Evidence persistence must not write the operational aggregate.
        assert "DailyDischargeCount" not in content
        # Reconciliation must be routed through the shared boundary.
        assert "_reconcile_persisted_records" in content
        # The service must manage persistence (not delegate to another
        # command). RPSA-S7: the post-reconciliation aggregate refresh is
        # the ONLY allowed ``call_command`` use — any second invocation
        # fails this guard.
        assert content.count("call_command(") == 1
        assert 'call_command("refresh_daily_discharge_counts")' in content
