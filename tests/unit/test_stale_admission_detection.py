"""Two-census absence detection and bounded confirmation (RPSA-S5).

Covers the conservative stale-admission case lifecycle driven by accepted
complete census runs (provenance and completeness reused from
``validate_snapshot_completeness``), the 30-minute eligibility boundary,
the 6-hour inconclusive and 24-hour conclusive-no-exit cooldowns, the
100-per-cycle bounded enqueue with caller-side active-run dedup, the
conflict-evidence sync route, and identity-safe output.

Absence never writes ``Admission.discharge_date``. All fixtures are
synthetic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError

from apps.census.models import BedStatus, CensusSnapshot
from apps.census.stale_admissions import (
    CONCLUSIVE_NO_EXIT_COOLDOWN,
    INCONCLUSIVE_COOLDOWN,
    MAX_ENQUEUES_PER_CYCLE,
    MIN_ELIGIBILITY_IDLE,
    STALE_ADMISSION_SWEEP_LOCK_KEY,
    acquire_stale_admission_sweep_lock,
    evaluate_and_enqueue_stale_admission_cases,
    observe_accepted_census_run,
    release_stale_admission_sweep_lock,
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

T_BASE = datetime(2026, 3, 10, 9, 0, 0, tzinfo=TZ_LOCAL)

MINIMUM_TEST_SECTORS = 40


def _at(minutes: int) -> datetime:
    return T_BASE + timedelta(minutes=minutes)


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
        admission_date=T_BASE - timedelta(days=3),
    )


def _make_census_run(
    captured_at: datetime,
    occupied_pronts: Sequence[str] = (),
    *,
    sectors: int = MINIMUM_TEST_SECTORS,
) -> IngestionRun:
    """Create a succeeded census_extraction run with its snapshots."""
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


def _make_census_run_incomplete(captured_at: datetime) -> IngestionRun:
    """Create a census run whose snapshots fail the completeness gate."""
    return _make_census_run(captured_at, sectors=MINIMUM_TEST_SECTORS - 1)


def _admissions_only_records() -> list[str]:
    return [
        parameters.get("patient_record", "")
        for parameters in IngestionRun.objects.filter(
            intent="admissions_only"
        ).values_list("parameters_json", flat=True)
    ]


def _make_absent_pair(
    pront: str,
    *,
    present_at: datetime,
    absent_at: datetime,
) -> tuple[Patient, Admission, IngestionRun]:
    """Patient present in one accepted run, absent from a later one."""
    patient = _make_patient(pront)
    admission = _make_open_admission(patient, f"ADM_{pront}")
    _make_census_run(present_at, occupied_pronts=[pront])
    absent_run = _make_census_run(absent_at, occupied_pronts=[])
    return patient, admission, absent_run


def _make_two_absence_case(
    pront: str,
    *,
    first_absence_at: datetime,
    last_absence_at: datetime,
) -> tuple[StaleAdmissionCase, IngestionRun, IngestionRun]:
    """Eligible-shape case: two distinct consecutive accepted absences."""
    patient = _make_patient(pront)
    admission = _make_open_admission(patient, f"ADM_{pront}")
    first_run = _make_census_run(first_absence_at, occupied_pronts=[])
    last_run = _make_census_run(last_absence_at, occupied_pronts=[])
    case = StaleAdmissionCase.objects.create(
        admission=admission,
        first_absence_run=first_run,
        first_absence_at=first_absence_at,
        last_absence_run=last_run,
        last_absence_at=last_absence_at,
    )
    return case, first_run, last_run


# ---------------------------------------------------------------------------
# Accepted-run provenance (completeness reused, never reimplemented)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAcceptedRunProvenance:
    def test_complete_run_with_unique_provenance_is_accepted(self) -> None:
        run = _make_census_run(_at(0), occupied_pronts=["PRNT-A1"])

        result = observe_accepted_census_run(run_id=run.pk, now=_at(1))

        assert result["accepted"] is True
        assert result["run_id"] == run.pk

    def test_incomplete_run_is_ignored_without_case_changes(self) -> None:
        patient = _make_patient("PRNT-B1")
        admission = _make_open_admission(patient, "ADM_B1")
        present = _make_census_run(_at(0), occupied_pronts=["PRNT-B1"])
        incomplete = _make_census_run_incomplete(_at(10))
        assert present.pk != incomplete.pk

        result = observe_accepted_census_run(
            run_id=incomplete.pk, now=_at(11)
        )

        assert result["accepted"] is False
        assert StaleAdmissionCase.objects.count() == 0
        assert IngestionRun.objects.filter(
            intent="admissions_only"
        ).count() == 0
        assert admission.discharge_date is None

    def test_ambiguous_provenance_is_ignored(self) -> None:
        """Two runs sharing the latest captured_at resolve to no run."""
        _make_census_run(_at(0), occupied_pronts=["PRNT-C1"])
        _make_census_run(_at(0), occupied_pronts=["PRNT-C2"])

        result = observe_accepted_census_run(run_id=None, now=_at(1))

        assert result["accepted"] is False
        assert StaleAdmissionCase.objects.count() == 0

    def test_unknown_run_id_is_noop(self) -> None:
        result = observe_accepted_census_run(run_id=999999, now=_at(0))

        assert result["accepted"] is False


# ---------------------------------------------------------------------------
# Case lifecycle: start, advance, resolve, idempotency, baseline
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCaseLifecycle:
    def test_first_accepted_absence_starts_one_case_only(self) -> None:
        patient, admission, absent_run = _make_absent_pair(
            "PRNT-D1", present_at=_at(0), absent_at=_at(10)
        )

        result = observe_accepted_census_run(
            run_id=absent_run.pk, now=_at(11)
        )

        assert result["cases_created"] == 1
        cases = StaleAdmissionCase.objects.all()
        assert cases.count() == 1
        case = cases.get()
        assert case.admission == admission
        assert case.first_absence_run_id == absent_run.pk
        assert case.last_absence_run_id == absent_run.pk
        assert case.first_absence_at == _at(10)
        assert case.resolved_at is None
        # One absence never enqueues source confirmation.
        assert not _admissions_only_records()
        admission.refresh_from_db()
        assert admission.discharge_date is None
        del patient

    def test_repeated_observation_of_same_run_is_idempotent(self) -> None:
        _, _, absent_run = _make_absent_pair(
            "PRNT-D2", present_at=_at(0), absent_at=_at(10)
        )

        first = observe_accepted_census_run(
            run_id=absent_run.pk, now=_at(11)
        )
        second = observe_accepted_census_run(
            run_id=absent_run.pk, now=_at(12)
        )

        assert first["cases_created"] == 1
        assert second["cases_created"] == 0
        assert second["cases_advanced"] == 0
        assert StaleAdmissionCase.objects.count() == 1

    def test_patient_present_creates_no_case(self) -> None:
        _make_census_run(_at(0), occupied_pronts=["PRNT-D3"])

        result = observe_accepted_census_run(run_id=None, now=_at(1))

        assert result["cases_created"] == 0
        assert StaleAdmissionCase.objects.count() == 0

    def test_reappearance_resolves_case_without_clinical_mutation(
        self,
    ) -> None:
        patient, admission, absent_run = _make_absent_pair(
            "PRNT-D4", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=absent_run.pk, now=_at(11))
        # Prior-episode exit evidence must stay valid and untouched.
        prior_admission = _make_open_admission(patient, "ADM_D4_PRIOR")
        prior_admission.discharge_date = T_BASE - timedelta(days=10)
        prior_admission.save(update_fields=["discharge_date"])
        reappeared_run = _make_census_run(
            _at(40), occupied_pronts=["PRNT-D4"]
        )

        result = observe_accepted_census_run(
            run_id=reappeared_run.pk, now=_at(41)
        )

        assert result["cases_resolved_reappeared"] == 1
        case = StaleAdmissionCase.objects.get()
        assert case.resolved_at == _at(41)
        assert (
            case.resolution_reason
            == StaleAdmissionCase.ResolutionReason.REAPPEARED
        )
        # No source confirmation was ever requested by the census route.
        assert not _admissions_only_records()
        admission.refresh_from_db()
        prior_admission.refresh_from_db()
        assert admission.discharge_date is None
        assert prior_admission.discharge_date == T_BASE - timedelta(days=10)

    def test_gap_between_absences_starts_fresh_case_not_false_advance(
        self,
    ) -> None:
        """Reappearance resolves the case; a later absence starts over."""
        patient, _, absent_run = _make_absent_pair(
            "PRNT-D5", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=absent_run.pk, now=_at(11))
        reappeared = _make_census_run(
            _at(40), occupied_pronts=["PRNT-D5"]
        )
        observe_accepted_census_run(run_id=reappeared.pk, now=_at(41))
        absent_again = _make_census_run(_at(70), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=absent_again.pk, now=_at(71)
        )

        # The resolved case is not advanced; a fresh single-absence case.
        assert result["cases_advanced"] == 0
        assert result["cases_created"] == 1
        fresh = StaleAdmissionCase.objects.filter(
            resolved_at__isnull=True
        ).get()
        assert fresh.first_absence_run_id == absent_again.pk
        assert fresh.last_absence_run_id == absent_again.pk
        assert not _admissions_only_records()
        del patient

    def test_rejected_run_neither_advances_nor_resets(self) -> None:
        patient, _, absent_run = _make_absent_pair(
            "PRNT-D6", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=absent_run.pk, now=_at(11))

        # Rejected run with the patient absent: no advance.
        incomplete_absent = _make_census_run_incomplete(_at(20))
        result_absent = observe_accepted_census_run(
            run_id=incomplete_absent.pk, now=_at(21)
        )
        # Rejected run with the patient present: no reset/resolve either.
        incomplete_present = _make_census_run_incomplete(_at(30))
        CensusSnapshot.objects.filter(
            ingestion_run=incomplete_present
        ).update(prontuario="PRNT-D6", bed_status=BedStatus.OCCUPIED)
        result_present = observe_accepted_census_run(
            run_id=incomplete_present.pk, now=_at(31)
        )

        assert result_absent["cases_advanced"] == 0
        assert result_present["accepted"] is False
        assert result_present["cases_resolved_reappeared"] == 0
        case = StaleAdmissionCase.objects.get()
        assert case.last_absence_run_id == absent_run.pk
        del patient

    def test_absence_after_rejected_run_still_advances(self) -> None:
        """Accepted runs around a rejected run stay consecutive."""
        patient, _, absent_run = _make_absent_pair(
            "PRNT-D7", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=absent_run.pk, now=_at(11))
        _make_census_run_incomplete(_at(20))
        later_absent = _make_census_run(_at(50), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=later_absent.pk,
            now=_at(50) + timedelta(minutes=31),
        )

        assert result["cases_advanced"] == 1
        # Two consecutive accepted absences + >= 30 min -> bounded enqueue.
        assert len(_admissions_only_records()) == 1
        del patient

    def test_baseline_first_census_creates_no_cases(self) -> None:
        """The first usable complete census only sets the baseline."""
        patient = _make_patient("PRNT-D8")
        _make_open_admission(patient, "ADM_D8")
        first_census = _make_census_run(_at(0), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=first_census.pk, now=_at(1)
        )

        assert result["accepted"] is True
        assert result["cases_created"] == 0
        assert StaleAdmissionCase.objects.count() == 0


# ---------------------------------------------------------------------------
# Eligibility: 30-minute boundary and bounded enqueue
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEligibilityAndBoundedEnqueue:
    def test_second_absence_before_30min_is_not_eligible(self) -> None:
        patient, _, first_absent = _make_absent_pair(
            "PRNT-E1", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=first_absent.pk, now=_at(11))
        second_absent = _make_census_run(_at(39), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=second_absent.pk, now=_at(39)
        )

        assert result["cases_advanced"] == 1
        confirmation = result["confirmation"]
        assert isinstance(confirmation, dict)
        assert confirmation["not_yet_eligible"] == 1
        assert confirmation["enqueued_cases"] == 0
        assert not _admissions_only_records()
        del patient

    def test_exactly_30_minutes_is_eligible_boundary(self) -> None:
        patient, _, first_absent = _make_absent_pair(
            "PRNT-E2", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=first_absent.pk, now=_at(11))
        second_absent = _make_census_run(_at(40), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=second_absent.pk, now=_at(40)
        )

        assert result["cases_advanced"] == 1
        confirmation = result["confirmation"]
        assert isinstance(confirmation, dict)
        assert confirmation["enqueued_cases"] == 1
        assert _admissions_only_records() == ["PRNT-E2"]
        assert MIN_ELIGIBILITY_IDLE == timedelta(minutes=30)
        del patient

    def test_active_equivalent_run_deduplicates(self) -> None:
        from apps.ingestion.services import queue_admissions_only_run

        patient, _, first_absent = _make_absent_pair(
            "PRNT-E3", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=first_absent.pk, now=_at(11))
        queue_admissions_only_run(patient_record="PRNT-E3")
        second_absent = _make_census_run(_at(60), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=second_absent.pk, now=_at(60)
        )

        assert result["cases_advanced"] == 1
        confirmation = result["confirmation"]
        assert isinstance(confirmation, dict)
        assert confirmation["skipped_active_run"] == 1
        assert confirmation["enqueued_cases"] == 0
        assert _admissions_only_records() == ["PRNT-E3"]
        del patient

    def test_two_open_admissions_same_patient_enqueue_once(self) -> None:
        patient = _make_patient("PRNT-E4")
        first = _make_open_admission(patient, "ADM_E4_A")
        second = _make_open_admission(patient, "ADM_E4_B")
        _make_census_run(_at(0), occupied_pronts=["PRNT-E4"])
        first_absent = _make_census_run(_at(10), occupied_pronts=[])
        observe_accepted_census_run(run_id=first_absent.pk, now=_at(11))
        second_absent = _make_census_run(_at(60), occupied_pronts=[])

        observe_accepted_census_run(run_id=second_absent.pk, now=_at(60))

        # One patient-level sync for both per-admission cases.
        assert len(_admissions_only_records()) == 1
        assert StaleAdmissionCase.objects.filter(
            resolved_at__isnull=True
        ).count() == 2
        del first, second

    def test_cap_100_oldest_first_and_remainder_stay_eligible(
        self,
    ) -> None:
        for index in range(MAX_ENQUEUES_PER_CYCLE + 2):
            _make_two_absence_case(
                f"PRNT-F{index:03d}",
                first_absence_at=_at(10 + index),
                last_absence_at=_at(70 + index),
            )

        first_pass = evaluate_and_enqueue_stale_admission_cases(
            now=_at(200)
        )
        assert first_pass["enqueued_cases"] == MAX_ENQUEUES_PER_CYCLE
        assert first_pass["deferred_over_cap"] == 2
        records = _admissions_only_records()
        assert len(records) == MAX_ENQUEUES_PER_CYCLE
        assert set(records) == {
            f"PRNT-F{index:03d}" for index in range(MAX_ENQUEUES_PER_CYCLE)
        }

        # Remainder stays eligible: a second pass picks the deferred two.
        second_pass = evaluate_and_enqueue_stale_admission_cases(
            now=_at(201)
        )
        assert second_pass["enqueued_cases"] == 2
        assert set(_admissions_only_records()) == {
            f"PRNT-F{index:03d}"
            for index in range(MAX_ENQUEUES_PER_CYCLE + 2)
        }

    def test_exit_confirmed_resolution_when_admission_closed(self) -> None:
        patient = _make_patient("PRNT-E5")
        admission = _make_open_admission(patient, "ADM_E5")
        sync_run = IngestionRun.objects.create(
            status="succeeded",
            intent="admissions_only",
            parameters_json={
                "patient_record": "PRNT-E5",
                "intent": "admissions_only",
            },
            finished_at=_at(30),
        )
        baseline_run = _make_census_run(_at(0), occupied_pronts=[])
        StaleAdmissionCase.objects.create(
            admission=admission,
            first_absence_run=baseline_run,
            first_absence_at=_at(10),
            last_absence_run=sync_run,
            last_absence_at=_at(20),
            last_enqueued_run=sync_run,
            last_enqueued_at=_at(20),
        )
        # The canonical reconciler closed the admission from real evidence.
        admission.discharge_date = _at(25)
        admission.save(update_fields=["discharge_date"])

        result = evaluate_and_enqueue_stale_admission_cases(now=_at(40))

        assert result["resolved_exit_confirmed"] == 1
        case = StaleAdmissionCase.objects.get()
        assert case.resolved_at == _at(40)
        assert (
            case.resolution_reason
            == StaleAdmissionCase.ResolutionReason.EXIT_CONFIRMED
        )
        # Only the pre-existing synthetic confirmation run exists; the
        # pass must not have enqueued anything new.
        assert _admissions_only_records() == ["PRNT-E5"]

    def test_explicit_exit_evidence_is_independent_of_census_waiting(
        self,
    ) -> None:
        """Pending exit evidence neither blocks absence confirmation nor
        is it mutated by the census route (no imposed ordering)."""
        from apps.discharges.models import DischargeRecord

        patient, _, first_absent = _make_absent_pair(
            "PRNT-E6", present_at=_at(0), absent_at=_at(10)
        )
        evidence = DischargeRecord.objects.create(
            prontuario="PRNT-E6",
            data_internacao="01/01/2026",
            saida_em=_at(5),
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
        )
        observe_accepted_census_run(run_id=first_absent.pk, now=_at(11))
        second_absent = _make_census_run(_at(60), occupied_pronts=[])

        result = observe_accepted_census_run(
            run_id=second_absent.pk, now=_at(60)
        )

        confirmation = result["confirmation"]
        assert isinstance(confirmation, dict)
        assert confirmation["enqueued_cases"] == 1
        evidence.refresh_from_db()
        assert evidence.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert evidence.admission_id is None
        admission = Admission.objects.get(source_admission_key="ADM_PRNT-E6")
        assert admission.discharge_date is None
        del patient, admission


# ---------------------------------------------------------------------------
# Cooldowns: 6h inconclusive / 24h conclusive-no-exit (equality eligible)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCooldowns:
    def _make_enqueued_case(
        self, pront: str
    ) -> tuple[StaleAdmissionCase, IngestionRun]:
        case, _, _ = _make_two_absence_case(
            pront,
            first_absence_at=_at(10),
            last_absence_at=_at(15),
        )
        sync_run = IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            parameters_json={
                "patient_record": pront,
                "intent": "admissions_only",
            },
        )
        case.last_enqueued_run = sync_run
        case.last_enqueued_at = _at(15)
        case.save(
            update_fields=["last_enqueued_run", "last_enqueued_at"]
        )
        return case, sync_run

    def test_failed_sync_classifies_inconclusive_and_cools_down_6h(
        self,
    ) -> None:
        case, sync_run = self._make_enqueued_case("PRNT-G1")
        sync_run.status = "failed"
        sync_run.finished_at = _at(30)
        sync_run.save(update_fields=["status", "finished_at"])

        classified = evaluate_and_enqueue_stale_admission_cases(now=_at(31))
        assert classified["classified_inconclusive"] == 1
        case.refresh_from_db()
        assert (
            case.last_enqueue_outcome
            == StaleAdmissionCase.EnqueueOutcome.INCONCLUSIVE
        )
        assert case.last_outcome_at == _at(30)

        before = evaluate_and_enqueue_stale_admission_cases(
            now=_at(30) + INCONCLUSIVE_COOLDOWN - timedelta(seconds=1)
        )
        assert before["skipped_cooldown"] == 1
        assert before["enqueued_cases"] == 0

        boundary = evaluate_and_enqueue_stale_admission_cases(
            now=_at(30) + INCONCLUSIVE_COOLDOWN
        )
        assert boundary["enqueued_cases"] == 1
        assert INCONCLUSIVE_COOLDOWN == timedelta(hours=6)
        case.refresh_from_db()
        assert case.last_enqueue_outcome == ""
        assert case.last_enqueued_run_id != sync_run.pk

    def test_succeeded_sync_classifies_conclusive_no_exit_and_cools_24h(
        self,
    ) -> None:
        case, sync_run = self._make_enqueued_case("PRNT-G2")
        sync_run.status = "succeeded"
        sync_run.finished_at = _at(30)
        sync_run.save(update_fields=["status", "finished_at"])

        classified = evaluate_and_enqueue_stale_admission_cases(now=_at(31))
        assert classified["classified_conclusive"] == 1
        case.refresh_from_db()
        assert (
            case.last_enqueue_outcome
            == StaleAdmissionCase.EnqueueOutcome.CONCLUSIVE_NO_EXIT
        )

        before = evaluate_and_enqueue_stale_admission_cases(
            now=_at(30) + CONCLUSIVE_NO_EXIT_COOLDOWN - timedelta(seconds=1)
        )
        assert before["skipped_cooldown"] == 1
        assert before["enqueued_cases"] == 0

        boundary = evaluate_and_enqueue_stale_admission_cases(
            now=_at(30) + CONCLUSIVE_NO_EXIT_COOLDOWN
        )
        assert boundary["enqueued_cases"] == 1
        assert CONCLUSIVE_NO_EXIT_COOLDOWN == timedelta(hours=24)

    def test_unclassified_active_run_blocks_via_dedup_not_cooldown(
        self,
    ) -> None:
        case, sync_run = self._make_enqueued_case("PRNT-G3")
        del case  # run still queued/active: dedup, not cooldown

        result = evaluate_and_enqueue_stale_admission_cases(now=_at(40))

        assert result["skipped_active_run"] == 1
        assert result["skipped_cooldown"] == 0
        assert result["classified_inconclusive"] == 0
        sync_run.refresh_from_db()
        assert sync_run.status == "queued"


# ---------------------------------------------------------------------------
# Conflict-evidence sync route
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConflictEvidenceRoute:
    def _make_conflict_discharge(
        self, pront: str, reconciled_at: datetime
    ) -> None:
        from apps.discharges.models import DischargeRecord

        DischargeRecord.objects.create(
            prontuario=pront,
            data_internacao="01/02/2026",
            reconciliation_status=RECONCILIATION_STATUS_CONFLICT,
            reconciled_at=reconciled_at,
        )

    def _make_conflict_death(
        self, pront: str, reconciled_at: datetime
    ) -> None:
        from apps.deaths.models import DeathRecord

        DeathRecord.objects.create(
            date=reconciled_at.date(),
            prontuario=pront,
            reconciliation_status=RECONCILIATION_STATUS_CONFLICT,
            reconciled_at=reconciled_at,
        )

    def test_conflict_discharge_enqueues_after_24h_boundary(self) -> None:
        self._make_conflict_discharge("PRNT-H1", _at(0))

        before = evaluate_and_enqueue_stale_admission_cases(
            now=_at(0) + CONCLUSIVE_NO_EXIT_COOLDOWN - timedelta(seconds=1)
        )
        assert before["enqueued_conflict"] == 0

        boundary = evaluate_and_enqueue_stale_admission_cases(
            now=_at(0) + CONCLUSIVE_NO_EXIT_COOLDOWN
        )
        assert boundary["enqueued_conflict"] == 1
        assert _admissions_only_records() == ["PRNT-H1"]

    def test_conflict_death_and_discharge_rows_enqueue_single_run(
        self,
    ) -> None:
        """Two conflict rows of one patient -> exactly one dedup run."""
        self._make_conflict_discharge("PRNT-H2", _at(0))
        self._make_conflict_death("PRNT-H2", _at(60))

        result = evaluate_and_enqueue_stale_admission_cases(
            now=_at(60) + CONCLUSIVE_NO_EXIT_COOLDOWN
        )

        assert result["enqueued_conflict"] == 1
        assert _admissions_only_records() == ["PRNT-H2"]

    def test_non_conflict_rows_are_never_re_enqueued(self) -> None:
        from apps.deaths.models import DeathRecord
        from apps.discharges.models import DischargeRecord

        old = T_BASE - timedelta(days=30)
        for status in (
            RECONCILIATION_STATUS_PENDING,
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
            RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
        ):
            DischargeRecord.objects.create(
                prontuario=f"PRNT-I-{status}",
                data_internacao="01/02/2026",
                reconciliation_status=status,
                reconciled_at=old,
            )
        DeathRecord.objects.create(
            date=old.date(),
            prontuario="PRNT-I-DEATH-PENDING",
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
            reconciled_at=old,
        )

        result = evaluate_and_enqueue_stale_admission_cases(now=_at(5000))

        assert result["enqueued_conflict"] == 0
        assert not _admissions_only_records()

    def test_conflict_route_respects_active_run_dedup(self) -> None:
        from apps.ingestion.services import queue_admissions_only_run

        self._make_conflict_discharge("PRNT-H3", T_BASE - timedelta(days=2))
        queue_admissions_only_run(patient_record="PRNT-H3")

        result = evaluate_and_enqueue_stale_admission_cases(now=_at(5000))

        assert result["enqueued_conflict"] == 0
        assert result["skipped_active_run"] == 1
        assert _admissions_only_records() == ["PRNT-H3"]

    def test_conflict_route_shares_cap_with_cases(self) -> None:
        for index in range(MAX_ENQUEUES_PER_CYCLE):
            _make_two_absence_case(
                f"PRNT-J{index:03d}",
                first_absence_at=_at(10 + index),
                last_absence_at=_at(70 + index),
            )
        self._make_conflict_discharge("PRNT-H4", _at(0))

        result = evaluate_and_enqueue_stale_admission_cases(now=_at(5000))

        total = result["enqueued_cases"] + result["enqueued_conflict"]
        assert total <= MAX_ENQUEUES_PER_CYCLE
        assert result["deferred_over_cap"] >= 1


# ---------------------------------------------------------------------------
# Model constraints and safety sweep lock
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCaseModelAndLock:
    def test_only_one_open_case_per_admission(self) -> None:
        patient = _make_patient("PRNT-K1")
        admission = _make_open_admission(patient, "ADM_K1")
        run = _make_census_run(_at(0), occupied_pronts=[])
        StaleAdmissionCase.objects.create(
            admission=admission,
            first_absence_run=run,
            first_absence_at=_at(1),
            last_absence_run=run,
            last_absence_at=_at(2),
        )

        with pytest.raises(IntegrityError):
            StaleAdmissionCase.objects.create(
                admission=admission,
                first_absence_run=run,
                first_absence_at=_at(3),
                last_absence_run=run,
                last_absence_at=_at(4),
            )

    def test_sweep_lock_key_differs_from_orchestrator_key(self) -> None:
        from apps.census.orchestration import ADVISORY_LOCK_KEY

        assert STALE_ADMISSION_SWEEP_LOCK_KEY != ADVISORY_LOCK_KEY

    def test_sweep_lock_acquire_release_roundtrip(self) -> None:
        assert acquire_stale_admission_sweep_lock() is True
        assert release_stale_admission_sweep_lock() is True
        assert release_stale_admission_sweep_lock() is False


# ---------------------------------------------------------------------------
# Identity safety and clinical safety
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIdentitySafety:
    def test_results_and_logs_carry_no_patient_identity(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        patient = _make_patient("PRNT-L1")
        admission = _make_open_admission(patient, "ADM_L1")
        _make_census_run(_at(0), occupied_pronts=["PRNT-L1"])
        absent_run = _make_census_run(_at(10), occupied_pronts=[])

        with caplog.at_level(
            logging.INFO, logger="apps.census.stale_admissions"
        ):
            observation = observe_accepted_census_run(
                run_id=absent_run.pk, now=_at(11)
            )
            confirmation = evaluate_and_enqueue_stale_admission_cases(
                now=_at(12)
            )

        serialized = json.dumps(
            {"observation": observation, "confirmation": confirmation}
        )
        for value in ("PRNT-L1", "ADM_L1", "PACIENTE PRNT-L1"):
            assert value not in serialized
        assert "PRNT-L1" not in caplog.text
        assert "ADM_L1" not in caplog.text
        del admission

    def test_absence_never_writes_discharge_date(self) -> None:
        """Full lifecycle leaves the clinical exit state untouched."""
        patient, admission, absent_run = _make_absent_pair(
            "PRNT-L2", present_at=_at(0), absent_at=_at(10)
        )
        observe_accepted_census_run(run_id=absent_run.pk, now=_at(11))
        second_absent = _make_census_run(_at(60), occupied_pronts=[])
        observe_accepted_census_run(run_id=second_absent.pk, now=_at(60))
        evaluate_and_enqueue_stale_admission_cases(now=_at(61))

        admission.refresh_from_db()
        assert admission.discharge_date is None
        assert (
            Admission.objects.filter(
                discharge_date__isnull=False
            ).count()
            == 0
        )
        del patient
