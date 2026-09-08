"""Mirror-exit backfill cohort planning (BME-S1).

Covers the ``mirror_exits`` cohort of the dry-run planner: pending
``DischargeRecord`` evidence whose unique closed canonical admission
mirrors the exit (``admission_date <= alta_em <= discharge_date``), the
explicit manual-review reasons (``discharges:mirror_ambiguous`` /
``discharges:mirror_patient_not_found``), the plan order, the ``--limit``
bound, the command dry-run line and the not-yet-supported apply guard.

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
    RECONCILIATION_STATUS_PENDING,
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
# Command dry-run (R7) and the not-yet-supported apply guard (R8)
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

    def test_mirror_payload_apply_raises_not_supported(self):
        from apps.patients.backfill import (
            BackfillItemFailed,
            build_backfill_plan,
        )

        _, _, record = _make_mirror_evidence(
            "MX-AP-1",
            anchor_key="MX-AP-1-ADM",
            anchor_start="2026-05-01T08:00:00",
            anchor_end="2026-06-10T10:00:00",
            alta="2026-06-01T09:00:00",
        )
        plan = build_backfill_plan(limit=10)
        assert [item.cohort for item in plan.items] == ["mirror_exits"]

        from apps.patients.backfill import apply_backfill_plan

        with pytest.raises(BackfillItemFailed) as excinfo:
            apply_backfill_plan(plan=plan)

        message = str(excinfo.value)
        assert "mirror" in message.lower()
        assert "not supported" in message

        # The guard aborted the whole batch with zero writes.
        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert ReconciliationEvent.objects.count() == 0
