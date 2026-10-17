"""PEND-S2: unit tests for the idempotent exit-close helper.

Covers the deterministic seam of ``close_pending_items_for_confirmed_exit``
(open episodes are a no-op, closed episodes close only actives, human
finals are preserved, repeated calls add no versions). Writer wiring is
covered by ``tests/integration/test_pending_items_exit_lifecycle.py``.

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.utils import timezone

from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    ACTION_FINALIZED,
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.services import (
    CONFIRMED_EXIT_REASON,
    SYSTEM_AUTHOR_NAME,
    close_pending_items_for_confirmed_exit,
)

TZ = ZoneInfo("America/Bahia")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


@pytest.fixture
def writer(db: object) -> User:
    user = User.objects.create_user(username="s2_unit_writer", password="x")
    Group.objects.get(name="Desospitalização").user_set.add(user)
    return user


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    end: str | None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt("2026-06-01T08:00:00"),
        discharge_date=_dt(end) if end else None,
    )


def _seed_item(
    admission: Admission,
    author: User,
    description: str,
    status: str = STATUS_ACTIVE,
    version: int = 1,
) -> PendingItem:
    item_type = PendingItemType.objects.get(slug=OUTRO_SLUG)
    label = author.get_username()
    return PendingItem.objects.create(
        admission=admission,
        item_type=item_type,
        description=description,
        status=status,
        version=version,
        finalized_at=(
            _dt("2026-06-04T10:00:00") if status != STATUS_ACTIVE else None
        ),
        created_by=author,
        created_by_name=label,
        updated_by=author,
        updated_by_name=label,
        is_system_updated=False,
    )


def _close_locked(admission: Admission) -> int:
    """Call the helper the way writers do: admission locked, in-txn."""
    with transaction.atomic():
        locked = Admission.objects.select_for_update().get(pk=admission.pk)
        return close_pending_items_for_confirmed_exit(admission=locked)


@pytest.mark.django_db
class TestClosePendingItemsForConfirmedExit:
    def test_open_episode_is_noop(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_U1")
        admission = _make_admission(patient, "ADM_S2_U1", None)
        item = _seed_item(admission, writer, "pendencia aberta")

        closed = _close_locked(admission)

        assert closed == 0
        item.refresh_from_db()
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert PendingItemRevision.objects.filter(item=item).count() == 0

    def test_closed_episode_closes_only_actives(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_U2")
        admission = _make_admission(
            patient, "ADM_S2_U2", "2026-06-05T10:00:00"
        )
        other = _make_admission(patient, "ADM_S2_U2_OTHER", None)
        first = _seed_item(admission, writer, "primeira ativa")
        second = _seed_item(admission, writer, "segunda ativa")
        resolved = _seed_item(
            admission, writer, "resolvida", STATUS_RESOLVED, 2
        )
        foreign = _seed_item(other, writer, "ativa de outro episodio")

        close_started = timezone.now()
        closed = _close_locked(admission)
        close_finished = timezone.now()

        assert closed == 2
        for item in (first, second):
            item.refresh_from_db()
            assert item.status == STATUS_CLOSED_UNRESOLVED
            assert item.version == 2
            assert item.finalized_at is not None
            # Processing time, never backdated to the effective exit: it
            # must fall inside the wall-clock bracket of the close call.
            assert close_started <= item.finalized_at <= close_finished
            assert item.is_system_updated is True
            assert item.updated_by_id is None
            assert item.updated_by_name == SYSTEM_AUTHOR_NAME
            assert item.created_by_id == writer.pk
            revision = PendingItemRevision.objects.get(
                item=item, version=2
            )
            assert revision.action == ACTION_FINALIZED
            assert revision.status == STATUS_CLOSED_UNRESOLVED
            assert revision.note == CONFIRMED_EXIT_REASON == "confirmed_exit"
            assert revision.is_system is True
            assert revision.author_id is None
            assert revision.author_name == SYSTEM_AUTHOR_NAME
        resolved.refresh_from_db()
        assert resolved.status == STATUS_RESOLVED
        assert resolved.version == 2
        assert resolved.updated_by_id == writer.pk
        assert (
            PendingItemRevision.objects.filter(item=resolved).count() == 0
        )
        foreign.refresh_from_db()
        assert foreign.status == STATUS_ACTIVE
        assert foreign.version == 1

    def test_repeated_call_adds_no_versions(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_S2_U3")
        admission = _make_admission(
            patient, "ADM_S2_U3", "2026-06-05T10:00:00"
        )
        item = _seed_item(admission, writer, "pendencia repetida")

        assert _close_locked(admission) == 1
        assert _close_locked(admission) == 0

        item.refresh_from_db()
        assert item.status == STATUS_CLOSED_UNRESOLVED
        assert item.version == 2
        assert PendingItemRevision.objects.filter(item=item).count() == 1

    def test_contract_values(self, db: object) -> None:
        assert CONFIRMED_EXIT_REASON == "confirmed_exit"
        assert SYSTEM_AUTHOR_NAME == "Sistema"
