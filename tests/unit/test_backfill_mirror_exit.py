"""Mirror-exit backfill cohort planning, apply and rollback (BME-S1/S2).

Covers the ``mirror_exits`` cohort of the dry-run planner: pending
``DischargeRecord`` evidence whose unique closed canonical admission
mirrors the exit (``admission_date <= alta_em <= discharge_date``), the
explicit manual-review reasons (``discharges:mirror_ambiguous`` /
``discharges:mirror_patient_not_found``), the plan order, the ``--limit``
bound, the command dry-run/apply lines and — for apply/rollback — the
provenance event, the untouched ``Admission``, the idempotent replan and
the evidence restoration inside the backfill rollback.

All fixtures are synthetic and carry no real patient data.
"""

from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.patients.models import (
    EXIT_HOSPITAL_DISCHARGE,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

TZ_LOCAL = ZoneInfo("America/Bahia")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ_LOCAL)


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SIGILOSO {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str,
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt(start),
        discharge_date=_dt(end) if end else None,
        source_patient_reference=f"PRONT-REF-{key}",
    )


def _make_discharge(
    prontuario: str,
    *,
    saida: str | None,
    alta: str | None,
    internacao: str,
) -> DischargeRecord:
    return DischargeRecord.objects.create(
        prontuario=prontuario,
        data_internacao=internacao,
        saida_em=_dt(saida) if saida else None,
        alta_em=_dt(alta) if alta else None,
        nome=f"PACIENTE SIGILOSO {prontuario}",
    )


def _make_mirror_evidence(
    patient_key: str,
    *,
    anchor_key: str,
    anchor_start: str,
    anchor_end: str,
    alta: str,
) -> tuple[Patient, Admission, DischargeRecord]:
    """One pending discharge record corroborated by one closed anchor.

    The record carries a valid ``alta_em`` inside the closed anchor
    period and no ``saida_em``, so it is never eligible for the exact
    discharge cohort (and never double-claims an exact item).
    """
    patient = _make_patient(patient_key)
    anchor = _make_admission(
        patient, anchor_key, anchor_start, anchor_end
    )
    record = _make_discharge(
        patient_key,
        saida=None,
        alta=alta,
        internacao="01/05/2026",
    )
    return patient, anchor, record


def _plan_mirror_ids(plan) -> list[int]:
    return [
        item.payload.record_id
        for item in plan.mirror_exits.items
    ]


def _admission_snapshot(admission: Admission) -> dict:
    """Byte-level snapshot of every concrete column of one Admission."""
    return {
        field.attname: getattr(admission, field.attname)
        for field in admission._meta.concrete_fields
    }


