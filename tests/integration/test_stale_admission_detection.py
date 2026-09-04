"""Integration coverage for RPSA-S5 stale-admission detection.

Exercises the migrated schema (case model, dedicated review permission),
the post-census observation hook inside ``run_single_cycle``, the hourly
safety command (bounded, aggregate-safe, distinct advisory lock) and the
conflict-evidence sync route against real PostgreSQL.

All fixtures are synthetic; output assertions stay aggregate-safe.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Sequence
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.orchestration import (
    acquire_orchestrator_lock,
    release_orchestrator_lock,
    run_single_cycle,
)
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
    RECONCILIATION_STATUS_PENDING,
    Admission,
    Patient,
    StaleAdmissionCase,
)

TZ_LOCAL = ZoneInfo("America/Bahia")

MINIMUM_TEST_SECTORS = 40


def _make_patient(pront: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=pront,
        source_system="tasy",
        name=f"PACIENTE {pront}",
    )


def _make_open_admission(patient: Patient, key: str) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=timezone.now() - timedelta(days=3),
    )


def _make_census_run(
    captured_at,
    occupied_pronts: Sequence[str] = (),
    *,
    sectors: int = MINIMUM_TEST_SECTORS,
) -> IngestionRun:
    run = IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
        queued_at=captured_at,
        processing_started_at=captured_at,
        finished_at=captured_at,
    )
    rows: list[CensusSnapshot] = []
    for index in range(sectors):
        pront = occupied_pronts[index] if index < len(occupied_pronts) else ""
        rows.append(
            CensusSnapshot(
                captured_at=captured_at,
                ingestion_run=run,
                setor=f"SETOR {index:03d}",
                setor_codigo=str(1000 + index),
                leito=f"L{index:03d}",
                prontuario=pront,
                nome=(f"PACIENTE {pront}" if pront else "DESOCUPADO"),
                bed_status=(
                    BedStatus.OCCUPIED if pront else BedStatus.EMPTY
                ),
            )
        )
    CensusSnapshot.objects.bulk_create(rows)
    return run


def _make_two_absence_case(pront: str) -> StaleAdmissionCase:
    patient = _make_patient(pront)
    admission = _make_open_admission(patient, f"ADM_{pront}")
    now = timezone.now()
    first_run = _make_census_run(
        now - timedelta(hours=3), occupied_pronts=[]
    )
    last_run = _make_census_run(
        now - timedelta(hours=2), occupied_pronts=[]
    )
    return StaleAdmissionCase.objects.create(
        admission=admission,
        first_absence_run=first_run,
        first_absence_at=now - timedelta(hours=3),
        last_absence_run=last_run,
        last_absence_at=now - timedelta(hours=2),
    )


def _admissions_only_records() -> list[str]:
    return [
        parameters.get("patient_record", "")
        for parameters in IngestionRun.objects.filter(
            intent="admissions_only"
        ).values_list("parameters_json", flat=True)
    ]


class _CensusCycleSimulator:
    """Simulates ``extract_census`` producing prepared accepted runs."""

    def __init__(self) -> None:
        self.prepared: list[tuple[object, Sequence[str]]] = []
        self.created_runs: list[IngestionRun] = []

    def queue_run(self, captured_at, occupied_pronts: Sequence[str]) -> None:
        self.prepared.append((captured_at, occupied_pronts))

    def __call__(self, command: str, **kwargs: object) -> None:
        if command != "extract_census":
            return
        captured_at, occupied_pronts = self.prepared.pop(0)
        self.created_runs.append(
            _make_census_run(captured_at, occupied_pronts)
        )


# ---------------------------------------------------------------------------
# Schema and dedicated review permission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReviewPermission:
    def test_review_permission_created_after_migrate(self) -> None:
        permission = Permission.objects.get(
            codename="review_reconciliation_cases",
            content_type__app_label="patients",
            content_type__model="staleadmissioncase",
        )
        assert permission.name == "Can review reconciliation cases"

    def test_permission_assignment_grants_review_access(self) -> None:
        user = User.objects.create_user("reviewer", password="x")
        permission = Permission.objects.get(
            codename="review_reconciliation_cases"
        )
        user.user_permissions.add(permission)

        refreshed = User.objects.get(pk=user.pk)
        assert refreshed.has_perm("patients.review_reconciliation_cases")

    def test_other_authenticated_users_lack_the_permission(self) -> None:
        user = User.objects.create_user("plain", password="x")

        refreshed = User.objects.get(pk=user.pk)
        assert not refreshed.has_perm(
            "patients.review_reconciliation_cases"
        )


@pytest.mark.django_db
class TestCaseSchema:
    def test_case_rows_persist_and_resolve(self) -> None:
        case = _make_two_absence_case("PRNT-S1")
        case.resolved_at = timezone.now()
        case.resolution_reason = StaleAdmissionCase.ResolutionReason.REAPPEARED
        case.save(update_fields=["resolved_at", "resolution_reason"])

        refreshed = StaleAdmissionCase.objects.get(pk=case.pk)
        assert refreshed.resolution_reason == "reappeared"


# ---------------------------------------------------------------------------
# Post-census observation hook in run_single_cycle
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestPostCensusHook:
    def _eligible_system(self) -> None:
        """No active runs and no open batch before the cycle."""
        assert not IngestionRun.objects.filter(
            status__in=("queued", "running")
        ).exists()

    def test_successful_cycle_invokes_observation_for_accepted_run(
        self,
    ) -> None:
        from unittest import mock

        self._eligible_system()
        patient = _make_patient("PRNT-HK1")
        _make_open_admission(patient, "ADM_HK1")
        # Preceding accepted run: patient occupied.
        _make_census_run(
            timezone.now() - timedelta(minutes=90),
            occupied_pronts=["PRNT-HK1"],
        )
        simulator = _CensusCycleSimulator()
        simulator.queue_run(
            timezone.now() - timedelta(minutes=40), occupied_pronts=[]
        )

        with mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=simulator,
        ):
            result = run_single_cycle(min_interval_minutes=0)

        assert result["outcome"] == "success"
        observation = result["absence_observation"]
        assert observation["accepted"] is True
        assert observation["run_id"] == simulator.created_runs[0].pk
        assert observation["cases_created"] == 1
        case = StaleAdmissionCase.objects.get()
        assert case.first_absence_run_id == simulator.created_runs[0].pk
        # First absence never enqueues confirmation.
        assert not _admissions_only_records()
        admission = Admission.objects.get(source_admission_key="ADM_HK1")
        assert admission.discharge_date is None

    def test_second_cycle_advances_case_and_enqueues_bounded_sync(
        self,
    ) -> None:
        from unittest import mock

        self._eligible_system()
        patient = _make_patient("PRNT-HK2")
        _make_open_admission(patient, "ADM_HK2")
        _make_census_run(
            timezone.now() - timedelta(minutes=120),
            occupied_pronts=["PRNT-HK2"],
        )
        simulator = _CensusCycleSimulator()
        simulator.queue_run(
            timezone.now() - timedelta(minutes=70), occupied_pronts=[]
        )
        simulator.queue_run(
            timezone.now() - timedelta(minutes=10), occupied_pronts=[]
        )

        with mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=simulator,
        ):
            first = run_single_cycle(min_interval_minutes=0)
            second = run_single_cycle(min_interval_minutes=0)

        assert first["outcome"] == "success"
        assert first["absence_observation"]["cases_created"] == 1
        assert second["outcome"] == "success"
        assert second["absence_observation"]["cases_advanced"] == 1
        assert second["absence_observation"]["confirmation"][
            "enqueued_cases"
        ] == 1
        assert _admissions_only_records() == ["PRNT-HK2"]
        admission = Admission.objects.get(source_admission_key="ADM_HK2")
        assert admission.discharge_date is None

    def test_observation_failure_does_not_fail_cycle_or_leak_lock(
        self,
    ) -> None:
        from unittest import mock

        self._eligible_system()
        _make_census_run(timezone.now(), occupied_pronts=["PRNT-HK3"])
        simulator = _CensusCycleSimulator()
        simulator.queue_run(timezone.now(), occupied_pronts=[])

        def boom(run_id: int | None = None, **kwargs: object) -> dict:
            del run_id, kwargs
            raise RuntimeError("observation exploded")

        with mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=simulator,
        ):
            with mock.patch(
                "apps.census.orchestration.observe_accepted_census_run",
                side_effect=boom,
            ):
                result = run_single_cycle(min_interval_minutes=0)

        assert result["outcome"] == "success"
        assert result["absence_observation"]["observed"] is False
        assert StaleAdmissionCase.objects.count() == 0
        # The orchestrator lock was released despite the hook failure.
        assert acquire_orchestrator_lock() is True
        release_orchestrator_lock()

    def test_processing_failure_skips_observation_and_keeps_sequence(
        self,
    ) -> None:
        from unittest import mock

        self._eligible_system()
        case = _make_two_absence_case("PRNT-HK4")
        baseline = case.last_absence_run
        simulator = _CensusCycleSimulator()
        simulator.queue_run(timezone.now(), occupied_pronts=[])

        def fail_process(command: str, **kwargs: object) -> None:
            if command == "process_census_snapshot":
                raise CommandError("processing failed")
            simulator(command, **kwargs)

        with mock.patch(
            "apps.census.orchestration.call_command",
            side_effect=fail_process,
        ):
            result = run_single_cycle(min_interval_minutes=0)

        assert result["outcome"] == "processing_failed"
        case.refresh_from_db()
        assert case.last_absence_run_id == baseline.pk
        assert not _admissions_only_records()


# ---------------------------------------------------------------------------
# Hourly safety command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSafetyCommand:
    def test_command_enqueues_eligible_case_with_aggregate_output(
        self,
    ) -> None:
        case = _make_two_absence_case("PRNT-SC1")

        out = StringIO()
        call_command("reconcile_stale_admissions", stdout=out)

        assert "enqueued_cases=1" in out.getvalue()
        assert "PRNT-SC1" not in out.getvalue()
        assert _admissions_only_records() == ["PRNT-SC1"]
        case.refresh_from_db()
        assert case.last_enqueued_run is not None

    def test_command_limit_argument_is_bounded(self) -> None:
        for index in range(3):
            _make_two_absence_case(f"PRNT-SC2{index}")

        out = StringIO()
        call_command(
            "reconcile_stale_admissions",
            "--limit",
            "2",
            stdout=out,
        )

        assert "enqueued_cases=2" in out.getvalue()
        assert len(_admissions_only_records()) == 2

    def test_command_rejects_non_positive_limit(self) -> None:
        with pytest.raises(CommandError, match="positive"):
            call_command("reconcile_stale_admissions", "--limit", "0")

    def test_command_skips_when_sweep_lock_held(self) -> None:
        import psycopg
        from django.db import connection

        from apps.census.stale_admissions import (
            STALE_ADMISSION_SWEEP_LOCK_KEY,
        )

        case = _make_two_absence_case("PRNT-SC3")
        settings = connection.settings_dict
        other_conn = psycopg.connect(
            host=settings["HOST"],
            port=settings["PORT"],
            dbname=settings["NAME"],
            user=settings["USER"],
            password=settings["PASSWORD"],
        )
        other_conn.execute(
            "SELECT pg_advisory_lock(%s)", [STALE_ADMISSION_SWEEP_LOCK_KEY]
        )
        try:
            out = StringIO()
            call_command("reconcile_stale_admissions", stdout=out)
            assert "lock already held" in out.getvalue()
            assert not _admissions_only_records()
        finally:
            other_conn.execute(
                "SELECT pg_advisory_unlock(%s)",
                [STALE_ADMISSION_SWEEP_LOCK_KEY],
            )
            other_conn.close()
        case.refresh_from_db()
        assert case.last_enqueued_run is None

    def test_command_releases_lock_when_evaluation_fails(self) -> None:
        from unittest import mock

        from apps.census.stale_admissions import (
            acquire_stale_admission_sweep_lock,
            release_stale_admission_sweep_lock,
        )

        def boom(*args: object, **kwargs: object) -> dict:
            del args, kwargs
            raise RuntimeError("evaluation exploded")

        with mock.patch(
            "apps.census.management.commands.reconcile_stale_admissions"
            ".evaluate_and_enqueue_stale_admission_cases",
            side_effect=boom,
        ):
            with pytest.raises(RuntimeError):
                call_command("reconcile_stale_admissions")

        # Released on the failure path.
        assert acquire_stale_admission_sweep_lock() is True
        release_stale_admission_sweep_lock()


# ---------------------------------------------------------------------------
# Conflict-evidence sync route (integration)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConflictRouteIntegration:
    def test_conflict_rows_enqueue_one_deduplicated_run(self) -> None:
        from apps.deaths.models import DeathRecord
        from apps.discharges.models import DischargeRecord

        old = timezone.now() - timedelta(days=2)
        _make_patient("PRNT-CF1")
        DischargeRecord.objects.create(
            prontuario="PRNT-CF1",
            data_internacao="01/02/2026",
            reconciliation_status=RECONCILIATION_STATUS_CONFLICT,
            reconciled_at=old,
        )
        DeathRecord.objects.create(
            date=old.date(),
            prontuario="PRNT-CF1",
            reconciliation_status=RECONCILIATION_STATUS_CONFLICT,
            reconciled_at=old,
        )

        call_command("reconcile_stale_admissions")

        assert _admissions_only_records() == ["PRNT-CF1"]

    def test_unresolved_non_conflict_rows_produce_zero_runs(self) -> None:
        from apps.discharges.models import DischargeRecord

        old = timezone.now() - timedelta(days=30)
        for status in (
            RECONCILIATION_STATUS_PENDING,
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
            RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
        ):
            DischargeRecord.objects.create(
                prontuario=f"PRNT-CF2-{status}",
                data_internacao="01/02/2026",
                reconciliation_status=status,
                reconciled_at=old,
            )

        call_command("reconcile_stale_admissions")

        assert not _admissions_only_records()
