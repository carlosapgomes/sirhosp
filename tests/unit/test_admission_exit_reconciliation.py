"""Evidence-linked hospital-discharge reconciliation (RPSA-S2).

Covers the canonical exit taxonomy (exactly eight reconciliation
statuses), the pure ordered match decision (current key, alias, exact
start, unique ``America/Bahia`` local date — skipping unavailable
levels), the transactional locked application with append-only audit,
and the evidence-side service entry point
(:func:`apps.discharges.services.reconcile_discharge_record`).

``saida_em`` is the only authoritative closing time; ``alta_em`` never
closes an admission. All fixtures are synthetic.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from apps.discharges.models import DischargeRecord
from apps.discharges.services import reconcile_discharge_record
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    EXIT_HOSPITAL_DISCHARGE,
    EXIT_TYPES,
    RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_INVALID_EXIT_DATETIME,
    RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    RECONCILIATION_STATUSES,
    Admission,
    Patient,
    ReconciliationEvent,
)
from apps.patients.reconciliation import (
    DischargeExitEvidence,
    apply_discharge_exit,
    decide_discharge_match,
)

TZ_LOCAL = ZoneInfo("America/Bahia")


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str | None,
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=(
            datetime.fromisoformat(start).replace(tzinfo=TZ_LOCAL)
            if start
            else None
        ),
        discharge_date=(
            datetime.fromisoformat(end).replace(tzinfo=TZ_LOCAL) if end else None
        ),
    )


def _evidence(**overrides: Any) -> DischargeExitEvidence:
    base: dict[str, Any] = dict(
        patient_record="777",
        exit_datetime=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        admission_key=None,
        admission_start=None,
        admission_local_date=date(2026, 5, 20),
        source_system="tasy",
    )
    base.update(overrides)
    return DischargeExitEvidence(**base)


def _make_record(
    admission: Admission | None,
    *,
    prontuario: str = "777",
    data_internacao: str = "20/05/2026",
    saida: datetime | None = None,
    alta: datetime | None = None,
) -> DischargeRecord:
    return DischargeRecord.objects.create(
        admission=admission,
        alta_em=alta,
        saida_em=saida,
        prontuario=prontuario,
        nome=f"PACIENTE {prontuario}",
        data_internacao=data_internacao,
        leito="UN01H",
        especialidade="CLI",
    )


# =========================================================================
# Taxonomy pins
# =========================================================================


class TestStatusAndExitTaxonomy:
    def test_statuses_are_exactly_the_eight_specified_values(self):
        assert set(RECONCILIATION_STATUSES) == {
            "pending",
            "reconciled",
            "already_reconciled",
            "patient_not_found",
            "admission_not_found",
            "ambiguous",
            "conflict",
            "invalid_exit_datetime",
        }
        assert len(RECONCILIATION_STATUSES) == 8

    def test_exit_types_are_deliberately_minimal(self):
        assert set(EXIT_TYPES) == {"hospital_discharge", "death", "unknown"}


# =========================================================================
# Pure ordered match decision
# =========================================================================


@pytest.mark.django_db
class TestDecideDischargeMatch:
    def test_patient_not_found_when_mirror_lacks_patient(self):
        decision = decide_discharge_match(evidence=_evidence())
        assert decision.status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        assert decision.admission is None

    def test_current_key_match_wins_over_weaker_levels(self):
        patient = _make_patient("777")
        keyed = _make_admission(patient, "ADM-KEY", "2026-05-20T08:00:00")
        _make_admission(patient, "ADM-OTHER", "2026-05-21T08:00:00")
        decision = decide_discharge_match(
            evidence=_evidence(
                admission_key="ADM-KEY",
                admission_local_date=date(2026, 5, 21),
            )
        )
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.admission is not None
        assert decision.admission.pk == keyed.pk
        assert decision.match_reason == "current_key"

    def test_alias_match_used_when_key_unknown(self):
        patient = _make_patient("777")
        aliased = _make_admission(patient, "ADM-NEW", "2026-05-20T08:00:00")
        aliased.source_aliases.create(source_system="tasy", alias_key="ADM-OLD")
        decision = decide_discharge_match(
            evidence=_evidence(admission_key="ADM-OLD")
        )
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.admission is not None
        assert decision.admission.pk == aliased.pk
        assert decision.match_reason == "alias"

    def test_unique_local_date_match_with_local_date_precision_only(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T09:30:00")
        decision = decide_discharge_match(evidence=_evidence())
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.admission is not None
        assert decision.admission.pk == admission.pk
        assert decision.match_reason == "unique_local_date"
        assert decision.exit_type == EXIT_HOSPITAL_DISCHARGE

    def test_local_date_only_never_claims_exact_start(self):
        """``data_internacao`` is a local date, never an exact-start claim."""
        patient = _make_patient("777")
        _make_admission(patient, "ADM-1", "2026-05-20T00:00:00")
        decision = decide_discharge_match(evidence=_evidence())
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.match_reason == "unique_local_date"

    def test_invalid_or_missing_local_date_is_admission_not_found(self):
        """No date/key precision: never fall back to the latest admission."""
        patient = _make_patient("777")
        _make_admission(patient, "ADM-1", "2026-05-20T09:30:00")
        decision = decide_discharge_match(
            evidence=_evidence(admission_local_date=None)
        )
        assert decision.status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        assert decision.admission is None

    def test_exit_equal_to_admission_start_is_reconciled(self):
        """Equality boundary: exit exactly equal to the admission start is
        a valid close (strict ``<``), never ``invalid_exit_datetime``."""
        patient = _make_patient("777")
        boundary = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        admission = _make_admission(patient, "ADM-1", "2026-06-01T12:00:00")
        decision = decide_discharge_match(
            evidence=_evidence(
                admission_local_date=date(2026, 6, 1),
                exit_datetime=boundary,
            )
        )
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.admission is not None
        assert decision.admission.pk == admission.pk

    def test_same_day_two_candidates_are_ambiguous(self):
        patient = _make_patient("777")
        _make_admission(patient, "ADM-A", "2026-05-20T08:00:00")
        _make_admission(patient, "ADM-B", "2026-05-20T16:00:00")
        decision = decide_discharge_match(evidence=_evidence())
        assert decision.status == RECONCILIATION_STATUS_AMBIGUOUS
        assert decision.admission is None
        assert decision.candidate_count == 2

    def test_key_match_with_null_start_is_conflict(self):
        patient = _make_patient("777")
        _make_admission(patient, "ADM-KEY", None)
        decision = decide_discharge_match(
            evidence=_evidence(admission_key="ADM-KEY")
        )
        assert decision.status == RECONCILIATION_STATUS_CONFLICT
        assert decision.reason_code == "null_admission_start"

    def test_contradictory_strong_ids_are_conflict(self):
        patient = _make_patient("777")
        keyed = _make_admission(patient, "ADM-KEY", "2026-05-20T08:00:00")
        other = _make_admission(patient, "ADM-B", "2026-05-21T09:00:00")
        decision = decide_discharge_match(
            evidence=_evidence(
                admission_key="ADM-KEY",
                admission_start=datetime(2026, 5, 21, 9, 0, tzinfo=TZ_LOCAL),
            )
        )
        assert decision.status == RECONCILIATION_STATUS_CONFLICT
        assert decision.reason_code == "contradictory_strong_ids"
        assert decision.admission is not None
        assert decision.admission.pk == keyed.pk
        assert decision.admission.pk != other.pk

    def test_exit_before_admission_is_invalid(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        decision = decide_discharge_match(
            evidence=_evidence(
                exit_datetime=datetime(2026, 5, 20, 7, 0, tzinfo=TZ_LOCAL),
            )
        )
        assert decision.status == RECONCILIATION_STATUS_INVALID_EXIT_DATETIME
        assert decision.admission is not None
        assert decision.admission.pk == admission.pk

    def test_closed_at_same_time_is_already_reconciled(self):
        patient = _make_patient("777")
        _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-01T12:00:00",
        )
        decision = decide_discharge_match(evidence=_evidence())
        assert decision.status == RECONCILIATION_STATUS_ALREADY_RECONCILED

    def test_closed_at_other_time_is_reconciled_correction(self):
        patient = _make_patient("777")
        _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-01T15:00:00",
        )
        decision = decide_discharge_match(evidence=_evidence())
        assert decision.status == RECONCILIATION_STATUS_RECONCILED

    def test_missing_exit_is_pending(self):
        decision = decide_discharge_match(
            evidence=_evidence(exit_datetime=None)
        )
        assert decision.status == RECONCILIATION_STATUS_PENDING


# =========================================================================
# Transactional locked application
# =========================================================================


@pytest.mark.django_db
class TestApplyDischargeExit:
    def _reconciled_decision(self, admission: Admission):
        from apps.patients.reconciliation import DischargeMatchDecision

        return DischargeMatchDecision(
            status=RECONCILIATION_STATUS_RECONCILED,
            admission=admission,
            match_reason="unique_local_date",
            candidate_count=1,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
        )

    def test_reconciled_stores_exact_aware_timestamp_and_audits(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        exit_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)

        status = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == exit_at

        event = ReconciliationEvent.objects.get()
        assert event.status == RECONCILIATION_STATUS_RECONCILED
        assert event.exit_type == EXIT_HOSPITAL_DISCHARGE
        assert event.source_kind == "discharge_record"
        assert event.source_id == 42
        assert event.prior_discharge_date is None
        assert event.new_discharge_date == exit_at
        assert event.admission_id == admission.pk

    def test_repeat_is_already_reconciled_without_duplicate_audit(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        exit_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)

        first = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )
        second = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert first == RECONCILIATION_STATUS_RECONCILED
        assert second == RECONCILIATION_STATUS_ALREADY_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == exit_at
        assert ReconciliationEvent.objects.count() == 1

    def test_first_time_evidence_pre_closed_by_other_writer_gets_one_event(self):
        """Audit gap fix: evidence whose matched admission was already
        closed at the same discharge time by a DIFFERENT writer gets
        linkage plus exactly one structural ``already_reconciled`` event
        of its own — append-only audit of every attempted reconciliation.
        """
        patient = _make_patient("777")
        exit_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        # Another writer pre-closed the admission at the same instant —
        # simulated by seeding discharge_date directly (the legacy PDF
        # flow itself is not exercised here).
        admission = _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-01T12:00:00",
        )

        status = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert status == RECONCILIATION_STATUS_ALREADY_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == exit_at  # no clinical change here
        assert ReconciliationEvent.objects.count() == 1
        event = ReconciliationEvent.objects.get()
        assert event.status == RECONCILIATION_STATUS_ALREADY_RECONCILED
        assert event.source_kind == "discharge_record"
        assert event.source_id == 42
        assert event.prior_discharge_date == exit_at
        assert event.new_discharge_date is None

    def test_same_evidence_repeat_of_already_reconciled_writes_no_duplicate(self):
        """Same-evidence idempotency is preserved on the
        ``already_reconciled`` branch: a re-extraction of a record that
        already has its own audit event appends no duplicate row.
        """
        patient = _make_patient("777")
        exit_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        admission = _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-01T12:00:00",
        )

        first = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )
        second = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=exit_at,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert first == RECONCILIATION_STATUS_ALREADY_RECONCILED
        assert second == RECONCILIATION_STATUS_ALREADY_RECONCILED
        assert ReconciliationEvent.objects.count() == 1

    def test_correction_records_prior_and_new_in_audit(self):
        patient = _make_patient("777")
        prior_exit = datetime(2026, 6, 1, 15, 0, tzinfo=TZ_LOCAL)
        admission = _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-01T15:00:00",
        )
        corrected = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)

        status = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=corrected,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == corrected

        event = ReconciliationEvent.objects.get()
        assert event.prior_discharge_date == prior_exit
        assert event.new_discharge_date == corrected

    def test_invalid_exit_leaves_admission_unchanged_and_audits(self):
        from apps.patients.reconciliation import DischargeMatchDecision

        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        decision = DischargeMatchDecision(
            status=RECONCILIATION_STATUS_INVALID_EXIT_DATETIME,
            admission=admission,
            match_reason="unique_local_date",
            candidate_count=1,
        )

        status = apply_discharge_exit(
            decision=decision,
            exit_datetime=datetime(2026, 5, 20, 7, 0, tzinfo=TZ_LOCAL),
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert status == RECONCILIATION_STATUS_INVALID_EXIT_DATETIME
        admission.refresh_from_db()
        assert admission.discharge_date is None
        event = ReconciliationEvent.objects.get()
        assert event.status == RECONCILIATION_STATUS_INVALID_EXIT_DATETIME
        assert event.prior_discharge_date is None
        assert event.new_discharge_date is None

    def test_locked_equality_boundary_is_reconciled(self):
        """Under lock, exit exactly equal to the admission start re-derives
        ``reconciled`` (strict ``<``), never ``invalid_exit_datetime``."""
        patient = _make_patient("777")
        boundary = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        admission = _make_admission(patient, "ADM-1", "2026-06-01T12:00:00")

        status = apply_discharge_exit(
            decision=self._reconciled_decision(admission),
            exit_datetime=boundary,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind="discharge_record",
            source_id=42,
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == boundary
        event = ReconciliationEvent.objects.get()
        assert event.status == RECONCILIATION_STATUS_RECONCILED


# =========================================================================
# Evidence-side service entry point
# =========================================================================


@pytest.mark.django_db
class TestReconcileDischargeRecord:
    def test_valid_saida_closes_and_links_evidence(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        saida = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        record = _make_record(None, saida=saida)

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == saida
        record.refresh_from_db()
        assert record.admission_id == admission.pk
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        assert record.reconciled_at is not None
        assert ReconciliationEvent.objects.count() == 1

    def test_alta_only_row_stays_pending_and_admission_open(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        alta = datetime(2026, 6, 1, 10, 0, tzinfo=TZ_LOCAL)
        record = _make_record(None, alta=alta, saida=None)

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_PENDING
        admission.refresh_from_db()
        assert admission.discharge_date is None
        record.refresh_from_db()
        assert record.admission_id is None
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert ReconciliationEvent.objects.count() == 0

    def test_repeated_application_is_idempotent(self):
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        saida = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        record = _make_record(None, saida=saida)

        first = reconcile_discharge_record(record=record)
        second = reconcile_discharge_record(record=record)

        assert first == RECONCILIATION_STATUS_RECONCILED
        assert second == RECONCILIATION_STATUS_ALREADY_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == saida
        assert ReconciliationEvent.objects.count() == 1
        assert Admission.objects.count() == 1

    def test_prior_failed_attempt_does_not_block_already_reconciled_audit(self):
        """A prior non-reconcilable event of the same evidence (e.g.
        ``patient_not_found`` while the mirror lacked the patient) never
        covers the structural linkage audit: once the patient is mirrored
        and the admission turns out pre-closed at the same exit by another
        writer (simulated by seeded ``discharge_date``), the
        re-reconciled evidence appends exactly one ``already_reconciled``
        event — 2 events total (failed attempt + structural one)."""
        exit_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        record = _make_record(
            None,
            prontuario="888",
            data_internacao="20/05/2026",
            saida=exit_at,
        )

        first = reconcile_discharge_record(record=record)
        assert first == RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        assert ReconciliationEvent.objects.count() == 1
        assert (
            ReconciliationEvent.objects.get().status
            == RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        )

        # The mirror now holds the patient; the admission was pre-closed
        # at the same saida_em by another writer (simulated: state seeded
        # directly, not through the legacy PDF flow).
        patient = _make_patient("888")
        admission = _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-01T12:00:00",
        )

        second = reconcile_discharge_record(record=record)

        assert second == RECONCILIATION_STATUS_ALREADY_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == exit_at  # unchanged
        assert ReconciliationEvent.objects.count() == 2
        assert list(
            ReconciliationEvent.objects.order_by("pk").values_list(
                "status", flat=True
            )
        ) == [
            RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
            RECONCILIATION_STATUS_ALREADY_RECONCILED,
        ]
        structural = ReconciliationEvent.objects.order_by("pk").last()
        assert structural.source_id == record.pk
        assert structural.prior_discharge_date == exit_at
        assert structural.new_discharge_date is None
        record.refresh_from_db()
        assert record.admission_id == admission.pk
        assert (
            record.reconciliation_status
            == RECONCILIATION_STATUS_ALREADY_RECONCILED
        )

    def test_unparseable_local_date_does_not_pick_latest_admission(self):
        """A real unparseable ``data_internacao`` string (XLS adapter parse
        layer via :func:`apps.discharges.services._parse_admission_date`,
        reached through the public path) yields no local-date precision:
        the row is ``admission_not_found`` and no admission is touched —
        there is never a latest-admission fallback."""
        patient = _make_patient("777")
        admission = _make_admission(patient, "ADM-LATEST", "2026-05-30T09:30:00")
        record = _make_record(
            None,
            data_internacao="31/02/2026",  # February 31st never exists
            saida=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        )

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        admission.refresh_from_db()
        assert admission.discharge_date is None
        assert Admission.objects.count() == 1
        record.refresh_from_db()
        assert record.admission_id is None
        assert (
            record.reconciliation_status
            == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        )

    def test_missing_patient_enqueues_bounded_sync_without_synthetic_rows(self):
        record = _make_record(
            None,
            prontuario="404",
            saida=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        )

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        assert Patient.objects.filter(patient_source_key="404").count() == 0
        assert Admission.objects.count() == 0
        record.refresh_from_db()
        assert record.admission_id is None
        assert record.reconciliation_status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND

        admissions_runs = IngestionRun.objects.filter(intent="admissions_only")
        demographics_runs = IngestionRun.objects.filter(
            intent="demographics_only"
        )
        assert admissions_runs.count() == 1
        assert demographics_runs.count() == 1
        assert (
            admissions_runs.get().parameters_json["patient_record"] == "404"
        )

    def test_missing_patient_sync_is_bounded_to_one_active_run(self):
        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            parameters_json={
                "patient_record": "404",
                "intent": "admissions_only",
            },
        )
        record = _make_record(
            None,
            prontuario="404",
            saida=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        )

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        assert IngestionRun.objects.filter(intent="admissions_only").count() == 1

    def test_missing_admission_enqueues_admissions_only(self):
        # Patient exists in the mirror; no admission matches the evidence.
        _make_patient("777")
        record = _make_record(
            None,
            data_internacao="01/03/2026",
            saida=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        )

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        assert Admission.objects.count() == 0
        assert IngestionRun.objects.filter(intent="admissions_only").count() == 1
        assert IngestionRun.objects.filter(intent="demographics_only").count() == 0

    def test_logs_are_identity_safe(self, caplog):
        import logging

        patient = _make_patient("777")
        _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_record(
            None,
            saida=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        )

        with caplog.at_level(logging.INFO):
            reconcile_discharge_record(record=record)
            # Also exercise the unresolved path.
            missing = _make_record(
                None,
                prontuario="404",
                data_internacao="01/03/2026",
                saida=datetime(2026, 6, 1, 13, 0, tzinfo=TZ_LOCAL),
            )
            reconcile_discharge_record(record=missing)

        joined = caplog.text
        assert "777" not in joined
        assert "404" not in joined
        assert "PACIENTE 777" not in joined

    def test_audit_payloads_carry_no_patient_identity(self):
        patient = _make_patient("777")
        _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_record(
            None,
            saida=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        )
        reconcile_discharge_record(record=record)

        event = ReconciliationEvent.objects.get()
        payload = json.dumps(
            {
                "details": event.details_json,
                "reason": event.reason_code,
                "status": event.status,
            }
        )
        assert "777" not in payload
        assert "PACIENTE" not in payload
        assert event.source_kind == "discharge_record"