# ---------------------------------------------------------------------------
# Mirror-exit cohort selection (R1-R6): pure planning
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMirrorExitPlannerCohort:
    """Cohort selection rules of the mirror_exits planner cohort."""

    def test_unique_closed_anchor_is_eligible(self):
        from apps.patients.backfill import build_backfill_plan

        _, anchor, record = _make_mirror_evidence(
            "MX-1",
            anchor_key="MX-1-ADM",
            anchor_start="2026-05-20T08:00:00",
            anchor_end="2026-06-02T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        assert anchor.discharge_date is not None

        plan = build_backfill_plan()

        assert plan.mirror_exits.cohort == "mirror_exits"
        assert plan.mirror_exits.total == 1
        assert _plan_mirror_ids(plan) == [record.pk]
        assert plan.mirror_exits.truncated is False

    def test_two_closed_candidates_go_to_manual_review(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("MX-2")
        _make_admission(
            patient, "MX-2-A", "2026-05-01T08:00:00", "2026-06-10T10:00:00"
        )
        _make_admission(
            patient, "MX-2-B", "2026-05-15T08:00:00", "2026-06-05T10:00:00"
        )
        _make_discharge(
            "MX-2",
            saida=None,
            alta="2026-05-20T09:00:00",
            internacao="01/05/2026",
        )

        plan = build_backfill_plan()

        assert plan.mirror_exits.total == 0
        assert plan.manual_review["discharges:mirror_ambiguous"] == 1

    def test_unresolvable_patient_goes_to_manual_review(self):
        from apps.patients.backfill import build_backfill_plan

        _make_discharge(
            "MX-3-NOPE",
            saida=None,
            alta="2026-06-01T09:00:00",
            internacao="01/05/2026",
        )

        plan = build_backfill_plan()

        assert plan.mirror_exits.total == 0
        assert plan.manual_review["discharges:mirror_patient_not_found"] == 1

    def test_null_alta_em_stays_missing_saida_em(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("MX-4")
        _make_admission(
            patient, "MX-4-ADM", "2026-05-01T08:00:00", "2026-06-10T10:00:00"
        )
        _make_discharge(
            "MX-4", saida=None, alta=None, internacao="01/05/2026"
        )

        plan = build_backfill_plan()

        # No valid alta_em: never a mirror candidate; the evidence keeps
        # the existing discharge review reason.
        assert plan.mirror_exits.total == 0
        assert _plan_mirror_ids(plan) == []
        assert plan.manual_review["discharges:missing_saida_em"] == 1
        assert "mirror" not in " ".join(plan.manual_review)

    def test_open_admission_never_becomes_mirror(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("MX-5")
        _make_admission(patient, "MX-5-ADM", "2026-06-20T08:00:00")
        record = _make_discharge(
            "MX-5",
            saida="2026-06-25T10:00:00",
            alta="2026-06-25T10:00:00",
            internacao="20/06/2026",
        )

        plan = build_backfill_plan()

        # The exact cohort replays the open anchor; mirror never claims it.
        assert plan.discharges.total == 1
        assert plan.discharges.items[0].payload.record_id == record.pk
        assert plan.mirror_exits.total == 0

    def test_conflict_status_evidence_is_never_mirror_planned(self):
        """P1-2 regression: only genuinely pending rows enter the cohort.

        A review-status row (conflict/ambiguous/admission_not_found/...)
        with a valid ``alta_em`` and a unique closed anchor must never be
        planned as a mirror item — apply would otherwise silently convert
        manual-review evidence into a reconciled provenance event.
        """
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("MX-CF")
        _make_admission(
            patient, "MX-CF-ADM", "2026-05-01T08:00:00", "2026-06-10T10:00:00"
        )
        record = _make_discharge(
            "MX-CF",
            saida=None,
            alta="2026-06-01T09:00:00",
            internacao="01/05/2026",
        )
        record.reconciliation_status = RECONCILIATION_STATUS_CONFLICT
        record.save(update_fields=["reconciliation_status"])

        plan = build_backfill_plan()

        assert plan.mirror_exits.total == 0
        assert _plan_mirror_ids(plan) == []
        # No mirror manual-review reason appears for the record either: the
        # review status simply keeps it out of the mirror cohort entirely.
        assert "mirror" not in " ".join(plan.manual_review)

    def test_exact_eligible_record_never_becomes_mirror(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("MX-6")
        # Open same-local-date anchor that the exact cohort claims...
        _make_admission(patient, "MX-6-OPEN", "2026-06-20T08:00:00")
        # ...plus an older closed admission whose period contains the
        # record's alta_em (the double-claim hazard the exclusion blocks).
        _make_admission(
            patient, "MX-6-CLOSED", "2026-05-01T08:00:00", "2026-05-15T10:00:00"
        )
        record = _make_discharge(
            "MX-6",
            saida="2026-06-25T10:00:00",
            alta="2026-05-10T09:00:00",
            internacao="20/06/2026",
        )

        plan = build_backfill_plan()

        discharge_ids = [
            item.payload.record_id
            for item in plan.discharges.items
        ]
        assert record.pk in discharge_ids
        assert plan.mirror_exits.total == 0
        # The same record_id never sits in both cohorts of one plan.
        assert set(discharge_ids).isdisjoint(set(_plan_mirror_ids(plan)))

    def test_plan_order_duplicates_discharges_mirror_deaths(self):
        from apps.patients.backfill import build_backfill_plan

        # Duplicates: one open/closed source-confirmed pair.
        pair_patient = _make_patient("MX-ORD-PAIR")
        _make_admission(pair_patient, "MX-ORD-PAIR-OPEN", "2026-05-01T08:00:00")
        _make_admission(
            pair_patient,
            "MX-ORD-PAIR-CLOSED",
            "2026-05-01T09:00:00",
            "2026-05-03T10:00:00",
        )
        # Exact discharge: open same-day anchor.
        exact_patient = _make_patient("MX-ORD-EXACT")
        _make_admission(exact_patient, "MX-ORD-EXACT-ADM", "2026-05-20T08:00:00")
        _make_discharge(
            "MX-ORD-EXACT",
            saida="2026-06-01T12:00:00",
            alta=None,
            internacao="20/05/2026",
        )
        # Mirror exit: closed anchor containing alta_em.
        _make_mirror_evidence(
            "MX-ORD-MIRROR",
            anchor_key="MX-ORD-MIRROR-ADM",
            anchor_start="2026-05-20T08:00:00",
            anchor_end="2026-06-05T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        # Death: open anchor plus complete obito datetime.
        death_patient = _make_patient("MX-ORD-OBITO")
        _make_admission(death_patient, "MX-ORD-OBITO-ADM", "2026-05-22T08:00:00")
        DeathRecord.objects.create(
            date=date(2026, 6, 1),
            prontuario="MX-ORD-OBITO",
            data_obito="30/05/2026 14:00",
            nome="PACIENTE SIGILOSO MX-ORD-OBITO",
        )

        plan = build_backfill_plan()

        assert [item.cohort for item in plan.items] == [
            "duplicates",
            "discharges",
            "mirror_exits",
            "deaths",
        ]

    def test_limit_truncates_mirror_cohort(self):
        from apps.patients.backfill import build_backfill_plan

        for index in range(3):
            _make_mirror_evidence(
                f"MX-LM-{index}",
                anchor_key=f"MX-LM-{index}-ADM",
                anchor_start="2026-05-01T08:00:00",
                anchor_end="2026-06-10T10:00:00",
                alta="2026-06-01T09:00:00",
            )

        plan = build_backfill_plan(limit=2)

        assert plan.mirror_exits.total == 3
        assert len(plan.mirror_exits.items) == 2
        assert plan.mirror_exits.truncated is True
        assert len(plan.items) == 2


# ---------------------------------------------------------------------------
# Command dry-run (R7) and mirror apply/rollback guard semantics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMirrorExitCommandAndApplyGuard:
    def test_dry_run_prints_mirror_cohort_line(self):
        from apps.patients.backfill import build_backfill_plan

        _make_mirror_evidence(
            "MX-DR-1",
            anchor_key="MX-DR-1-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan()
        assert plan.mirror_exits.total == 1

        out = StringIO()
        call_command("reconcile_admission_history", stdout=out)
        output = out.getvalue()

        assert "cohort=mirror_exits eligible=1 bounded=1" in output
        assert "Nothing was mutated" in output
        assert "PACIENTE SIGILOSO" not in output
        assert "MX-DR-1" not in output


# ---------------------------------------------------------------------------
# Mirror apply/rollback (SLICE-BME-S2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMirrorExitApply:
    """R1/R2: apply emits the provenance event and closes the evidence."""

    def test_apply_emits_mirror_event_and_marks_evidence(self):
        from apps.patients.backfill import apply_backfill_plan, build_backfill_plan

        _, anchor, record = _make_mirror_evidence(
            "MX-S2A-1",
            anchor_key="MX-S2A-1-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan(limit=10)
        assert _plan_mirror_ids(plan) == [record.pk]

        result = apply_backfill_plan(plan=plan)

        assert result.items == 1
        assert result.applied["mirror_exits"] == 1
        events = ReconciliationEvent.objects.filter(
            source_id=record.pk,
        )
        assert events.count() == 1
        event = events.get()
        assert event.source_kind == "discharge_record"
        assert event.status == RECONCILIATION_STATUS_RECONCILED
        assert event.exit_type == EXIT_HOSPITAL_DISCHARGE
        assert event.reason_code == "mirror_exit"
        assert event.admission_id == anchor.pk
        # Provenance, not change: prior and new equal the mirrored value.
        assert event.prior_discharge_date == anchor.discharge_date
        assert event.new_discharge_date == anchor.discharge_date
        assert event.details_json["backfill"]["batch_uuid"] == str(
            result.batch_uuid
        )
        assert event.details_json["backfill"]["item_order"] == 1

        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        assert record.reconciled_at is not None
        assert record.admission_id == anchor.pk

    def test_apply_leaves_admission_untouched(self):
        from apps.patients.backfill import apply_backfill_plan, build_backfill_plan

        _, anchor, record = _make_mirror_evidence(
            "MX-S2A-2",
            anchor_key="MX-S2A-2-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan(limit=10)

        anchor.refresh_from_db()
        before = _admission_snapshot(anchor)
        apply_backfill_plan(plan=plan)
        anchor.refresh_from_db()

        # Byte-for-byte: no Admission column changed, discharge_date included.
        assert _admission_snapshot(anchor) == before
        assert anchor.discharge_date == _dt("2026-06-10T10:00:00")

    def test_replan_after_apply_has_no_mirror_item(self):
        from apps.patients.backfill import (
            BackfillItemFailed,
            apply_backfill_plan,
            build_backfill_plan,
        )

        _, anchor, record = _make_mirror_evidence(
            "MX-S2A-3",
            anchor_key="MX-S2A-3-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan(limit=10)
        apply_backfill_plan(plan=plan)

        # R3: the evidence is no longer pending, so replanning does not
        # re-claim it (idempotent cohort, no duplicated provenance event).
        replanned = build_backfill_plan()
        assert replanned.mirror_exits.total == 0
        assert _plan_mirror_ids(replanned) == []

        # A stale plan re-applied after apply fails loudly with zero writes.
        with pytest.raises(BackfillItemFailed):
            apply_backfill_plan(plan=plan)
        assert ReconciliationEvent.objects.count() == 1
        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED


@pytest.mark.django_db
class TestMirrorExitRollback:
    """R4/R5: rollback restores the evidence inside the same transaction."""

    def _apply_one(self, key: str):
        from apps.patients.backfill import apply_backfill_plan, build_backfill_plan

        _, anchor, record = _make_mirror_evidence(
            key,
            anchor_key=f"{key}-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan(limit=10)
        result = apply_backfill_plan(plan=plan)
        assert result.applied["mirror_exits"] == 1
        return anchor, record, result

    def test_batch_rollback_restores_pending(self):
        from apps.patients.backfill import rollback_backfill_batch

        anchor, record, result = self._apply_one("MX-S2R-1")
        original = ReconciliationEvent.objects.get(source_id=record.pk)
        mirrored_discharge = anchor.discharge_date

        rollback_backfill_batch(batch_uuid=result.batch_uuid)

        # Evidence back to its prior state inside the same transaction.
        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert record.reconciled_at is None
        assert record.admission_id is None

        # The Admission stays exactly as the mirror left it: nothing to undo.
        anchor.refresh_from_db()
        assert anchor.discharge_date == mirrored_discharge

        # Documented asymmetry (design D5): reverse_reconciliation copied the
        # exit_type, so the latest reconciled event for the admission is still
        # hospital_discharge and the exit remains counted in the canonical
        # series — the rollback undoes the evidence provenance, not the mirror.
        assert ReconciliationEvent.objects.count() == 2
        inverse = ReconciliationEvent.objects.exclude(pk=original.pk).get()
        assert inverse.status == RECONCILIATION_STATUS_RECONCILED
        assert inverse.exit_type == EXIT_HOSPITAL_DISCHARGE
        assert inverse.reason_code == "rollback"
        assert inverse.details_json["rollback_of"] == str(original.operation_uuid)
        assert inverse.new_discharge_date == mirrored_discharge
        latest = (
            ReconciliationEvent.objects.filter(admission_id=anchor.pk)
            .order_by("-created_at", "-pk")
            .first()
        )
        assert latest is not None
        assert latest.status == RECONCILIATION_STATUS_RECONCILED
        assert latest.exit_type == EXIT_HOSPITAL_DISCHARGE

    def test_single_operation_rollback_restores_pending(self):
        from apps.patients.backfill import rollback_single_operation

        anchor, record, result = self._apply_one("MX-S2R-2")
        original = ReconciliationEvent.objects.get(source_id=record.pk)
        mirrored_discharge = anchor.discharge_date

        rollback_single_operation(operation_uuid=original.operation_uuid)

        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert record.reconciled_at is None
        assert record.admission_id is None
        anchor.refresh_from_db()
        assert anchor.discharge_date == mirrored_discharge
        # Same contract as the batch rollback: one inverse provenance event
        # whose exit_type keeps the admission counted in the canonical series.
        inverse = ReconciliationEvent.objects.exclude(pk=original.pk).get()
        assert inverse.status == RECONCILIATION_STATUS_RECONCILED
        assert inverse.exit_type == EXIT_HOSPITAL_DISCHARGE
        assert inverse.details_json["rollback_of"] == str(original.operation_uuid)

    def test_single_operation_rollback_conflict_writes_nothing(self):
        """P1-1 regression: event branch is one atomic transaction.

        When the evidence no longer exists, the restore raises
        ``BackfillRollbackConflict`` and the just-emitted inverse event must
        be rolled back with it — a failure must never leave a committed
        half-rollback (inverse event without the evidence restore).
        """
        from apps.patients.backfill import (
            BackfillRollbackConflict,
            rollback_single_operation,
        )

        anchor, record, result = self._apply_one("MX-S2R-3")
        original = ReconciliationEvent.objects.get(source_id=record.pk)
        events_before = ReconciliationEvent.objects.count()
        mirrored_discharge = anchor.discharge_date
        record.delete()

        with pytest.raises(BackfillRollbackConflict):
            rollback_single_operation(operation_uuid=original.operation_uuid)

        # Atomicity proof: zero writes — no inverse event survived.
        assert ReconciliationEvent.objects.count() == events_before
        # The Admission was never touched by the aborted rollback either.
        anchor.refresh_from_db()
        assert anchor.discharge_date == mirrored_discharge


@pytest.mark.django_db
class TestMirrorExitApplyOutput:
    """R6: apply output is aggregate-only and names the mirror cohort."""

    def test_apply_prints_mirror_cohort_line(self):
        from apps.patients.backfill import build_backfill_plan

        _make_mirror_evidence(
            "MX-S2O-1",
            anchor_key="MX-S2O-1-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan()
        assert plan.mirror_exits.total == 1

        out = StringIO()
        call_command(
            "reconcile_admission_history",
            "--apply", "--limit", "10", "--label", "slice-canary",
            "--backup-ref", "bkp-001", stdout=out,
        )
        output = out.getvalue()

        assert "applied cohort=mirror_exits count=1" in output
        assert "applied batch_uuid=" in output

    def test_apply_output_is_aggregate_only(self):
        _make_mirror_evidence(
            "MX-S2O-2",
            anchor_key="MX-S2O-2-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )

        out = StringIO()
        call_command(
            "reconcile_admission_history",
            "--apply", "--limit", "10", "--label", "slice-canary",
            "--backup-ref", "bkp-001", stdout=out,
        )
        output = out.getvalue()

        assert "cohort=mirror_exits" in output
        assert "PACIENTE SIGILOSO" not in output
        assert "MX-S2O-2" not in output
        assert "MX-S2O-2-ADM" not in output
