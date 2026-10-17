"""PEND-S1: pending items services, policy, catalog protection and merge.

Covers R1 (Outro/group bootstrap, duplicate types allowed, rename/delete
guards), R3 (group-only writes, superuser included), R4 (FSM, atomicity,
version conflicts) and R6 (merge registry, consolidation guard and the
residual guard-vs-create race as a conservative failure).

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError

from apps.census.models import BedStatus, CensusSnapshot
from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.services import _consolidate_period_duplicates
from apps.patients.admission_merge import (
    RELATION_DISPOSITION_REPOINT,
    AdmissionSourceConfirmation,
    SourceEpisode,
    build_relation_registry,
    merge_admissions,
    rollback_admission_merge,
    source_confirmation_fingerprint,
)
from apps.patients.models import Admission, Patient
from apps.pending_items import policy
from apps.pending_items.eligibility import IneligibleAdmissionError
from apps.pending_items.models import (
    ACTION_CREATED,
    ACTION_FINALIZED,
    ACTION_UPDATED,
    GROUP_NAME,
    INELIGIBLE_MESSAGE,
    OUTRO_NAME,
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.services import (
    InvalidStatusTransitionError,
    VersionConflictError,
    create_pending_item,
    finalize_pending_item,
    update_pending_item,
)

TZ = ZoneInfo("America/Bahia")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


@pytest.fixture
def writer(db: object) -> User:
    user = User.objects.create_user(username="pend_writer", password="x")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    return user


@pytest.fixture
def colleague(db: object) -> User:
    user = User.objects.create_user(username="pend_colleague", password="x")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    return user


@pytest.fixture
def reader(db: object) -> User:
    return User.objects.create_user(username="pend_reader", password="x")


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


def _confirmation(local_day: str = "2026-05-01") -> AdmissionSourceConfirmation:
    from datetime import date

    return AdmissionSourceConfirmation(
        patient_record="P_PEND_MERGE",
        local_admission_date=date.fromisoformat(local_day),
        captured_at=_dt("2026-05-04T09:00:00"),
        failed=False,
        episodes=(
            SourceEpisode(
                source_admission_key="ADM_CLOSED",
                admission_start=_dt("2026-05-01T08:00:00"),
                admission_end=None,
            ),
        ),
    )


def _merge_pair(canonical: Admission, duplicate: Admission):
    from apps.patients.models import AdmissionMergeOperation

    confirmation = _confirmation()
    result = merge_admissions(
        first=duplicate,
        second=canonical,
        confirmation=confirmation,
        expected_fingerprint=source_confirmation_fingerprint(confirmation),
    )
    return AdmissionMergeOperation.objects.get(
        operation_uuid=result.operation_uuid
    )


@pytest.mark.django_db
class TestBootstrap:
    def test_outro_is_available(self, db: object) -> None:
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        assert outro.name == OUTRO_NAME

    def test_group_exists_and_has_no_users(self, db: object) -> None:
        group = Group.objects.get(name=GROUP_NAME)
        assert group.user_set.count() == 0


@pytest.mark.django_db
class TestWritePolicy:
    def test_member_can_write(self, writer: User) -> None:
        assert policy.can_write_pending_items(writer) is True

    def test_non_member_cannot_write(self, reader: User) -> None:
        assert policy.can_write_pending_items(reader) is False

    def test_superuser_without_group_cannot_write(self, db: object) -> None:
        admin = User.objects.create_superuser(
            username="pend_admin", password="x", email=""
        )
        assert policy.can_write_pending_items(admin) is False

    def test_staff_without_group_cannot_write(self, db: object) -> None:
        staff = User.objects.create_user(username="pend_staff", password="x")
        staff.is_staff = True
        staff.save()
        assert policy.can_write_pending_items(staff) is False

    def test_anonymous_cannot_write(self, db: object) -> None:
        from django.contrib.auth.models import AnonymousUser

        assert policy.can_write_pending_items(AnonymousUser()) is False

    def test_lost_membership_denies(self, writer: User) -> None:
        Group.objects.get(name=GROUP_NAME).user_set.remove(writer)
        writer = User.objects.get(pk=writer.pk)
        assert policy.can_write_pending_items(writer) is False

    def test_require_raises_permission_denied(self, reader: User) -> None:
        with pytest.raises(PermissionDenied):
            policy.require_can_write(reader)


@pytest.mark.django_db
class TestOutroProtection:
    def test_rename_outro_is_blocked_without_use(self, db: object) -> None:
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        outro.name = "Renamed"
        with pytest.raises(ValidationError):
            outro.save()

    def test_delete_outro_is_blocked_without_use(self, db: object) -> None:
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        with pytest.raises(ProtectedError):
            outro.delete()
        assert PendingItemType.objects.filter(slug=OUTRO_SLUG).exists()

    def test_delete_referenced_type_is_blocked(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_REF")
        admission = _make_admission(patient, "ADM_PEND_REF")
        _make_census_row("P_PEND_REF")
        item_type = PendingItemType.objects.create(
            slug="doc", name="Documento"
        )
        create_pending_item(
            admission=admission,
            item_type=item_type,
            description="aguardando documento sintetico",
            author=writer,
        )
        with pytest.raises(ProtectedError):
            item_type.delete()

    def test_allowed_rename_preserves_revision_snapshots(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_REN")
        admission = _make_admission(patient, "ADM_PEND_REN")
        _make_census_row("P_PEND_REN")
        item_type = PendingItemType.objects.create(
            slug="exam", name="Exame Antigo"
        )
        item = create_pending_item(
            admission=admission,
            item_type=item_type,
            description="aguardando exame sintetico",
            author=writer,
        )
        item_type.name = "Exame Novo"
        item_type.save()
        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.type_name == "Exame Antigo"
        item.refresh_from_db()
        assert item.item_type.name == "Exame Novo"


@pytest.mark.django_db
class TestCreateService:
    def test_create_ok_writes_item_and_first_revision(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_C1")
        admission = _make_admission(patient, "ADM_PEND_C1")
        _make_census_row("P_PEND_C1")
        item = create_pending_item(
            admission=admission,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="  barreira sintetica de teste  ",
            author=writer,
        )
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert item.finalized_at is None
        assert item.created_by_id == writer.pk
        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.action == ACTION_CREATED
        assert revision.description == "barreira sintetica de teste"
        assert revision.status == STATUS_ACTIVE
        assert revision.author_id == writer.pk
        assert revision.is_system is False

    def test_duplicate_type_allowed(self, db: object, writer: User) -> None:
        patient = _make_patient("P_PEND_C2")
        admission = _make_admission(patient, "ADM_PEND_C2")
        _make_census_row("P_PEND_C2")
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        first = create_pending_item(
            admission=admission,
            item_type=outro,
            description="primeira pendencia sintetica",
            author=writer,
        )
        second = create_pending_item(
            admission=admission,
            item_type=outro,
            description="segunda pendencia sintetica",
            author=writer,
        )
        assert first.pk != second.pk
        assert first.status == STATUS_ACTIVE
        assert second.status == STATUS_ACTIVE

    def test_blank_description_rejected_without_side_effects(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_C3")
        admission = _make_admission(patient, "ADM_PEND_C3")
        _make_census_row("P_PEND_C3")
        with pytest.raises(ValidationError):
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="   ",
                author=writer,
            )
        assert PendingItem.objects.count() == 0
        assert PendingItemRevision.objects.count() == 0

    def test_non_member_denied(self, db: object, reader: User) -> None:
        patient = _make_patient("P_PEND_C4")
        admission = _make_admission(patient, "ADM_PEND_C4")
        _make_census_row("P_PEND_C4")
        with pytest.raises(PermissionDenied):
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="tentativa de leitor",
                author=reader,
            )
        assert PendingItem.objects.count() == 0

    def test_superuser_without_group_denied(self, db: object) -> None:
        admin = User.objects.create_superuser(
            username="pend_admin2", password="x", email=""
        )
        patient = _make_patient("P_PEND_C5")
        admission = _make_admission(patient, "ADM_PEND_C5")
        _make_census_row("P_PEND_C5")
        with pytest.raises(PermissionDenied):
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="tentativa de superusuario",
                author=admin,
            )
        assert PendingItem.objects.count() == 0

    def test_absent_from_census_blocked_with_exact_message(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_C6")
        admission = _make_admission(patient, "ADM_PEND_C6")
        with pytest.raises(IneligibleAdmissionError) as exc:
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="sem censo",
                author=writer,
            )
        assert str(exc.value) == INELIGIBLE_MESSAGE
        assert PendingItem.objects.count() == 0

    def test_conflicting_census_occupations_blocked(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_C7")
        admission = _make_admission(patient, "ADM_PEND_C7")
        _make_census_row("P_PEND_C7", setor="UTI", leito="U01")
        _make_census_row("P_PEND_C7", setor="ENFERMARIA", leito="E02")
        with pytest.raises(IneligibleAdmissionError) as exc:
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="censo conflitante",
                author=writer,
            )
        assert str(exc.value) == INELIGIBLE_MESSAGE

    def test_equivalent_census_repetition_counts_once(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_C8")
        admission = _make_admission(patient, "ADM_PEND_C8")
        _make_census_row("P_PEND_C8", setor="UTI", leito="U01")
        _make_census_row("P_PEND_C8", setor="UTI", leito="U01")
        item = create_pending_item(
            admission=admission,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="repeticao equivalente",
            author=writer,
        )
        assert item.pk is not None

    def test_two_open_admissions_blocked(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_C9")
        admission = _make_admission(patient, "ADM_PEND_C9A")
        _make_admission(patient, "ADM_PEND_C9B")
        _make_census_row("P_PEND_C9")
        with pytest.raises(IneligibleAdmissionError) as exc:
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="duas abertas",
                author=writer,
            )
        assert str(exc.value) == INELIGIBLE_MESSAGE

    def test_closed_admission_blocked(self, db: object, writer: User) -> None:
        patient = _make_patient("P_PEND_C10")
        admission = _make_admission(
            patient, "ADM_PEND_C10", end="2026-06-05T10:00:00"
        )
        _make_census_row("P_PEND_C10")
        with pytest.raises(IneligibleAdmissionError):
            create_pending_item(
                admission=admission,
                item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
                description="episodio encerrado",
                author=writer,
            )


@pytest.mark.django_db
class TestUpdateService:
    def _eligible_item(self, writer: User, key: str = "P_PEND_U1"):
        patient = _make_patient(key)
        admission = _make_admission(patient, f"ADM_{key}")
        _make_census_row(key)
        item = create_pending_item(
            admission=admission,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="texto original sintetico",
            author=writer,
        )
        return item

    def test_edit_active_bumps_version(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        updated, changed = update_pending_item(
            item=item,
            item_type=item.item_type,
            description="texto alterado sintetico",
            author=writer,
            expected_version=1,
        )
        assert changed is True
        assert updated.version == 2
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.action == ACTION_UPDATED
        assert revision.description == "texto alterado sintetico"

    def test_no_effective_change_creates_no_version(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        updated, changed = update_pending_item(
            item=item,
            item_type=item.item_type,
            description="texto original sintetico",
            author=writer,
            expected_version=1,
        )
        assert changed is False
        assert updated.version == 1
        assert PendingItemRevision.objects.filter(item=item).count() == 1

    def test_stale_version_conflicts_without_overwrite(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        update_pending_item(
            item=item,
            item_type=item.item_type,
            description="texto mais recente",
            author=writer,
            expected_version=1,
        )
        with pytest.raises(VersionConflictError):
            update_pending_item(
                item=PendingItem.objects.get(pk=item.pk),
                item_type=item.item_type,
                description="envio antigo",
                author=writer,
                expected_version=1,
            )
        item.refresh_from_db()
        assert item.description == "texto mais recente"
        assert item.version == 2

    def test_colleague_edit_preserves_creation_author(
        self, db: object, writer: User, colleague: User
    ) -> None:
        item = self._eligible_item(writer)
        updated, _ = update_pending_item(
            item=item,
            item_type=item.item_type,
            description="edicao de colega",
            author=colleague,
            expected_version=1,
        )
        assert updated.created_by_id == writer.pk
        assert updated.updated_by_id == colleague.pk
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.author_id == colleague.pk

    def test_finalized_item_rejects_edit(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        finalize_pending_item(
            item=item,
            target_status=STATUS_RESOLVED,
            note="",
            author=writer,
            expected_version=1,
        )
        with pytest.raises(InvalidStatusTransitionError):
            update_pending_item(
                item=PendingItem.objects.get(pk=item.pk),
                item_type=item.item_type,
                description="tentativa tardia",
                author=writer,
                expected_version=2,
            )

    def test_lost_eligibility_blocks_edit(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer, key="P_PEND_U2")
        CensusSnapshot.objects.filter(prontuario="P_PEND_U2").delete()
        with pytest.raises(IneligibleAdmissionError) as exc:
            update_pending_item(
                item=item,
                item_type=item.item_type,
                description="edicao sem censo",
                author=writer,
                expected_version=1,
            )
        assert str(exc.value) == INELIGIBLE_MESSAGE

    def test_revision_failure_rolls_back_item_change(
        self, db: object, writer: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = self._eligible_item(writer)

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic revision failure")

        monkeypatch.setattr(
            PendingItemRevision.objects, "create", _boom
        )
        with pytest.raises(RuntimeError):
            update_pending_item(
                item=item,
                item_type=item.item_type,
                description="mudanca desfeita",
                author=writer,
                expected_version=1,
            )
        item.refresh_from_db()
        assert item.description == "texto original sintetico"
        assert item.version == 1
        assert PendingItemRevision.objects.filter(item=item).count() == 1


@pytest.mark.django_db
class TestFinalizeService:
    def _eligible_item(self, writer: User, key: str = "P_PEND_F1"):
        patient = _make_patient(key)
        admission = _make_admission(patient, f"ADM_{key}")
        _make_census_row(key)
        return create_pending_item(
            admission=admission,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="pendencia a finalizar",
            author=writer,
        )

    def test_finalize_without_note_preserves_description(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        finalized = finalize_pending_item(
            item=item,
            target_status=STATUS_RESOLVED,
            note="",
            author=writer,
            expected_version=1,
        )
        assert finalized.status == STATUS_RESOLVED
        assert finalized.description == "pendencia a finalizar"
        assert finalized.finalized_at is not None
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.action == ACTION_FINALIZED
        assert revision.note == ""

    def test_finalize_closed_unresolved_with_note(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        finalized = finalize_pending_item(
            item=item,
            target_status=STATUS_CLOSED_UNRESOLVED,
            note="cadastro por engano sintetico",
            author=writer,
            expected_version=1,
        )
        assert finalized.status == STATUS_CLOSED_UNRESOLVED
        revision = PendingItemRevision.objects.get(item=item, version=2)
        assert revision.note == "cadastro por engano sintetico"

    def test_finalized_item_is_immutable(
        self, db: object, writer: User
    ) -> None:
        item = self._eligible_item(writer)
        finalize_pending_item(
            item=item,
            target_status=STATUS_RESOLVED,
            note="",
            author=writer,
            expected_version=1,
        )
        with pytest.raises(InvalidStatusTransitionError):
            finalize_pending_item(
                item=PendingItem.objects.get(pk=item.pk),
                target_status=STATUS_CLOSED_UNRESOLVED,
                note="",
                author=writer,
                expected_version=2,
            )
        item.refresh_from_db()
        assert item.status == STATUS_RESOLVED
        assert PendingItemRevision.objects.filter(item=item).count() == 2

    def test_invalid_target_rejected(self, db: object, writer: User) -> None:
        item = self._eligible_item(writer)
        with pytest.raises(InvalidStatusTransitionError):
            finalize_pending_item(
                item=item,
                target_status=STATUS_ACTIVE,
                note="",
                author=writer,
                expected_version=1,
            )

    def test_stale_version_conflicts(self, db: object, writer: User) -> None:
        item = self._eligible_item(writer)
        update_pending_item(
            item=item,
            item_type=item.item_type,
            description="atualizacao concorrente",
            author=writer,
            expected_version=1,
        )
        with pytest.raises(VersionConflictError):
            finalize_pending_item(
                item=PendingItem.objects.get(pk=item.pk),
                target_status=STATUS_RESOLVED,
                note="",
                author=writer,
                expected_version=1,
            )


@pytest.mark.django_db
class TestHistoryPreservation:
    def test_user_deletion_preserves_author_labels(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_H1")
        admission = _make_admission(patient, "ADM_PEND_H1")
        _make_census_row("P_PEND_H1")
        item = create_pending_item(
            admission=admission,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="autoria a preservar",
            author=writer,
        )
        writer.delete()
        revision = PendingItemRevision.objects.get(item=item, version=1)
        assert revision.author_id is None
        assert revision.author_name == "pend_writer"
        item.refresh_from_db()
        assert item.created_by_id is None
        assert item.created_by_name == "pend_writer"

    def test_revisions_order_deterministically(
        self, db: object, writer: User
    ) -> None:
        patient = _make_patient("P_PEND_H2")
        admission = _make_admission(patient, "ADM_PEND_H2")
        _make_census_row("P_PEND_H2")
        item = create_pending_item(
            admission=admission,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="v1",
            author=writer,
        )
        update_pending_item(
            item=item,
            item_type=item.item_type,
            description="v2",
            author=writer,
            expected_version=1,
        )
        versions = list(
            PendingItemRevision.objects.filter(item=item).values_list(
                "version", flat=True
            )
        )
        assert versions == [1, 2]


@pytest.mark.django_db
class TestMergePreservation:
    def _pair_with_item(self, writer: User):
        patient = _make_patient("P_PEND_M1")
        canonical = _make_admission(
            patient, "ADM_PEND_M1A", start="2026-05-01T08:00:00"
        )
        duplicate = _make_admission(
            patient, "ADM_PEND_M1B", start="2026-05-01T10:00:00"
        )
        outro = PendingItemType.objects.get(slug=OUTRO_SLUG)
        item = PendingItem.objects.create(
            admission=duplicate,
            item_type=outro,
            description="pendencia na duplicata",
            status=STATUS_RESOLVED,
            version=2,
            finalized_at=_dt("2026-05-03T10:00:00"),
            created_by=writer,
            created_by_name=writer.username,
            updated_by=writer,
            updated_by_name=writer.username,
        )
        PendingItemRevision.objects.create(
            item=item,
            version=1,
            action=ACTION_CREATED,
            item_type=outro,
            type_name=outro.name,
            description="pendencia na duplicata",
            status=STATUS_ACTIVE,
            author=writer,
            author_name=writer.username,
        )
        PendingItemRevision.objects.create(
            item=item,
            version=2,
            action=ACTION_FINALIZED,
            item_type=outro,
            type_name=outro.name,
            description="pendencia na duplicata",
            status=STATUS_RESOLVED,
            author=writer,
            author_name=writer.username,
        )
        return patient, canonical, duplicate

    def test_registry_classifies_pending_items_as_repoint(
        self, db: object
    ) -> None:
        registry = build_relation_registry()
        assert (
            registry["pending_items"].disposition
            == RELATION_DISPOSITION_REPOINT
        )

    def test_merge_transfers_items_without_duplicating_versions(
        self, db: object, writer: User
    ) -> None:
        patient, canonical, duplicate = self._pair_with_item(writer)
        operation = _merge_pair(canonical, duplicate)
        assert PendingItem.objects.filter(admission=canonical).count() == 1
        assert not PendingItem.objects.filter(admission=duplicate).exists()
        item = PendingItem.objects.get(admission=canonical)
        assert item.status == STATUS_RESOLVED
        assert PendingItemRevision.objects.filter(item=item).count() == 2
        manifest_text = str(operation.relation_manifest)
        assert "pendencia na duplicata" not in manifest_text

    def test_rollback_restores_items_without_reopening(
        self, db: object, writer: User
    ) -> None:
        patient, canonical, duplicate = self._pair_with_item(writer)
        operation = _merge_pair(canonical, duplicate)
        rollback_admission_merge(operation=operation)
        assert PendingItem.objects.filter(admission=duplicate).count() == 1
        item = PendingItem.objects.get(admission=duplicate)
        assert item.status == STATUS_RESOLVED
        assert PendingItemRevision.objects.filter(item=item).count() == 2


@pytest.mark.django_db
class TestConsolidationGuard:
    def _duplicate_set(self, key: str = "P_PEND_G1"):
        patient = _make_patient(key)
        first = _make_admission(
            patient, f"ADM_{key}_A", start="2026-06-01T08:00:00"
        )
        second = _make_admission(
            patient, f"ADM_{key}_B", start="2026-06-01T08:00:00"
        )
        ClinicalEvent.objects.create(
            admission=second,
            patient=patient,
            event_identity_key=f"EVT-{key}",
            content_hash="hash",
            happened_at=_dt("2026-06-01T09:00:00"),
            author_name="AUTOR SINTETICO",
            profession_type="medica",
            content_text="Evolucao sintetica.",
        )
        return patient, first, second

    def test_set_with_pending_items_is_not_consolidated(
        self, db: object, writer: User
    ) -> None:
        patient, first, second = self._duplicate_set()
        PendingItem.objects.create(
            admission=second,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="pendencia bloqueia consolidacao",
            status=STATUS_ACTIVE,
            version=1,
            created_by=writer,
            created_by_name=writer.username,
        )
        _consolidate_period_duplicates(
            patient,
            _dt("2026-06-01T08:00:00"),
            None,
            "tasy",
        )
        assert Admission.objects.filter(patient=patient).count() == 2
        assert PendingItem.objects.count() == 1
        assert ClinicalEvent.objects.get().admission_id == second.pk

    def test_set_without_pending_items_keeps_legacy_behavior(
        self, db: object
    ) -> None:
        patient, first, second = self._duplicate_set(key="P_PEND_G2")
        _consolidate_period_duplicates(
            patient,
            _dt("2026-06-01T08:00:00"),
            None,
            "tasy",
        )
        remaining = list(Admission.objects.filter(patient=patient))
        assert len(remaining) == 1
        assert remaining[0].pk == second.pk
        assert ClinicalEvent.objects.get().admission_id == second.pk

    def test_interleaved_create_fails_conservatively(
        self, db: object, writer: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import apps.ingestion.services as ingestion_services

        patient, first, second = self._duplicate_set(key="P_PEND_G3")
        ClinicalEvent.objects.create(
            admission=first,
            patient=patient,
            event_identity_key="EVT-P_PEND_G3-FIRST",
            content_hash="hash-first",
            happened_at=_dt("2026-06-01T09:00:00"),
            author_name="AUTOR SINTETICO",
            profession_type="medica",
            content_text="Evolucao sintetica.",
        )
        # Committed before the consolidation runs: models the concurrent
        # creation a stale guard read would miss.
        PendingItem.objects.create(
            admission_id=second.pk,
            item_type=PendingItemType.objects.get(slug=OUTRO_SLUG),
            description="pendencia intercalada",
            status=STATUS_ACTIVE,
            version=1,
            created_by=writer,
            created_by_name=writer.username,
        )
        monkeypatch.setattr(
            ingestion_services,
            "_period_set_has_pending_items",
            lambda ids: False,
        )
        with pytest.raises(ProtectedError):
            _consolidate_period_duplicates(
                patient,
                _dt("2026-06-01T08:00:00"),
                None,
                "tasy",
            )
        assert Admission.objects.filter(patient=patient).count() == 2
        assert PendingItem.objects.count() == 1
        assert (
            ClinicalEvent.objects.get(
                event_identity_key="EVT-P_PEND_G3"
            ).admission_id
            == second.pk
        )
        assert (
            ClinicalEvent.objects.get(
                event_identity_key="EVT-P_PEND_G3-FIRST"
            ).admission_id
            == first.pk
        )
