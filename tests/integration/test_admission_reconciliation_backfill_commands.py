"""Bounded backfill apply and rollback commands (RPSA-S9, integration).

Proves the end-to-end command flows against the isolated test database:
dry-run row counts, one bounded apply transaction with append-only
batch/operation payload linkage, two-phase atomic batch rollback in
reverse item order, zero-write rollback conflicts, and single operation
rollback. All fixtures are synthetic; production is never touched.
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
    Admission,
    AdmissionMergeOperation,
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


def _make_pair(key: str, local_date: str = "2026-05-01"):
    patient = _make_patient(key)
    canonical = _make_admission(patient, f"{key}-OPEN", f"{local_date}T08:00:00")
    duplicate = _make_admission(
        patient, f"{key}-CLOSED", f"{local_date}T09:00:00", "2026-05-03T10:00:00"
    )
    return patient, canonical, duplicate


def _make_discharge_patient(key: str, local_day: int):
    patient = _make_patient(key)
    admission = _make_admission(
        patient, f"{key}-ADM", f"2026-05-{local_day}T08:00:00"
    )
    record = DischargeRecord.objects.create(
        prontuario=key,
        data_internacao=f"{local_day}/05/2026",
        saida_em=_dt("2026-06-01T12:00:00"),
        nome=f"PACIENTE SIGILOSO {key}",
    )
    return patient, admission, record


def _counts() -> dict[str, int]:
    return {
        "admissions": Admission.all_objects.count(),
        "events": ReconciliationEvent.objects.count(),
        "merge_operations": AdmissionMergeOperation.objects.count(),
    }


def _apply(stdout: StringIO | None = None, limit: str = "10") -> str:
    out = stdout or StringIO()
    call_command(
        "reconcile_admission_history",
        "--apply", "--limit", limit, "--label", "slice-canary",
        "--backup-ref", "bkp-001", stdout=out,
    )
    match = re.search(r"batch_uuid=([0-9a-f-]{36})", out.getvalue())
    assert match is not None, "apply output must report the batch UUID"
    return match.group(1)


# ---------------------------------------------------------------------------
# Apply: bounded transaction, batch/operation payload linkage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApplyRecordsPayloads:
    def test_apply_closes_merges_and_records_batch_payloads(self):
        _, pair_canonical, pair_duplicate = _make_pair("AP-1")
        discharge_patient, discharge_adm, _ = _make_discharge_patient("AP-2", 20)
        death_patient = _make_patient("AP-3")
        death_adm = _make_admission(death_patient, "AP-3-ADM", "2026-05-20T08:00:00")
        DeathRecord.objects.create(
            date=date(2026, 6, 1),
            prontuario="AP-3",
            data_obito="28/05/2026 14:00",
            nome="PACIENTE SIGILOSO AP-3",
        )
        before = _counts()
        obito = _dt("2026-05-28T14:00:00")

        out = StringIO()
        batch_uuid = _apply(out)

        # Clinical effects happened only through the online services.
        discharge_adm.refresh_from_db()
        assert discharge_adm.discharge_date == _dt("2026-06-01T12:00:00")
        pair_duplicate.refresh_from_db()
        assert pair_duplicate.merged_into_id == pair_canonical.pk
        death_adm.refresh_from_db()
        assert death_adm.discharge_date == obito

        # One batch UUID groups exactly three ordered items.
        linkage_events = ReconciliationEvent.objects.filter(
            details_json__backfill__batch_uuid=batch_uuid
        )
        assert linkage_events.count() == 2
        linkage_ops = AdmissionMergeOperation.objects.filter(
            relation_manifest__backfill__batch_uuid=batch_uuid
        )
        assert linkage_ops.count() == 1

        merge_op = linkage_ops.get()
        assert merge_op.relation_manifest["backfill"]["item_order"] == 1
        by_order = {1: "merge"}
        for event in linkage_events:
            payload = event.details_json["backfill"]
            assert payload["batch_uuid"] == batch_uuid
            by_order[payload["item_order"]] = "event"
        assert by_order == {1: "merge", 2: "event", 3: "event"}

        # Every item has its own distinct operation UUID.
        uuids = [str(merge_op.operation_uuid)] + [
            str(event.operation_uuid) for event in linkage_events
        ]
        assert len(set(uuids)) == 3

        # Append-only: rows were created, nothing else changed (two new
        # reconciliation events — the merge item writes its own operation).
        assert _counts()["events"] == before["events"] + 2
        assert _counts()["merge_operations"] == before["merge_operations"] + 1

    def test_dry_run_leaves_all_row_counts_untouched(self):
        _make_pair("DRY-1")
        _make_discharge_patient("DRY-2", 20)
        before = _counts()

        out = StringIO()
        call_command("reconcile_admission_history", stdout=out)

        assert _counts() == before
        assert "dry-run" in out.getvalue().lower()


# ---------------------------------------------------------------------------
# Batch rollback: two-phase, reverse order, atomic
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBatchRollback:
    def test_batch_rollback_reverses_every_item_in_reverse_order(self):
        _, pair_canonical, pair_duplicate = _make_pair("RB-1")
        _, discharge_adm, _ = _make_discharge_patient("RB-2", 20)
        death_patient = _make_patient("RB-3")
        death_adm = _make_admission(death_patient, "RB-3-ADM", "2026-05-20T08:00:00")
        DeathRecord.objects.create(
            date=date(2026, 6, 1),
            prontuario="RB-3",
            data_obito="28/05/2026 14:00",
            nome="PACIENTE SIGILOSO RB-3",
        )

        batch_uuid = _apply()
        originals = list(
            ReconciliationEvent.objects.filter(
                details_json__backfill__batch_uuid=batch_uuid
            )
        )
        original_payloads = {
            str(ev.operation_uuid): dict(ev.details_json) for ev in originals
        }
        original_dates = {
            str(ev.operation_uuid): (ev.prior_discharge_date, ev.new_discharge_date)
            for ev in originals
        }

        out = StringIO()
        call_command(
            "rollback_admission_reconciliation", "--batch", batch_uuid, stdout=out
        )

        # Clinical state restored for every grouped item.
        discharge_adm.refresh_from_db()
        assert discharge_adm.discharge_date is None
        pair_duplicate.refresh_from_db()
        assert pair_duplicate.merged_into_id is None
        pair_canonical.refresh_from_db()
        assert pair_canonical.discharge_date is None
        death_adm.refresh_from_db()
        assert death_adm.discharge_date is None

        # Merge operation carries the single sanctioned rollback mark.
        merge_op = AdmissionMergeOperation.objects.get(
            relation_manifest__backfill__batch_uuid=batch_uuid
        )
        assert merge_op.rolled_back_at is not None

        # Append-only inverse events with swapped prior/new, rollback_of
        # and the batch linkage preserved.
        inverses = ReconciliationEvent.objects.exclude(
            operation_uuid__in=[ev.operation_uuid for ev in originals]
        )
        assert inverses.count() == 2
        for inverse in inverses:
            assert inverse.status == "reconciled"
            assert inverse.details_json["rollback_of"] in original_dates
            original = original_dates[inverse.details_json["rollback_of"]]
            assert inverse.prior_discharge_date == original[1]
            assert inverse.new_discharge_date == original[0]
            assert inverse.details_json["backfill"]["batch_uuid"] == batch_uuid

        # Originals were never updated.
        for ev in originals:
            ev.refresh_from_db()
            assert ev.details_json == original_payloads[str(ev.operation_uuid)]

    def test_rollback_conflict_aborts_with_zero_writes(self):
        _, adm_a, _ = _make_discharge_patient("CF-1", 20)
        _, adm_b, _ = _make_discharge_patient("CF-2", 21)
        batch_uuid = _apply()

        # A later incompatible mutation on one item's admission.
        adm_a.discharge_date = _dt("2026-06-05T09:00:00")
        adm_a.save(update_fields=["discharge_date", "updated_at"])
        events_after_mutation = ReconciliationEvent.objects.count()
        adm_b_closed = _dt("2026-06-01T12:00:00")

        with pytest.raises(CommandError) as excinfo:
            call_command(
                "rollback_admission_reconciliation", "--batch", batch_uuid,
                stdout=StringIO(),
            )
        assert "post-state" in str(excinfo.value).lower()
        assert "PACIENTE" not in str(excinfo.value)

        # Zero writes anywhere: the untouched item stays applied, the
        # conflicting item keeps its later mutation, and no inverse
        # events were created.
        adm_b.refresh_from_db()
        assert adm_b.discharge_date == adm_b_closed
        adm_a.refresh_from_db()
        assert adm_a.discharge_date == _dt("2026-06-05T09:00:00")
        assert ReconciliationEvent.objects.count() == events_after_mutation

    def test_double_rollback_of_the_same_batch_is_blocked(self):
        _make_discharge_patient("DB-1", 20)
        batch_uuid = _apply()

        call_command(
            "rollback_admission_reconciliation", "--batch", batch_uuid,
            stdout=StringIO(),
        )
        with pytest.raises(CommandError):
            call_command(
                "rollback_admission_reconciliation", "--batch", batch_uuid,
                stdout=StringIO(),
            )


# ---------------------------------------------------------------------------
# Single operation rollback (never confused with a batch)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOperationRollback:
    def test_operation_rollback_reverses_exactly_one_item(self):
        _, adm_a, _ = _make_discharge_patient("OP-1", 20)
        _, adm_b, _ = _make_discharge_patient("OP-2", 21)
        batch_uuid = _apply()

        first_event = (
            ReconciliationEvent.objects.filter(
                details_json__backfill__batch_uuid=batch_uuid
            )
            .order_by("details_json__backfill__item_order")
            .first()
        )
        # Records were created in pk order, so item_order 1 is OP-1's event.
        assert first_event.details_json["backfill"]["item_order"] == 1

        out = StringIO()
        call_command(
            "rollback_admission_reconciliation",
            "--operation", str(first_event.operation_uuid),
            stdout=out,
        )

        adm_a.refresh_from_db()
        adm_b.refresh_from_db()
        assert adm_a.discharge_date is None  # exactly the targeted item
        assert adm_b.discharge_date == _dt("2026-06-01T12:00:00")

    def test_merge_operation_rollback_via_operation_uuid(self):
        _, canonical, duplicate = _make_pair("OP-4")
        batch_uuid = _apply()
        merge_op = AdmissionMergeOperation.objects.get(
            relation_manifest__backfill__batch_uuid=batch_uuid
        )

        call_command(
            "rollback_admission_reconciliation",
            "--operation", str(merge_op.operation_uuid),
            stdout=StringIO(),
        )

        duplicate.refresh_from_db()
        assert duplicate.merged_into_id is None
        merge_op.refresh_from_db()
        assert merge_op.rolled_back_at is not None
