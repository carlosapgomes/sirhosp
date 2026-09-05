"""Bounded dry-run reconciliation backfill and rollback (RPSA-S9).

Covers the pure cohort plan (deterministic order, approved cohorts only,
manual-review aggregation), the command option discipline (dry-run
default, apply preconditions, 50/100 canary caps), the rollback command
namespaces (batch vs operation) and identity-free aggregate output.

All fixtures are synthetic; no production source is ever contacted and
the commands never run against production data.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command

from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.patients.models import (
    RECONCILIATION_STATUS_PENDING,
    Admission,
    AdmissionMergeOperation,
    Patient,
    ReconciliationEvent,
)

TZ_LOCAL = ZoneInfo("America/Bahia")

APPLY = ("--apply", "--limit", "10", "--label", "slice-canary", "--backup-ref", "bkp-001")


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


def _make_pair(
    key: str,
    *,
    local_date: str = "2026-05-01",
) -> tuple[Patient, Admission, Admission]:
    """One open/closed duplicate pair for the same patient and local date."""
    patient = _make_patient(key)
    canonical = _make_admission(patient, f"{key}-OPEN", f"{local_date}T08:00:00")
    duplicate = _make_admission(
        patient, f"{key}-CLOSED", f"{local_date}T09:00:00", "2026-05-03T10:00:00"
    )
    return patient, canonical, duplicate


def _make_discharge(
    prontuario: str,
    *,
    saida: str | None,
    internacao: str,
) -> DischargeRecord:
    return DischargeRecord.objects.create(
        prontuario=prontuario,
        data_internacao=internacao,
        saida_em=_dt(saida) if saida else None,
        nome=f"PACIENTE SIGILOSO {prontuario}",
    )


def _make_death(
    prontuario: str,
    *,
    data_obito: str,
) -> DeathRecord:
    return DeathRecord.objects.create(
        date=date(2026, 6, 1),
        prontuario=prontuario,
        data_obito=data_obito,
        nome=f"PACIENTE SIGILOSO {prontuario}",
    )


def _counts() -> dict[str, int]:
    return {
        "admissions": Admission.all_objects.count(),
        "events": ReconciliationEvent.objects.count(),
        "merge_operations": AdmissionMergeOperation.objects.count(),
        "discharge_records": DischargeRecord.objects.count(),
        "death_records": DeathRecord.objects.count(),
    }


# ---------------------------------------------------------------------------
# Plan API and cohort selection (pure planning)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBackfillPlanCohorts:
    """Cohort selection: approved cohorts only, deterministic order."""

    def test_plan_api_is_importable(self):
        from apps.patients.backfill import (  # noqa: F401
            BackfillPlan,
            build_backfill_plan,
        )

    def test_deterministic_cohort_order_and_stable_pk(self):
        from apps.patients.backfill import build_backfill_plan

        _make_pair("PAIR-B")
        patient = _make_patient("ORD-1")
        _make_admission(patient, "ORD-1-ADM", "2026-05-20T08:00:00")
        _make_discharge("ORD-1", saida="2026-06-01T12:00:00", internacao="20/05/2026")
        patient2 = _make_patient("ORD-2")
        _make_admission(patient2, "ORD-2-ADM", "2026-05-21T08:00:00")
        _make_discharge("ORD-2", saida="2026-06-01T13:00:00", internacao="21/05/2026")
        dying = _make_patient("ORD-3")
        _make_admission(dying, "ORD-3-ADM", "2026-05-22T08:00:00")
        _make_death("ORD-3", data_obito="30/05/2026 14:00")

        plan = build_backfill_plan()

        assert [item.cohort for item in plan.items] == [
            "duplicates",
            "discharges",
            "discharges",
            "deaths",
        ]
        assert [item.order for item in plan.items] == [1, 2, 3, 4]
        discharge_ids = [
            item.payload.record_id
            for item in plan.items
            if item.cohort == "discharges"
        ]
        assert discharge_ids == sorted(discharge_ids)  # stable PK order

    def test_exact_discharge_cohort_requires_same_local_date(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("DQ-1")
        _make_admission(patient, "DQ-1-ADM", "2026-05-20T08:00:00")
        exact = _make_discharge(
            "DQ-1", saida="2026-06-01T12:00:00", internacao="20/05/2026"
        )
        temporal_only = _make_discharge(
            "DQ-1", saida="2026-06-01T12:30:00", internacao="21/05/2026"
        )

        plan = build_backfill_plan()

        assert plan.discharges.total == 1
        assert plan.discharges.items[0].payload.record_id == exact.pk
        assert temporal_only.pk not in [
            item.payload.record_id for item in plan.discharges.items
        ]
        assert plan.manual_review["discharges:admission_not_found"] == 1

    def test_discharge_without_saida_em_is_review_only(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("DQ-2")
        _make_admission(patient, "DQ-2-ADM", "2026-05-20T08:00:00")
        _make_discharge("DQ-2", saida=None, internacao="20/05/2026")

        plan = build_backfill_plan()

        assert plan.discharges.total == 0
        assert plan.manual_review["discharges:missing_saida_em"] == 1

    def test_ambiguous_discharge_is_never_applied(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("DQ-3")
        _make_admission(patient, "DQ-3-A", "2026-05-20T08:00:00")
        _make_admission(patient, "DQ-3-B", "2026-05-20T15:00:00")
        _make_discharge("DQ-3", saida="2026-06-01T12:00:00", internacao="20/05/2026")

        plan = build_backfill_plan()

        assert plan.discharges.total == 0
        assert plan.manual_review["discharges:ambiguous"] == 1

    def test_complete_death_cohort_requires_unique_admission(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("OB-1")
        _make_admission(patient, "OB-1-ADM", "2026-05-20T08:00:00")
        complete = _make_death("OB-1", data_obito="28/05/2026 14:00")
        _make_death("OB-2", data_obito="28/05/2026")

        plan = build_backfill_plan()

        assert plan.deaths.total == 1
        assert plan.deaths.items[0].payload.record_id == complete.pk
        assert plan.manual_review["deaths:date_only"] == 1

    def test_ambiguous_death_is_review_only(self):
        from apps.patients.backfill import build_backfill_plan

        patient = _make_patient("OB-3")
        _make_admission(patient, "OB-3-A", "2026-05-20T08:00:00", "2026-05-30T10:00:00")
        _make_admission(patient, "OB-3-B", "2026-05-22T08:00:00", "2026-05-29T10:00:00")
        _make_death("OB-3", data_obito="28/05/2026 14:00")

        plan = build_backfill_plan()

        assert plan.deaths.total == 0
        assert plan.manual_review["deaths:ambiguous"] == 1

    def test_limit_bounds_the_merged_plan(self):
        from apps.patients.backfill import build_backfill_plan

        for index in range(3):
            local_day = 21 + index
            patient = _make_patient(f"LM-{index}")
            _make_admission(
                patient,
                f"LM-{index}-ADM",
                f"2026-05-{local_day}T08:00:00",
            )
            _make_discharge(
                f"LM-{index}",
                saida="2026-06-01T12:00:00",
                internacao=f"{local_day}/05/2026",
            )

        plan = build_backfill_plan(limit=2)

        assert plan.discharges.total == 3
        assert len(plan.discharges.items) == 2
        assert plan.discharges.truncated is True
        assert len(plan.items) == 2


# ---------------------------------------------------------------------------
# Dry-run default and apply preconditions (command)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDryRunDefaultAndApplyPreconditions:
    def test_dry_run_is_the_default_and_mutates_nothing(self):
        _make_pair("DR-1")
        patient = _make_patient("DR-2")
        _make_admission(patient, "DR-2-ADM", "2026-05-20T08:00:00")
        _make_discharge("DR-2", saida="2026-06-01T12:00:00", internacao="20/05/2026")
        before = _counts()

        out = StringIO()
        call_command("reconcile_admission_history", stdout=out)

        assert _counts() == before  # zero writes without --apply
        output = out.getvalue()
        assert "dry-run" in output.lower()
        assert "batch_uuid" not in output  # batch UUID exists on apply only

    def test_apply_without_limit_label_or_backup_ref_fails_before_mutation(self):
        _make_pair("PC-1")
        before = _counts()

        with pytest.raises(CommandError) as excinfo:
            call_command("reconcile_admission_history", "--apply", stdout=StringIO())
        assert "--limit" in str(excinfo.value)

        with pytest.raises(CommandError) as excinfo:
            call_command(
                "reconcile_admission_history", "--apply", "--limit", "10",
                stdout=StringIO(),
            )
        assert "--label" in str(excinfo.value)

        with pytest.raises(CommandError) as excinfo:
            call_command(
                "reconcile_admission_history", "--apply", "--limit", "10",
                "--label", "ops-label", stdout=StringIO(),
            )
        assert "--backup-ref" in str(excinfo.value)

        with pytest.raises(CommandError) as excinfo:
            call_command(
                "reconcile_admission_history", *APPLY[:3], "--label", "   ",
                "--backup-ref", "bkp", stdout=StringIO(),
            )
        assert "--label" in str(excinfo.value)

        with pytest.raises(CommandError) as excinfo:
            call_command(
                "reconcile_admission_history", "--apply", "--limit", "0",
                "--label", "ops-label", "--backup-ref", "bkp",
                stdout=StringIO(),
            )
        assert "--limit" in str(excinfo.value)

        assert _counts() == before  # every rejection happened pre-mutation


# ---------------------------------------------------------------------------
# Canary caps: zero prior batches -> 50; at least one prior batch -> 100
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCanaryCaps:
    def test_cap_is_50_with_zero_prior_batches(self):
        from apps.patients.backfill import current_apply_cap

        assert current_apply_cap() == 50

    def test_first_apply_rejects_limit_above_50(self):
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "reconcile_admission_history", "--apply", "--limit", "51",
                "--label", "ops-label", "--backup-ref", "bkp",
                stdout=StringIO(),
            )
        assert "50" in str(excinfo.value)

        out = StringIO()
        call_command(
            "reconcile_admission_history", "--apply", "--limit", "50",
            "--label", "ops-label", "--backup-ref", "bkp", stdout=out,
        )
        assert "applied" in out.getvalue()

    def test_cap_is_100_after_one_recorded_reconciliation_batch(self):
        from apps.patients.backfill import current_apply_cap

        ReconciliationEvent.objects.create(
            source_kind="discharge_record",
            source_id=1,
            status=RECONCILIATION_STATUS_PENDING,
            details_json={
                "backfill": {
                    "batch_uuid": "11111111-1111-1111-1111-111111111111",
                    "item_order": 1,
                }
            },
        )
        assert current_apply_cap() == 100

    def test_cap_is_100_after_one_recorded_merge_batch(self):
        from apps.patients.backfill import current_apply_cap

        AdmissionMergeOperation.objects.create(
            canonical_admission_id=1,
            merged_admission_id=2,
            patient_id=1,
            source_fingerprint="f" * 64,
            confirmed_local_date=date(2026, 5, 1),
            relation_manifest={
                "backfill": {
                    "batch_uuid": "22222222-2222-2222-2222-222222222222",
                    "item_order": 1,
                }
            },
        )
        assert current_apply_cap() == 100

    def test_later_apply_rejects_limit_above_100(self):
        ReconciliationEvent.objects.create(
            source_kind="discharge_record",
            source_id=1,
            status=RECONCILIATION_STATUS_PENDING,
            details_json={
                "backfill": {
                    "batch_uuid": "33333333-3333-3333-3333-333333333333",
                    "item_order": 1,
                }
            },
        )
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "reconcile_admission_history", "--apply", "--limit", "101",
                "--label", "ops-label", "--backup-ref", "bkp",
                stdout=StringIO(),
            )
        assert "100" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Identity-free output
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIdentityFreeOutput:
    def test_dry_run_and_apply_output_carry_no_identity(self):
        _make_pair("ID-1")
        patient = _make_patient("PRONT-BF-777")
        _make_admission(patient, "ID-2-ADM", "2026-05-20T08:00:00")
        _make_discharge(
            "PRONT-BF-777", saida="2026-06-01T12:00:00", internacao="20/05/2026"
        )

        dry_out = StringIO()
        call_command("reconcile_admission_history", stdout=dry_out)
        dry = dry_out.getvalue()
        assert "PACIENTE SIGILOSO" not in dry
        assert "PRONT-BF-777" not in dry
        assert "PRONT-REF-" not in dry

        apply_out = StringIO()
        call_command(
            "reconcile_admission_history",
            "--apply", "--limit", "10", "--label", "ops-label",
            "--backup-ref", "bkp", stdout=apply_out,
        )
        applied = apply_out.getvalue()
        assert "PACIENTE SIGILOSO" not in applied
        assert "PRONT-BF-777" not in applied
        assert "PRONT-REF-" not in applied
        assert re.search(r"batch_uuid=[0-9a-f-]{36}", applied)


# ---------------------------------------------------------------------------
# Rollback command namespaces (batch vs operation)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRollbackCommandNamespaces:
    def test_batch_and_operation_are_mutually_exclusive(self):
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "rollback_admission_reconciliation",
                "--batch", "44444444-4444-4444-4444-444444444444",
                "--operation", "55555555-5555-5555-5555-555555555555",
                stdout=StringIO(),
            )
        assert "--batch" in str(excinfo.value)
        assert "--operation" in str(excinfo.value)

    def test_rollback_requires_one_selector(self):
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "rollback_admission_reconciliation", stdout=StringIO()
            )
        assert "--batch" in str(excinfo.value)
        assert "--operation" in str(excinfo.value)

    def test_batch_selector_does_not_resolve_operation_uuids(self):
        """Batch UUIDs live only in backfill payloads — namespaces are disjoint."""
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "rollback_admission_reconciliation",
                "--batch", "66666666-6666-6666-6666-666666666666",
                stdout=StringIO(),
            )
        assert "batch" in str(excinfo.value).lower()

    def test_unknown_operation_resolves_to_nothing(self):
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "rollback_admission_reconciliation",
                "--operation", "77777777-7777-7777-7777-777777777777",
                stdout=StringIO(),
            )
        assert "operation" in str(excinfo.value).lower()

    def test_operation_uuid_present_in_both_audits_is_ambiguous(self):
        shared = "88888888-8888-8888-8888-888888888888"
        ReconciliationEvent.objects.create(
            source_kind="discharge_record",
            source_id=1,
            status=RECONCILIATION_STATUS_PENDING,
            operation_uuid=shared,
        )
        AdmissionMergeOperation.objects.create(
            canonical_admission_id=1,
            merged_admission_id=2,
            patient_id=1,
            source_fingerprint="f" * 64,
            confirmed_local_date=date(2026, 5, 1),
            operation_uuid=shared,
        )
        with pytest.raises(CommandError) as excinfo:
            call_command(
                "rollback_admission_reconciliation", "--operation", shared,
                stdout=StringIO(),
            )
        assert "ambiguous" in str(excinfo.value).lower()

    def test_rollback_output_carries_no_identity(self):
        _make_pair("RO-1")
        apply_out = StringIO()
        call_command(
            "reconcile_admission_history",
            "--apply", "--limit", "10", "--label", "ops-label",
            "--backup-ref", "bkp", stdout=apply_out,
        )
        batch_uuid = re.search(
            r"batch_uuid=([0-9a-f-]{36})", apply_out.getvalue()
        ).group(1)

        out = StringIO()
        call_command(
            "rollback_admission_reconciliation", "--batch", batch_uuid,
            stdout=out,
        )
        output = out.getvalue()
        assert "PACIENTE SIGILOSO" not in output
        assert "PRONT-" not in output
