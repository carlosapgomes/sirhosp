"""PEND-S2: exit lifecycle — confirmed exits close residual actives.

Covers R1 (the three writers close only Actives of the resultant closed
episode, including already_reconciled residuals and merge-closed without an
end in the confirmation), R2 (idempotency plus per-item snapshot atomicity),
R3 (negatives assert observable state), R4 (PostgreSQL concurrency with
separate connections and barriers) and R5 (merge paths, rollback, HTTP
history after exit).

Contract literals (design D5): system revisions carry motivo
``confirmed_exit`` with ``is_system=True``; processing time (never
backdated to the effective exit). No S2 helper is imported here on
purpose: these tests exercise the real writers end to end.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.db import connection, connections
from django.test import Client

from apps.census.models import BedStatus, CensusSnapshot
from apps.discharges.models import DischargeRecord
from apps.discharges.services import reconcile_discharge_record
from apps.ingestion.services import upsert_admission_snapshot
from apps.patients.admission_merge import (
    AdmissionSourceConfirmation,
    SourceEpisode,
    merge_admissions,
    rollback_admission_merge,
    source_confirmation_fingerprint,
)
from apps.patients.models import (
    EXIT_DEATH,
    EXIT_HOSPITAL_DISCHARGE,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    AdmissionMergeOperation,
    AdmissionSourceAlias,
    Patient,
    ReconciliationEvent,
)
from apps.patients.reconciliation import (
    EVIDENCE_SOURCE_DISCHARGE_RECORD,
    DischargeExitEvidence,
    apply_discharge_exit,
    decide_discharge_match,
    reverse_reconciliation,
)
from apps.pending_items.eligibility import IneligibleAdmissionError
from apps.pending_items.models import (
    ACTION_CREATED,
    ACTION_FINALIZED,
    GROUP_NAME,
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.services import (
    create_pending_item,
    finalize_pending_item,
    update_pending_item,
)

TZ = ZoneInfo("America/Bahia")

# Contract values from design D5 (motivo + system author label recorded on
# every exit-driven revision). Kept as literals so this module never
# imports the S2 seam it is meant to verify through the writers.
SYSTEM_CLOSE_NOTE = "confirmed_exit"
SYSTEM_AUTHOR_LABEL = "Sistema"

requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-level locking behavior requires PostgreSQL",
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str | None = "2026-06-01T08:00:00",
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt(start) if start else None,
        discharge_date=_dt(end) if end else None,
    )


def _make_census_row(
    prontuario: str,
    *,
    setor: str = "CLINICA MEDICA",
    leito: str = "L01",
    captured_at: str = "2026-06-10T08:00:00",
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=_dt(captured_at),
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome="PACIENTE SINTETICO",
        bed_status=BedStatus.OCCUPIED,
    )


def _ensure_bootstrap() -> None:
    """Recreate migration-bootstrapped rows when flushed.

    ``django_db(transaction=True)`` (the concurrency class) flushes the
    database after every transactional test, removing rows created by
    data migrations (the ``Desospitalização`` group and ``Outro`` type).
    The HTTP suite keeps proving the migration bootstrap with strict
    ``.get``; this lifecycle suite only needs the rows to exist.
    """
    from django.contrib.auth.models import Group

    Group.objects.get_or_create(name=GROUP_NAME)
    PendingItemType.objects.get_or_create(
        slug=OUTRO_SLUG, defaults={"name": "Outro"}
    )


def _outro_type() -> PendingItemType:
    """Return the Outro type, recreating it after a transactional flush."""
    _ensure_bootstrap()
    return PendingItemType.objects.get(slug=OUTRO_SLUG)


def _make_item(
    admission: Admission, author: User, description: str
) -> PendingItem:
    return create_pending_item(
        admission=admission,
        item_type=_outro_type(),
        description=description,
        author=author,
    )


def _seed_active_item(
    admission: Admission, author: User, description: str
) -> PendingItem:
    """Seed a pre-existing active item plus its v1 revision via ORM.

    Setup-only helper for fixtures the human write service rightly
    refuses (several open admissions, closed episodes, legacy data).
    """
    item_type = _outro_type()
    label = author.get_username()
    item = PendingItem.objects.create(
        admission=admission,
        item_type=item_type,
        description=description,
        status=STATUS_ACTIVE,
        version=1,
        created_by=author,
        created_by_name=label,
        updated_by=author,
        updated_by_name=label,
        is_system_updated=False,
    )
    PendingItemRevision.objects.create(
        item=item,
        version=1,
        action=ACTION_CREATED,
        item_type=item_type,
        type_name=item_type.name,
        description=description,
        status=STATUS_ACTIVE,
        note="",
        author=author,
        author_name=label,
        is_system=False,
    )
    return item


def _confirmation(
    *,
    end: str | None,
    local_day: str = "2026-05-01",
    start: str = "2026-05-01T08:00:00",
) -> AdmissionSourceConfirmation:
    return AdmissionSourceConfirmation(
        patient_record="P_S2_MERGE",
        local_admission_date=date.fromisoformat(local_day),
        captured_at=_dt("2026-05-04T09:00:00"),
        failed=False,
        episodes=(
            SourceEpisode(
                source_admission_key="ADM_S2_CLOSED",
                admission_start=_dt(start),
                admission_end=_dt(end) if end else None,
            ),
        ),
    )


def _merge(
    canonical: Admission, duplicate: Admission, end: str | None, **kwargs
) -> AdmissionMergeOperation:
    confirmation = _confirmation(end=end, **kwargs)
    result = merge_admissions(
        first=duplicate,
        second=canonical,
        confirmation=confirmation,
        expected_fingerprint=source_confirmation_fingerprint(confirmation),
    )
    return AdmissionMergeOperation.objects.get(
        operation_uuid=result.operation_uuid
    )


def _reconcile_by_key(
    patient_key: str, admission_key: str, exit_at: str
) -> str:
    """Drive the real discharge boundary keyed to one admission."""
    exit_datetime = _dt(exit_at)
    evidence = DischargeExitEvidence(
        patient_record=patient_key,
        exit_datetime=exit_datetime,
        admission_key=admission_key,
    )
    decision = decide_discharge_match(evidence=evidence)
    return apply_discharge_exit(
        decision=decision,
        exit_datetime=exit_datetime,
        exit_type=EXIT_HOSPITAL_DISCHARGE,
        source_kind=EVIDENCE_SOURCE_DISCHARGE_RECORD,
        source_id=abs(hash((patient_key, admission_key, exit_at)))
        % (2**31),
    )


def _assert_system_close(item: PendingItem, prior_version: int) -> None:
    item.refresh_from_db()
    assert item.status == STATUS_CLOSED_UNRESOLVED
    assert item.version == prior_version + 1
    assert item.finalized_at is not None
    assert item.is_system_updated is True
    assert item.updated_by_id is None
    assert item.updated_by_name == SYSTEM_AUTHOR_LABEL
    revision = PendingItemRevision.objects.get(
        item=item, version=item.version
    )
    assert revision.action == ACTION_FINALIZED
    assert revision.status == STATUS_CLOSED_UNRESOLVED
    assert revision.note == SYSTEM_CLOSE_NOTE
    assert revision.is_system is True
    assert revision.author_id is None
    assert revision.author_name == SYSTEM_AUTHOR_LABEL


@pytest.fixture
def writer(db: object) -> User:
    _ensure_bootstrap()
    user = User.objects.create_user(username="s2_writer", password="x")
    Group.objects.get(name="Desospitalização").user_set.add(user)
    return user


@pytest.fixture
def writer_client(client: Client, db: object) -> Client:
    _ensure_bootstrap()
    user = User.objects.create_user(username="s2_http", password="pw123456")
    Group.objects.get(name="Desospitalização").user_set.add(user)
    client.login(username="s2_http", password="pw123456")
    return client


@pytest.mark.django_db
class TestReconciliationClose:
    """R1/R2: discharge and death reconciliation close residual actives."""

    def test_discharge_closes_only_actives_of_the_episode(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_R1")
        admission = _make_admission(patient, "ADM_S2_R1")
        other_patient = _make_patient("P_S2_R1_OTHER")
        other = _make_admission(other_patient, "ADM_S2_R1_OTHER")
        _make_census_row("P_S2_R1")
        _make_census_row("P_S2_R1_OTHER")
        first = _make_item(admission, writer, "primeira pendencia sintetica")
        second = _make_item(admission, writer, "segunda pendencia sintetica")
        resolved = _make_item(admission, writer, "resolvida por humano")
        finalize_pending_item(
            item=resolved,
            target_status=STATUS_RESOLVED,
            note="resolucao humana",
            author=writer,
            expected_version=1,
        )
        foreign = _make_item(other, writer, "pendencia de outro episodio")

        status = _reconcile_by_key(
            "P_S2_R1", "ADM_S2_R1", "2026-06-05T10:00:00"
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == _dt("2026-06-05T10:00:00")
        _assert_system_close(first, 1)
        _assert_system_close(second, 1)
        # Processing time, never backdated to the effective exit.
        assert first.finalized_at != _dt("2026-06-05T10:00:00")
        # Human finals are preserved without a new version.
        resolved.refresh_from_db()
        assert resolved.status == STATUS_RESOLVED
        assert resolved.version == 2
        assert resolved.updated_by_id == writer.pk
        assert resolved.is_system_updated is False
        assert (
            PendingItemRevision.objects.filter(item=resolved).count() == 2
        )
        # Another episode is untouched.
        foreign.refresh_from_db()
        assert foreign.status == STATUS_ACTIVE
        assert foreign.version == 1

    def test_death_exit_closes_actives(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_DEATH")
        admission = _make_admission(patient, "ADM_S2_DEATH")
        _make_census_row("P_S2_DEATH")
        item = _make_item(admission, writer, "pendencia antes do obito")

        exit_datetime = _dt("2026-06-05T10:00:00")
        evidence = DischargeExitEvidence(
            patient_record="P_S2_DEATH",
            exit_datetime=exit_datetime,
            match_by_period=True,
        )
        decision = decide_discharge_match(evidence=evidence)
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        status = apply_discharge_exit(
            decision=decision,
            exit_datetime=exit_datetime,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=4242,
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        _assert_system_close(item, 1)

    def test_already_reconciled_with_residual_actives(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_RESID")
        admission = _make_admission(patient, "ADM_S2_RESID")
        _make_census_row("P_S2_RESID")
        item = _make_item(admission, writer, "pendencia residual sintetica")
        first = _reconcile_by_key(
            "P_S2_RESID", "ADM_S2_RESID", "2026-06-05T10:00:00"
        )
        assert first == RECONCILIATION_STATUS_RECONCILED
        # Legacy residual: an active item on an already closed episode
        # (e.g. created before the exit hooks existed). ORM setup on
        # purpose: the write service rightly refuses closed episodes.
        residual = PendingItem.objects.create(
            admission=admission,
            item_type=_outro_type(),
            description="residuo ativo legado",
            status=STATUS_ACTIVE,
            version=1,
        )
        PendingItemRevision.objects.create(
            item=residual,
            version=1,
            action=ACTION_CREATED,
            item_type=residual.item_type,
            type_name=residual.item_type.name,
            description="residuo ativo legado",
            status=STATUS_ACTIVE,
            author=writer,
            author_name=writer.get_username(),
            is_system=False,
        )

        status = _reconcile_by_key(
            "P_S2_RESID", "ADM_S2_RESID", "2026-06-05T10:00:00"
        )

        assert status == RECONCILIATION_STATUS_ALREADY_RECONCILED
        _assert_system_close(item, 1)
        _assert_system_close(residual, 1)

    def test_repeated_evidence_creates_no_new_versions(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_REP")
        admission = _make_admission(patient, "ADM_S2_REP")
        _make_census_row("P_S2_REP")
        item = _make_item(admission, writer, "pendencia idempotente")
        assert (
            _reconcile_by_key("P_S2_REP", "ADM_S2_REP", "2026-06-05T10:00:00")
            == RECONCILIATION_STATUS_RECONCILED
        )
        revisions_before = PendingItemRevision.objects.filter(
            item=item
        ).count()

        status = _reconcile_by_key(
            "P_S2_REP", "ADM_S2_REP", "2026-06-05T10:00:00"
        )

        assert status == RECONCILIATION_STATUS_ALREADY_RECONCILED
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        assert item.version == 2
        assert (
            PendingItemRevision.objects.filter(item=item).count()
            == revisions_before
        )

    def test_exit_correction_keeps_item_versions_stable(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_CORR")
        admission = _make_admission(patient, "ADM_S2_CORR")
        _make_census_row("P_S2_CORR")
        item = _make_item(admission, writer, "pendencia estavel")
        assert (
            _reconcile_by_key(
                "P_S2_CORR", "ADM_S2_CORR", "2026-06-05T10:00:00"
            )
            == RECONCILIATION_STATUS_RECONCILED
        )
        revisions_before = PendingItemRevision.objects.filter(
            item=item
        ).count()

        status = _reconcile_by_key(
            "P_S2_CORR", "ADM_S2_CORR", "2026-06-05T12:30:00"
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == _dt("2026-06-05T12:30:00")
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        assert (
            PendingItemRevision.objects.filter(item=item).count()
            == revisions_before
        )


@pytest.mark.django_db
class TestSnapshotClose:
    """R1/R2: the admissions snapshot writer closes on resultant state."""

    def test_snapshot_end_in_item_closes_actives(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_SNAP1")
        admission = _make_admission(patient, "ADM_S2_SNAP1")
        _make_census_row("P_S2_SNAP1")
        item = _make_item(admission, writer, "pendencia do snapshot")
        resolved = _make_item(admission, writer, "resolvida antes")
        finalize_pending_item(
            item=resolved,
            target_status=STATUS_RESOLVED,
            note=None,
            author=writer,
            expected_version=1,
        )

        result = upsert_admission_snapshot(
            patient,
            [
                {
                    "admission_key": "ADM_S2_SNAP1",
                    "admission_start": "2026-06-01T08:00:00",
                    "admission_end": "2026-06-05T10:00:00",
                }
            ],
        )

        assert result["ambiguous"] == 0
        admission.refresh_from_db()
        assert admission.discharge_date is not None
        _assert_system_close(item, 1)
        resolved.refresh_from_db()
        assert resolved.status == STATUS_RESOLVED
        assert resolved.version == 2
        assert (
            PendingItemRevision.objects.filter(item=resolved).count() == 2
        )

    def test_snapshot_reprocessing_closed_without_end_closes_residuals(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_SNAP2")
        admission = _make_admission(
            patient, "ADM_S2_SNAP2", end="2026-06-05T10:00:00"
        )
        residual = PendingItem.objects.create(
            admission=admission,
            item_type=_outro_type(),
            description="residuo ativo no episodio fechado",
            status=STATUS_ACTIVE,
            version=1,
        )

        result = upsert_admission_snapshot(
            patient,
            [
                {
                    "admission_key": "ADM_S2_SNAP2",
                    "admission_start": "2026-06-01T08:00:00",
                    # No admission_end: the resultant state is already
                    # closed, which alone must trigger the close.
                }
            ],
        )

        assert result["ambiguous"] == 0
        _assert_system_close(residual, 1)

    def test_snapshot_open_item_leaves_actives_alone(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_SNAP3")
        admission = _make_admission(patient, "ADM_S2_SNAP3")
        _make_census_row("P_S2_SNAP3")
        item = _make_item(admission, writer, "pendencia ainda ativa")

        upsert_admission_snapshot(
            patient,
            [
                {
                    "admission_key": "ADM_S2_SNAP3",
                    "admission_start": "2026-06-01T08:00:00",
                    "ward": "CLINICA MEDICA",
                }
            ],
        )

        item.refresh_from_db()
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert PendingItemRevision.objects.filter(item=item).count() == 1

    def test_revision_failure_on_second_of_three_items_rolls_back_only_it(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_FAIL")
        admissions = [
            _make_admission(patient, f"ADM_S2_FAIL{i}") for i in (1, 2, 3)
        ]
        # ORM seeding: three open admissions is exactly what the human
        # write service refuses, and these items predate the snapshot.
        items = [
            _seed_active_item(
                admission, writer, f"pendencia sintetica {i}"
            )
            for i, admission in enumerate(admissions, start=1)
        ]
        # A same-period duplicate pair around the failing item: the
        # consolidation step must leave every row untouched on failure.
        # (The guard already skips it because the failing admission
        # carries a pending item; the assertion pins that no partial
        # consolidation leaks through the item rollback.)
        extra_duplicate = _make_admission(
            patient, "ADM_S2_FAIL2_DUP", end="2026-06-06T10:00:00"
        )
        real_create = PendingItemRevision.objects.create
        calls = {"count": 0}

        def _flaky_create(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("falha sintetica de revisao")
            return real_create(*args, **kwargs)

        with (
            patch.object(
                PendingItemRevision.objects, "create", _flaky_create
            ),
            pytest.raises(RuntimeError, match="falha sintetica"),
        ):
            upsert_admission_snapshot(
                patient,
                [
                    {
                        "admission_key": "ADM_S2_FAIL1",
                        "admission_start": "2026-06-01T08:00:00",
                        "admission_end": "2026-06-05T10:00:00",
                    },
                    {
                        "admission_key": "ADM_S2_FAIL2",
                        "admission_start": "2026-06-01T08:00:00",
                        "admission_end": "2026-06-06T10:00:00",
                    },
                    {
                        "admission_key": "ADM_S2_FAIL3",
                        "admission_start": "2026-06-01T08:00:00",
                        "admission_end": "2026-06-07T10:00:00",
                    },
                ],
            )

        # First item: fully persisted (fields, close, revision, alias).
        admissions[0].refresh_from_db()
        assert admissions[0].discharge_date is not None
        _assert_system_close(items[0], 1)
        assert AdmissionSourceAlias.objects.filter(
            admission=admissions[0], alias_key="ADM_S2_FAIL1"
        ).exists()
        # Second item: exit, item, revision, alias and consolidation
        # are all undone together; the failure propagated.
        admissions[1].refresh_from_db()
        assert admissions[1].discharge_date is None
        items[1].refresh_from_db()
        assert items[1].status == STATUS_ACTIVE
        assert items[1].version == 1
        assert (
            PendingItemRevision.objects.filter(item=items[1]).count() == 1
        )
        assert not AdmissionSourceAlias.objects.filter(
            alias_key="ADM_S2_FAIL2"
        ).exists()
        assert Admission.objects.filter(pk=extra_duplicate.pk).exists()
        assert Admission.objects.filter(pk=admissions[1].pk).exists()
        # Third item: never processed in that call.
        admissions[2].refresh_from_db()
        assert admissions[2].discharge_date is None
        items[2].refresh_from_db()
        assert items[2].status == STATUS_ACTIVE
        assert not AdmissionSourceAlias.objects.filter(
            alias_key="ADM_S2_FAIL3"
        ).exists()
        # No reconciliation audit is invented for a snapshot writer.
        assert not ReconciliationEvent.objects.exists()

    def test_identity_merged_between_resolve_and_lock_is_not_written(
        self, db: object, writer: User
    ) -> None:
        from apps.ingestion.services import StaleSnapshotIdentity

        patient = _make_patient("P_S2_STALE")
        canonical = _make_admission(
            patient, "ADM_S2_STALE_CAN", start="2026-05-01T08:00:00"
        )
        duplicate = _make_admission(
            patient, "ADM_S2_STALE_DUP", start="2026-05-02T08:00:00"
        )
        _make_census_row("P_S2_STALE")
        import apps.ingestion.services as snapshot_services

        real_resolve = snapshot_services.resolve_admission_identity
        state = {"merged": False}

        def _resolve_then_merge(**kwargs):
            match = real_resolve(**kwargs)
            if not state["merged"]:
                state["merged"] = True
                _merge(
                    canonical,
                    duplicate,
                    None,
                    local_day="2026-05-02",
                    start="2026-05-02T08:00:00",
                )
            return match

        with (
            patch.object(
                snapshot_services,
                "resolve_admission_identity",
                _resolve_then_merge,
            ),
            pytest.raises(StaleSnapshotIdentity),
        ):
            upsert_admission_snapshot(
                patient,
                [
                    {
                        # Resolves the duplicate before the merge above.
                        "admission_key": "ADM_S2_STALE_DUP",
                        "admission_start": "2026-05-02T08:00:00",
                        "admission_end": "2026-05-06T10:00:00",
                    }
                ],
            )

        assert state["merged"] is True
        # Nothing is written through the stale object: neither the
        # merged row nor the canonical winner carries the snapshot end.
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id == canonical.pk
        assert duplicate.discharge_date is None
        canonical.refresh_from_db()
        assert canonical.discharge_date is None


@pytest.mark.django_db
class TestMergeClose:
    """R1/R5: merge closes when the resultant canonical state is closed."""

    def _pair_with_items(
        self, writer: User, tag: str, canonical_end: str | None,
        duplicate_end: str | None,
    ) -> tuple[Admission, Admission, PendingItem, PendingItem]:
        patient = _make_patient(f"P_S2_M_{tag}")
        canonical = _make_admission(
            patient,
            f"ADM_S2_M_{tag}_CAN",
            start="2026-05-01T08:00:00",
            end=canonical_end,
        )
        duplicate = _make_admission(
            patient,
            f"ADM_S2_M_{tag}_DUP",
            start="2026-05-01T09:00:00",
            end=duplicate_end,
        )
        canonical_item = _seed_active_item(
            canonical, writer, f"pendencia canonica {tag}"
        )
        duplicate_item = _seed_active_item(
            duplicate, writer, f"pendencia duplicata {tag}"
        )
        return canonical, duplicate, canonical_item, duplicate_item

    def test_merge_end_from_confirmation_closes_both_sides(
        self, db: object, writer: User
    ) -> None:
        canonical, duplicate, canonical_item, duplicate_item = (
            self._pair_with_items(writer, "CONF", None, None)
        )

        operation = _merge(canonical, duplicate, "2026-05-03T10:00:00")

        canonical.refresh_from_db()
        assert canonical.discharge_date == _dt("2026-05-03T10:00:00")
        assert operation.canonical_admission_id == canonical.pk
        duplicate_item.refresh_from_db()
        assert duplicate_item.admission_id == canonical.pk
        _assert_system_close(canonical_item, 1)
        _assert_system_close(duplicate_item, 1)

    def test_merge_canonical_already_closed_without_end_in_confirmation(
        self, db: object, writer: User
    ) -> None:
        canonical, duplicate, canonical_item, duplicate_item = (
            self._pair_with_items(
                writer, "PREC", "2026-05-03T10:00:00", None
            )
        )

        _merge(canonical, duplicate, None)

        canonical.refresh_from_db()
        assert canonical.discharge_date == _dt("2026-05-03T10:00:00")
        duplicate_item.refresh_from_db()
        assert duplicate_item.admission_id == canonical.pk
        _assert_system_close(canonical_item, 1)
        _assert_system_close(duplicate_item, 1)

    def test_merge_end_inherited_from_duplicate_without_end_in_confirmation(
        self, db: object, writer: User
    ) -> None:
        canonical, duplicate, canonical_item, duplicate_item = (
            self._pair_with_items(
                writer, "DUPL", None, "2026-05-03T10:00:00"
            )
        )

        _merge(canonical, duplicate, None)

        canonical.refresh_from_db()
        assert canonical.discharge_date == _dt("2026-05-03T10:00:00")
        _assert_system_close(canonical_item, 1)
        _assert_system_close(duplicate_item, 1)

    def test_merge_open_pair_closes_nothing(
        self, db: object, writer: User
    ) -> None:
        canonical, duplicate, canonical_item, duplicate_item = (
            self._pair_with_items(writer, "OPEN", None, None)
        )

        _merge(canonical, duplicate, None)

        canonical.refresh_from_db()
        assert canonical.discharge_date is None
        canonical_item.refresh_from_db()
        duplicate_item.refresh_from_db()
        assert canonical_item.status == STATUS_ACTIVE
        assert duplicate_item.status == STATUS_ACTIVE
        assert duplicate_item.admission_id == canonical.pk
        assert PendingItemRevision.objects.filter(
            item=canonical_item
        ).count() == 1
        assert PendingItemRevision.objects.filter(
            item=duplicate_item
        ).count() == 1

    def test_merge_preserves_human_finals(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_M_HUM")
        canonical = _make_admission(
            patient, "ADM_S2_M_HUM_CAN", start="2026-05-01T08:00:00"
        )
        duplicate = _make_admission(
            patient, "ADM_S2_M_HUM_DUP", start="2026-05-01T09:00:00"
        )
        resolved = _seed_active_item(
            duplicate, writer, "resolvida na duplicata"
        )
        resolved.status = STATUS_RESOLVED
        resolved.finalized_at = _dt("2026-05-02T10:00:00")
        resolved.version = 2
        resolved.save(
            update_fields=["status", "finalized_at", "version", "updated_at"]
        )
        PendingItemRevision.objects.create(
            item=resolved,
            version=2,
            action="finalized",
            item_type=resolved.item_type,
            type_name=resolved.item_type.name,
            description=resolved.description,
            status=STATUS_RESOLVED,
            note="resolucao humana",
            author=writer,
            author_name=writer.get_username(),
            is_system=False,
        )

        _merge(canonical, duplicate, "2026-05-03T10:00:00")

        resolved.refresh_from_db()
        assert resolved.status == STATUS_RESOLVED
        assert resolved.version == 2
        assert resolved.admission_id == canonical.pk
        assert (
            PendingItemRevision.objects.filter(item=resolved).count() == 2
        )


@pytest.mark.django_db
class TestNegatives:
    """R3: absence, medical-only discharge and ambiguity never close."""

    def test_absent_census_blocks_writes_without_closing(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_NEG1")
        admission = _make_admission(patient, "ADM_S2_NEG1")
        _make_census_row("P_S2_NEG1")
        item = _make_item(admission, writer, "pendencia sem censo depois")
        CensusSnapshot.objects.all().delete()

        with pytest.raises(IneligibleAdmissionError):
            create_pending_item(
                admission=admission,
                item_type=_outro_type(),
                description="bloqueada sem censo",
                author=writer,
            )

        item.refresh_from_db()
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert PendingItemRevision.objects.filter(item=item).count() == 1

    def test_medical_discharge_without_exit_does_not_close(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_NEG2")
        admission = _make_admission(patient, "ADM_S2_NEG2")
        _make_census_row("P_S2_NEG2")
        item = _make_item(admission, writer, "pendencia com alta sem saida")
        record = DischargeRecord.objects.create(
            prontuario="P_S2_NEG2",
            nome="PACIENTE SINTETICO",
            data_internacao="01/06/2026",
            alta_em=_dt("2026-06-04T10:00:00"),
            saida_em=None,
        )

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_PENDING
        admission.refresh_from_db()
        assert admission.discharge_date is None
        item.refresh_from_db()
        assert item.status == STATUS_ACTIVE
        assert PendingItemRevision.objects.filter(item=item).count() == 1
        assert not ReconciliationEvent.objects.exists()

    def test_ambiguous_evidence_does_not_close(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_NEG3")
        first = _make_admission(
            patient, "ADM_S2_NEG3_A", start="2026-06-01T08:00:00"
        )
        second = _make_admission(
            patient, "ADM_S2_NEG3_B", start="2026-06-01T14:00:00"
        )
        first_item = _seed_active_item(
            first, writer, "pendencia do primeiro candidato"
        )
        second_item = _seed_active_item(
            second, writer, "pendencia do segundo candidato"
        )
        record = DischargeRecord.objects.create(
            prontuario="P_S2_NEG3",
            nome="PACIENTE SINTETICO",
            data_internacao="01/06/2026",
            alta_em=_dt("2026-06-04T10:00:00"),
            saida_em=_dt("2026-06-05T10:00:00"),
        )

        status = reconcile_discharge_record(record=record)

        assert status == RECONCILIATION_STATUS_AMBIGUOUS
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.discharge_date is None
        assert second.discharge_date is None
        first_item.refresh_from_db()
        second_item.refresh_from_db()
        assert first_item.status == STATUS_ACTIVE
        assert second_item.status == STATUS_ACTIVE
        assert PendingItemRevision.objects.filter(
            item=first_item
        ).count() == 1
        assert PendingItemRevision.objects.filter(
            item=second_item
        ).count() == 1

    def test_conflicting_evidence_does_not_close(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_NEG4")
        keyed = _make_admission(
            patient, "ADM_S2_NEG4_KEY", start="2026-06-01T08:00:00"
        )
        other = _make_admission(
            patient, "ADM_S2_NEG4_OTH", start="2026-06-03T08:00:00"
        )
        keyed_item = _seed_active_item(
            keyed, writer, "pendencia do episodio chaveado"
        )
        other_item = _seed_active_item(
            other, writer, "pendencia do outro episodio"
        )
        exit_datetime = _dt("2026-06-05T10:00:00")
        evidence = DischargeExitEvidence(
            patient_record="P_S2_NEG4",
            exit_datetime=exit_datetime,
            admission_key="ADM_S2_NEG4_KEY",
            admission_start=_dt("2026-06-03T08:00:00"),
        )
        decision = decide_discharge_match(evidence=evidence)
        assert decision.status == RECONCILIATION_STATUS_CONFLICT

        status = apply_discharge_exit(
            decision=decision,
            exit_datetime=exit_datetime,
            exit_type=EXIT_HOSPITAL_DISCHARGE,
            source_kind=EVIDENCE_SOURCE_DISCHARGE_RECORD,
            source_id=777001,
        )

        assert status == RECONCILIATION_STATUS_CONFLICT
        keyed.refresh_from_db()
        other.refresh_from_db()
        assert keyed.discharge_date is None
        assert other.discharge_date is None
        keyed_item.refresh_from_db()
        other_item.refresh_from_db()
        assert keyed_item.status == STATUS_ACTIVE
        assert other_item.status == STATUS_ACTIVE
        assert PendingItemRevision.objects.filter(
            item=keyed_item
        ).count() == 1
        assert PendingItemRevision.objects.filter(
            item=other_item
        ).count() == 1


@pytest.mark.django_db
class TestRollbackPreservesHistory:
    """R5: structural rollbacks never delete revisions nor reopen finals."""

    def test_reconciliation_rollback_keeps_system_close(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_RB1")
        admission = _make_admission(patient, "ADM_S2_RB1")
        _make_census_row("P_S2_RB1")
        item = _make_item(admission, writer, "pendencia fechada e revertida")
        assert (
            _reconcile_by_key("P_S2_RB1", "ADM_S2_RB1", "2026-06-05T10:00:00")
            == RECONCILIATION_STATUS_RECONCILED
        )
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        event = ReconciliationEvent.objects.get(
            status=RECONCILIATION_STATUS_RECONCILED,
            admission=admission,
            new_discharge_date=_dt("2026-06-05T10:00:00"),
        )

        reverse_reconciliation(event=event)

        admission.refresh_from_db()
        assert admission.discharge_date is None
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        assert item.version == 2
        assert PendingItemRevision.objects.filter(item=item).count() == 2

    def test_merge_rollback_keeps_versions_and_finals(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_RB2")
        canonical = _make_admission(
            patient, "ADM_S2_RB2_CAN", start="2026-05-01T08:00:00"
        )
        duplicate = _make_admission(
            patient, "ADM_S2_RB2_DUP", start="2026-05-01T09:00:00"
        )
        canonical_item = _seed_active_item(
            canonical, writer, "pendencia canonica revertida"
        )
        duplicate_item = _seed_active_item(
            duplicate, writer, "pendencia duplicata revertida"
        )
        operation = _merge(canonical, duplicate, "2026-05-03T10:00:00")
        duplicate_item.refresh_from_db()
        assert duplicate_item.admission_id == canonical.pk
        assert duplicate_item.status == STATUS_CLOSED_UNRESOLVED

        rollback_admission_merge(operation=operation)

        canonical.refresh_from_db()
        duplicate.refresh_from_db()
        assert canonical.discharge_date is None
        assert duplicate.merged_into_id is None
        canonical_item.refresh_from_db()
        duplicate_item.refresh_from_db()
        assert canonical_item.status == STATUS_CLOSED_UNRESOLVED
        assert duplicate_item.status == STATUS_CLOSED_UNRESOLVED
        assert duplicate_item.admission_id == duplicate.pk
        assert PendingItemRevision.objects.filter(
            item=canonical_item
        ).count() == 2
        assert PendingItemRevision.objects.filter(
            item=duplicate_item
        ).count() == 2


@pytest.mark.django_db
class TestHttpAfterExit:
    """R5/validation: operational cycle through HTTP and the writers."""

    def test_authorized_create_exit_history_post_rejected_repeat(
        self, writer_client: Client
    ) -> None:
        patient = _make_patient("P_S2_HTTP")
        admission = _make_admission(patient, "ADM_S2_HTTP")
        _make_census_row("P_S2_HTTP")
        outro = _outro_type()
        list_url = f"/admissions/{admission.pk}/pending-items/"

        created = writer_client.post(
            list_url,
            {
                "item_type": str(outro.pk),
                "description": "pendencia operacional sintetica",
            },
        )
        assert created.status_code == 302
        item = PendingItem.objects.get(admission=admission)

        status = _reconcile_by_key(
            "P_S2_HTTP", "ADM_S2_HTTP", "2026-06-05T10:00:00"
        )
        assert status == RECONCILIATION_STATUS_RECONCILED
        _assert_system_close(item, 1)

        history = writer_client.get(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/history/"
        )
        assert history.status_code == 200
        content = history.content.decode()
        assert "Sistema" in content
        assert SYSTEM_CLOSE_NOTE in content
        assert "Encerrada sem resolu" in content

        rejected = writer_client.post(
            list_url,
            {
                "item_type": str(outro.pk),
                "description": "tentativa apos saida",
            },
        )
        assert rejected.status_code == 403
        edit_rejected = writer_client.post(
            f"/admissions/{admission.pk}/pending-items/{item.pk}/edit/",
            {
                "item_type": str(outro.pk),
                "description": "edicao apos saida",
                "expected_version": str(item.version),
            },
        )
        assert edit_rejected.status_code == 403

        repeat = _reconcile_by_key(
            "P_S2_HTTP", "ADM_S2_HTTP", "2026-06-05T10:00:00"
        )
        assert repeat == RECONCILIATION_STATUS_ALREADY_RECONCILED
        assert (
            PendingItemRevision.objects.filter(item=item).count() == 2
        )


def _run_race(*workers) -> dict[str, object]:
    """Run workers from a barrier on separate connections (R4).

    Returns each worker outcome: ``"ok"`` or the raised exception.
    No sleeps: the barrier alone synchronizes the start.
    """
    barrier = threading.Barrier(len(workers))
    outcomes: dict[str, object] = {}

    def _wrap(name: str, worker) -> None:
        try:
            barrier.wait(timeout=30)
            outcomes[name] = worker()
        except Exception as exc:  # noqa: BLE001 - collected, asserted later
            outcomes[name] = exc
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=_wrap, args=(f"w{i}", worker))
        for i, worker in enumerate(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
        assert not thread.is_alive()
    return outcomes


def _assert_consistent_history(item: PendingItem) -> None:
    item.refresh_from_db()
    versions = list(
        PendingItemRevision.objects.filter(item=item)
        .order_by("version")
        .values_list("version", flat=True)
    )
    assert versions == list(range(1, item.version + 1))


@pytest.mark.django_db(transaction=True)
@requires_postgres
class TestExitConcurrency:
    """R4: writers serialize with human edits/creates (PostgreSQL only)."""

    def test_snapshot_races_with_human_edit(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_CC1")
        admission = _make_admission(patient, "ADM_S2_CC1")
        _make_census_row("P_S2_CC1")
        item = _make_item(admission, writer, "texto original cc1")
        item_type = item.item_type

        def _edit():
            update_pending_item(
                item=item,
                item_type=item_type,
                description="texto editado cc1",
                author=writer,
                expected_version=1,
            )
            return "ok"

        def _close():
            upsert_admission_snapshot(
                Patient.objects.get(pk=patient.pk),
                [
                    {
                        "admission_key": "ADM_S2_CC1",
                        "admission_start": "2026-06-01T08:00:00",
                        "admission_end": "2026-06-05T10:00:00",
                    }
                ],
            )
            return "ok"

        outcomes = _run_race(_edit, _close)

        assert outcomes["w1"] == "ok"
        assert outcomes["w0"] == "ok" or isinstance(
            outcomes["w0"], IneligibleAdmissionError
        )
        admission.refresh_from_db()
        assert admission.discharge_date is not None
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        if outcomes["w0"] == "ok":
            assert item.description == "texto editado cc1"
            assert item.version == 3
        else:
            assert item.description == "texto original cc1"
            assert item.version == 2
        _assert_consistent_history(item)

    def test_snapshot_races_with_human_create(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_CC2")
        admission = _make_admission(patient, "ADM_S2_CC2")
        _make_census_row("P_S2_CC2")
        outro = _outro_type()

        def _create():
            create_pending_item(
                admission=admission,
                item_type=outro,
                description="pendencia criada na corrida",
                author=writer,
            )
            return "ok"

        def _close():
            upsert_admission_snapshot(
                Patient.objects.get(pk=patient.pk),
                [
                    {
                        "admission_key": "ADM_S2_CC2",
                        "admission_start": "2026-06-01T08:00:00",
                        "admission_end": "2026-06-05T10:00:00",
                    }
                ],
            )
            return "ok"

        outcomes = _run_race(_create, _close)

        assert outcomes["w1"] == "ok"
        assert outcomes["w0"] == "ok" or isinstance(
            outcomes["w0"], IneligibleAdmissionError
        )
        admission.refresh_from_db()
        assert admission.discharge_date is not None
        remaining = list(PendingItem.objects.filter(admission=admission))
        if outcomes["w0"] == "ok":
            assert len(remaining) == 1
            assert remaining[0].status == STATUS_CLOSED_UNRESOLVED
            assert remaining[0].version == 2
            _assert_consistent_history(remaining[0])
        else:
            assert remaining == []

    def test_reconciliation_races_with_human_edit(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_CC3")
        admission = _make_admission(patient, "ADM_S2_CC3")
        _make_census_row("P_S2_CC3")
        item = _make_item(admission, writer, "texto original cc3")
        item_type = item.item_type

        def _edit():
            update_pending_item(
                item=item,
                item_type=item_type,
                description="texto editado cc3",
                author=writer,
                expected_version=1,
            )
            return "ok"

        def _close():
            return _reconcile_by_key(
                "P_S2_CC3", "ADM_S2_CC3", "2026-06-05T10:00:00"
            )

        outcomes = _run_race(_edit, _close)

        assert outcomes["w1"] == RECONCILIATION_STATUS_RECONCILED
        assert outcomes["w0"] == "ok" or isinstance(
            outcomes["w0"], IneligibleAdmissionError
        )
        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        if outcomes["w0"] == "ok":
            assert item.description == "texto editado cc3"
            assert item.version == 3
        else:
            assert item.description == "texto original cc3"
            assert item.version == 2
        _assert_consistent_history(item)

    def test_reconciliation_races_with_human_create(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_CC4")
        admission = _make_admission(patient, "ADM_S2_CC4")
        _make_census_row("P_S2_CC4")
        outro = _outro_type()

        def _create():
            create_pending_item(
                admission=admission,
                item_type=outro,
                description="pendencia criada na corrida rec",
                author=writer,
            )
            return "ok"

        def _close():
            return _reconcile_by_key(
                "P_S2_CC4", "ADM_S2_CC4", "2026-06-05T10:00:00"
            )

        outcomes = _run_race(_create, _close)

        assert outcomes["w1"] == RECONCILIATION_STATUS_RECONCILED
        assert outcomes["w0"] == "ok" or isinstance(
            outcomes["w0"], IneligibleAdmissionError
        )
        remaining = list(PendingItem.objects.filter(admission=admission))
        if outcomes["w0"] == "ok":
            assert len(remaining) == 1
            assert remaining[0].status == STATUS_CLOSED_UNRESOLVED
            assert remaining[0].version == 2
            _assert_consistent_history(remaining[0])
        else:
            assert remaining == []

    def test_merge_races_with_human_edit(
        self, db: object, writer: User
    ) -> None:
        # Open/closed pair: the duplicate is the single open admission,
        # so the human edit is eligible until the merge commits.
        patient = _make_patient("P_S2_CC5")
        canonical = _make_admission(
            patient,
            "ADM_S2_CC5_CAN",
            start="2026-05-01T08:00:00",
            end="2026-05-03T10:00:00",
        )
        duplicate = _make_admission(
            patient, "ADM_S2_CC5_DUP", start="2026-05-01T09:00:00"
        )
        _make_census_row("P_S2_CC5")
        item = _make_item(duplicate, writer, "texto original cc5")
        item_type = item.item_type
        confirmation = _confirmation(end=None)

        def _edit():
            update_pending_item(
                item=item,
                item_type=item_type,
                description="texto editado cc5",
                author=writer,
                expected_version=1,
            )
            return "ok"

        def _merge_run():
            merge_admissions(
                first=Admission.objects.get(pk=duplicate.pk),
                second=Admission.objects.get(pk=canonical.pk),
                confirmation=confirmation,
                expected_fingerprint=source_confirmation_fingerprint(
                    confirmation
                ),
            )
            return "ok"

        outcomes = _run_race(_edit, _merge_run)

        assert outcomes["w1"] == "ok"
        assert outcomes["w0"] == "ok" or isinstance(
            outcomes["w0"], IneligibleAdmissionError
        )
        item.refresh_from_db()
        assert item.admission_id == canonical.pk
        assert item.status == STATUS_CLOSED_UNRESOLVED
        if outcomes["w0"] == "ok":
            assert item.description == "texto editado cc5"
            assert item.version == 3
        else:
            assert item.description == "texto original cc5"
            assert item.version == 2
        _assert_consistent_history(item)
