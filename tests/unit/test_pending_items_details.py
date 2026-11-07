"""STRUCT-PEND-S2: typed details, conditional observations and snapshots.

Covers R1 (PI-09/PI-01 profiles, coherence and local D3 constraints),
R2 (PI-06 complete/atomic revisions, detail-only versioning, no-op and
confirmed removal), R3 (finalization and confirmed exit copy details)
and R6 (service level of the non-destructive upgrade).

All fixtures are synthetic; no production source is ever contacted.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.census.models import BedStatus, CensusSnapshot
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    ACTION_FINALIZED,
    GROUP_NAME,
    OUTRO_SLUG,
    PROFILE_SCHEDULING,
    PROFILE_SIGNATURE,
    PROFILE_SIMPLE,
    PROFILE_TREATMENT,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    PendingItem,
    PendingItemCategory,
    PendingItemRevision,
    PendingItemType,
)
from apps.pending_items.services import (
    close_pending_items_for_confirmed_exit,
    create_pending_item,
    finalize_pending_item,
    update_pending_item,
)

TZ = ZoneInfo("America/Bahia")

START = date(2026, 11, 10)
END = date(2026, 11, 20)
SIGNED = datetime(2026, 11, 12, 9, 30, tzinfo=TZ)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


@pytest.fixture
def writer(db: object) -> User:
    user = User.objects.create_user(username="s2_detail_writer", password="x")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    return user


@pytest.fixture
def colleague(db: object) -> User:
    user = User.objects.create_user(username="s2_detail_peer", password="x")
    Group.objects.get(name=GROUP_NAME).user_set.add(user)
    return user


def _make_eligible(writer: User, key: str) -> Admission:
    patient = Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )
    admission = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM_{key}",
        admission_date=_dt("2026-06-01T08:00:00"),
    )
    CensusSnapshot.objects.create(
        captured_at=_dt("2026-06-10T08:00:00"),
        setor="CLINICA MEDICA",
        leito="L01",
        prontuario=key,
        nome=f"PACIENTE SINTETICO {key}",
        bed_status=BedStatus.OCCUPIED,
    )
    return admission


def _type(slug: str) -> PendingItemType:
    return PendingItemType.objects.get(slug=slug)


def _create(
    admission: Admission,
    writer: User,
    *,
    slug: str = "imagem-tomografia",
    description: str = "",
    details: dict | None = None,
    category: PendingItemCategory | None = None,
) -> PendingItem:
    return create_pending_item(
        admission=admission,
        item_type=_type(slug),
        category=category,
        description=description,
        details=details,
        author=writer,
    )


def _revision(item: PendingItem, version: int) -> PendingItemRevision:
    return PendingItemRevision.objects.get(item=item, version=version)


class TestSchedulingDetails:
    """PI-01/PI-09: explicit Sim/Não, optional civil date."""

    def test_empty_observation_accepted_with_explicit_no(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_SCHED_NO")
        item = _create(admission, writer, details={"is_scheduled": False})
        assert item.description == ""
        assert item.is_scheduled is False
        assert item.scheduled_date is None
        revision = _revision(item, 1)
        assert revision.description == ""
        assert revision.is_scheduled is False
        assert revision.status == STATUS_ACTIVE

    def test_missing_answer_is_rejected_without_side_effects(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_SCHED_MISSING")
        with pytest.raises(ValidationError):
            _create(admission, writer, details={})
        assert PendingItem.objects.count() == 0
        assert PendingItemRevision.objects.count() == 0

    def test_no_with_date_is_rejected_without_side_effects(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_SCHED_NO_DATE")
        with pytest.raises(ValidationError):
            _create(
                admission,
                writer,
                details={"is_scheduled": False, "scheduled_date": START},
            )
        assert PendingItem.objects.count() == 0
        assert PendingItemRevision.objects.count() == 0

    def test_yes_without_date_is_accepted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_SCHED_YES_NO_DATE")
        item = _create(admission, writer, details={"is_scheduled": True})
        assert item.is_scheduled is True
        assert item.scheduled_date is None
        assert _revision(item, 1).scheduled_date is None

    def test_yes_with_date_is_persisted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_SCHED_YES_DATE")
        item = _create(
            admission,
            writer,
            details={"is_scheduled": True, "scheduled_date": START},
        )
        assert item.scheduled_date == START
        assert _revision(item, 1).scheduled_date == START


class TestRnmDetails:
    """PI-09: contrast and sedation independent, absence is not Não."""

    def test_contrast_and_sedation_are_independent(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_RNM_COMBO")
        item = _create(
            admission,
            writer,
            slug="imagem-rnm",
            details={
                "is_scheduled": True,
                "scheduled_date": START,
                "contrast": True,
                "sedation": False,
            },
        )
        assert item.contrast is True
        assert item.sedation is False
        assert _revision(item, 1).contrast is True
        assert _revision(item, 1).sedation is False

    def test_unknown_stays_distinct_from_no(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_RNM_UNKNOWN")
        item = _create(
            admission,
            writer,
            slug="chd-rnm",
            details={"is_scheduled": False, "contrast": False},
        )
        assert item.contrast is False
        assert item.sedation is None

    def test_complements_rejected_on_type_without_rnm(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_RNM_WRONG_TYPE")
        with pytest.raises(ValidationError):
            _create(
                admission,
                writer,
                details={"is_scheduled": False, "contrast": True},
            )
        assert PendingItem.objects.count() == 0


class TestTreatmentAndSignatureDetails:
    """PI-09: partial treatment period and signature without side effects."""

    def test_partial_and_absent_periods_are_accepted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_TREAT_PARTIAL")
        only_start = _create(
            admission,
            writer,
            slug="infeccioso-antibioticos",
            details={"treatment_start_date": START},
        )
        assert only_start.treatment_start_date == START
        assert only_start.treatment_end_date is None
        none = _create(
            admission,
            writer,
            slug="infeccioso-antifungicos",
            details={},
        )
        assert none.treatment_start_date is None
        assert none.treatment_end_date is None
        both = _create(
            admission,
            writer,
            slug="infeccioso-antibioticos",
            details={
                "treatment_start_date": START,
                "treatment_end_date": END,
            },
        )
        assert both.treatment_end_date == END

    def test_end_before_start_is_rejected(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_TREAT_ORDER")
        with pytest.raises(ValidationError):
            _create(
                admission,
                writer,
                slug="infeccioso-antibioticos",
                details={
                    "treatment_start_date": END,
                    "treatment_end_date": START,
                },
            )
        assert PendingItem.objects.count() == 0

    def test_signature_is_preserved_without_finalizing(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_SIGNATURE")
        item = _create(
            admission,
            writer,
            slug="sumario-assinatura",
            details={"signature_at": SIGNED},
        )
        item.refresh_from_db()
        assert item.signature_at == SIGNED
        assert item.status == STATUS_ACTIVE
        assert item.finalized_at is None
        admission.refresh_from_db()
        assert admission.discharge_date is None

    def test_signature_rejected_on_scheduling_profile(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_SIGNATURE_WRONG")
        with pytest.raises(ValidationError):
            _create(
                admission,
                writer,
                details={"is_scheduled": False, "signature_at": SIGNED},
            )
        assert PendingItem.objects.count() == 0


class TestNoInferenceFromDatesOrNames:
    """PI-09/PI-11: past dates and clinical-sounding names stay administrative."""

    def test_past_scheduled_date_is_accepted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_PAST")
        past = date(2026, 1, 5)
        item = _create(
            admission,
            writer,
            details={"is_scheduled": True, "scheduled_date": past},
        )
        assert item.scheduled_date == past
        assert item.status == STATUS_ACTIVE
        assert item.finalized_at is None

    def test_only_treatment_end_is_accepted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_TREAT_END_ONLY")
        item = _create(
            admission,
            writer,
            slug="infeccioso-antifungicos",
            details={"treatment_end_date": START},
        )
        assert item.treatment_start_date is None
        assert item.treatment_end_date == START

    def test_clinical_sounding_names_create_plain_admin_items(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_RISK")
        item = _create(
            admission,
            writer,
            slug="quadro-risco-obito",
            description="acompanhamento sintetico",
        )
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        revision = _revision(item, 1)
        assert revision.action == "created"
        assert revision.description == "acompanhamento sintetico"
        admission.refresh_from_db()
        assert admission.discharge_date is None


class TestObservationRules:
    """PI-01: observation required only for generic catalog entries."""

    def test_defined_type_accepts_blank_observation(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_OBS_DEFINED")
        item = _create(
            admission,
            writer,
            slug="quadro-melhora-clinica",
            description="   ",
        )
        assert item.description == ""

    def test_generic_types_still_require_observation(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_OBS_GENERIC")
        with pytest.raises(ValidationError):
            _create(admission, writer, slug=OUTRO_SLUG, description="   ")
        with pytest.raises(ValidationError):
            _create(
                admission,
                writer,
                slug="regulacao-outros",
                description="  ",
            )
        assert PendingItem.objects.count() == 0


class TestClassificationCoherence:
    """PI-01/D3: category and type must correspond."""

    def test_category_mismatch_is_rejected(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_CAT_MISMATCH")
        wrong = PendingItemCategory.objects.get(slug="chd")
        with pytest.raises(ValidationError):
            _create(
                admission,
                writer,
                details={"is_scheduled": False},
                category=wrong,
            )
        assert PendingItem.objects.count() == 0

    def test_matching_category_is_accepted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_CAT_MATCH")
        matching = PendingItemCategory.objects.get(slug="exames-imagem")
        item = _create(
            admission,
            writer,
            details={"is_scheduled": False},
            category=matching,
        )
        assert item.item_type.category_id == matching.pk


class TestLocalConstraints:
    """D3: the database rejects invalid states written outside the form."""

    def _stored_type(self, slug: str = "imagem-tomografia") -> PendingItemType:
        return _type(slug)

    def _admission(self) -> Admission:
        return Admission.objects.create(
            patient=Patient.objects.create(
                patient_source_key="P_S2_DB", source_system="tasy", name="SINTETICO"
            ),
            source_system="tasy",
            source_admission_key="ADM_P_S2_DB",
            admission_date=_dt("2026-06-01T08:00:00"),
        )

    def test_item_rejects_date_without_yes(self, db: object) -> None:
        admission = self._admission()
        item_type = self._stored_type()
        for answer in (None, False):
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    PendingItem.objects.create(
                        admission=admission,
                        item_type=item_type,
                        description="",
                        is_scheduled=answer,
                        scheduled_date=START,
                    )

    def test_item_rejects_end_before_start(self, db: object) -> None:
        admission = self._admission()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PendingItem.objects.create(
                    admission=admission,
                    item_type=self._stored_type("infeccioso-antibioticos"),
                    description="",
                    treatment_start_date=END,
                    treatment_end_date=START,
                )

    def test_revision_rejects_invalid_details(self, db: object) -> None:
        admission = self._admission()
        item_type = self._stored_type()
        item = PendingItem.objects.create(
            admission=admission,
            item_type=item_type,
            description="",
            is_scheduled=False,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PendingItemRevision.objects.create(
                    item=item,
                    version=1,
                    action=ACTION_FINALIZED,
                    item_type=item_type,
                    type_name=item_type.name,
                    description="",
                    status=STATUS_ACTIVE,
                    scheduled_date=START,
                )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PendingItemRevision.objects.create(
                    item=item,
                    version=1,
                    action=ACTION_FINALIZED,
                    item_type=item_type,
                    type_name=item_type.name,
                    description="",
                    status=STATUS_ACTIVE,
                    treatment_start_date=END,
                    treatment_end_date=START,
                )

    def test_historical_unknowns_satisfy_local_constraints(
        self, db: object
    ) -> None:
        """Legacy rows keep every new value null and are still valid."""
        admission = self._admission()
        item_type = self._stored_type()
        item = PendingItem.objects.create(
            admission=admission,
            item_type=item_type,
            description="registro anterior",
        )
        revision = PendingItemRevision.objects.create(
            item=item,
            version=1,
            action=ACTION_FINALIZED,
            item_type=item_type,
            type_name=item_type.name,
            description="registro anterior",
            status=STATUS_ACTIVE,
        )
        item.full_clean()
        revision.full_clean()
        assert item.is_scheduled is None
        assert revision.is_scheduled is None


class TestDetailRevisions:
    """R2/PI-06: detail-only change versions; no-op does not."""

    def _rnm_item(self, writer: User, key: str = "P_S2_REV") -> PendingItem:
        admission = _make_eligible(writer, key)
        return _create(
            admission,
            writer,
            slug="imagem-rnm",
            details={"is_scheduled": True, "contrast": True},
        )

    def test_detail_only_change_creates_version(self, writer: User) -> None:
        item = self._rnm_item(writer)
        updated, changed = update_pending_item(
            item=item,
            item_type=item.item_type,
            description=item.description,
            details={"scheduled_date": START, "sedation": True},
            author=writer,
            expected_version=1,
        )
        assert changed is True
        assert updated.version == 2
        assert updated.scheduled_date == START
        assert updated.sedation is True
        assert updated.contrast is True
        revision = _revision(item, 2)
        assert revision.scheduled_date == START
        assert revision.contrast is True
        assert revision.sedation is True
        assert revision.is_scheduled is True

    def test_identical_resubmission_creates_no_version(
        self, writer: User
    ) -> None:
        item = self._rnm_item(writer)
        updated, changed = update_pending_item(
            item=item,
            item_type=item.item_type,
            description=item.description,
            details={
                "is_scheduled": True,
                "contrast": True,
                "scheduled_date": None,
            },
            author=writer,
            expected_version=1,
        )
        assert changed is False
        assert updated.version == 1
        assert PendingItemRevision.objects.filter(item=item).count() == 1

    def test_revision_failure_rolls_back_details(
        self, writer: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = self._rnm_item(writer, "P_S2_REV_ROLLBACK")

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic revision failure")

        monkeypatch.setattr(PendingItemRevision.objects, "create", _boom)
        with pytest.raises(RuntimeError):
            update_pending_item(
                item=item,
                item_type=item.item_type,
                description=item.description,
                details={"scheduled_date": START},
                author=writer,
                expected_version=1,
            )
        item.refresh_from_db()
        assert item.scheduled_date is None
        assert item.version == 1

    def test_omitted_field_preserves_stored_value(self, writer: User) -> None:
        item = self._rnm_item(writer, "P_S2_REV_OMIT")
        updated, changed = update_pending_item(
            item=item,
            item_type=item.item_type,
            description="observacao nova",
            details={},
            author=writer,
            expected_version=1,
        )
        assert changed is True
        assert updated.contrast is True
        assert updated.is_scheduled is True


class TestDetailRemoval:
    """R2/PI-09: detail removal needs explicit confirmation."""

    def _rnm_item(self, writer: User, key: str) -> PendingItem:
        admission = _make_eligible(writer, key)
        return _create(
            admission,
            writer,
            slug="imagem-rnm",
            details={
                "is_scheduled": True,
                "scheduled_date": START,
                "contrast": True,
                "sedation": False,
            },
        )

    def test_profile_change_with_details_requires_confirmation(
        self, writer: User
    ) -> None:
        item = self._rnm_item(writer, "P_S2_REMOVE_PROFILE")
        with pytest.raises(ValidationError):
            update_pending_item(
                item=item,
                item_type=_type("imagem-tomografia"),
                description=item.description,
                details={"is_scheduled": True, "scheduled_date": START},
                author=writer,
                expected_version=1,
            )
        item.refresh_from_db()
        assert item.item_type.slug == "imagem-rnm"
        assert item.contrast is True
        assert item.version == 1

    def test_confirmed_removal_clears_details_and_keeps_history(
        self, writer: User
    ) -> None:
        item = self._rnm_item(writer, "P_S2_REMOVE_CONFIRM")
        updated, changed = update_pending_item(
            item=item,
            item_type=_type("imagem-tomografia"),
            description=item.description,
            details={"is_scheduled": True, "scheduled_date": START},
            confirm_detail_removal=True,
            author=writer,
            expected_version=1,
        )
        assert changed is True
        assert updated.item_type.slug == "imagem-tomografia"
        assert updated.contrast is None
        assert updated.sedation is None
        previous = _revision(item, 1)
        assert previous.contrast is True
        assert previous.sedation is False
        assert previous.type_name == "RNM"

    def test_scheduled_no_with_stored_date_requires_confirmation(
        self, writer: User
    ) -> None:
        item = self._rnm_item(writer, "P_S2_REMOVE_SCHEDULE")
        with pytest.raises(ValidationError):
            update_pending_item(
                item=item,
                item_type=item.item_type,
                description=item.description,
                details={"is_scheduled": False},
                author=writer,
                expected_version=1,
            )
        item.refresh_from_db()
        assert item.scheduled_date == START
        assert item.is_scheduled is True

    def test_confirmed_scheduled_no_clears_only_the_date(
        self, writer: User
    ) -> None:
        item = self._rnm_item(writer, "P_S2_REMOVE_SCHEDULE_CONFIRM")
        updated, changed = update_pending_item(
            item=item,
            item_type=item.item_type,
            description=item.description,
            details={"is_scheduled": False},
            confirm_detail_removal=True,
            author=writer,
            expected_version=1,
        )
        assert changed is True
        assert updated.is_scheduled is False
        assert updated.scheduled_date is None
        assert updated.contrast is True
        assert _revision(item, 2).scheduled_date is None
        assert _revision(item, 1).scheduled_date == START


class TestFinalizationPreservesDetails:
    """PI-05/PI-07: finalization copies details without completing them."""

    def test_human_finalize_copies_details_without_validation(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_FINALIZE")
        legacy_type = _type("imagem-tomografia")
        item = PendingItem.objects.create(
            admission=admission,
            item_type=legacy_type,
            description="registro anterior",
            status=STATUS_ACTIVE,
            version=1,
        )
        finalized = finalize_pending_item(
            item=item,
            target_status=STATUS_CLOSED_UNRESOLVED,
            note="",
            author=writer,
            expected_version=1,
        )
        assert finalized.status == STATUS_CLOSED_UNRESOLVED
        revision = _revision(item, 2)
        assert revision.action == ACTION_FINALIZED
        assert revision.is_scheduled is None
        assert revision.profile == PROFILE_SCHEDULING

    def test_system_exit_copies_details(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_EXIT")
        item = _create(
            admission,
            writer,
            slug="infeccioso-antibioticos",
            details={
                "treatment_start_date": START,
                "treatment_end_date": END,
            },
        )
        Admission.objects.filter(pk=admission.pk).update(
            discharge_date=_dt("2026-06-20T10:00:00")
        )
        admission.refresh_from_db()
        with transaction.atomic():
            closed = close_pending_items_for_confirmed_exit(admission=admission)
        assert closed == 1
        item.refresh_from_db()
        revision = _revision(item, 2)
        assert revision.is_system is True
        assert revision.author_name == "Sistema"
        assert revision.treatment_start_date == START
        assert revision.treatment_end_date == END

    def test_signature_does_not_finalize_or_version(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_SIGNED_STATE")
        item = _create(
            admission,
            writer,
            slug="sumario-assinatura",
            details={"signature_at": SIGNED},
        )
        item.refresh_from_db()
        assert item.status == STATUS_ACTIVE
        assert item.version == 1
        assert item.finalized_at is None


class TestProfileFieldMapping:
    """D2/D3: only the approved profiles own the typed fields."""

    def test_profiles_are_the_four_approved_values(self) -> None:
        assert {
            PROFILE_SCHEDULING,
            PROFILE_TREATMENT,
            PROFILE_SIMPLE,
            PROFILE_SIGNATURE,
        } == {
            "agendamento",
            "tratamento-periodo",
            "registro-simples",
            "assinatura-documento",
        }

    def test_detail_rows_describe_applicable_fields(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_ROWS")
        item = _create(
            admission,
            writer,
            slug="imagem-rnm",
            details={"is_scheduled": True, "contrast": False},
        )
        rows = item.detail_rows
        labels = [row["label"] for row in rows]
        assert labels == [
            "Agendada",
            "Data agendada",
            "Contraste",
            "Sedação",
        ]
        values = {row["label"]: row["value"] for row in rows}
        assert values["Agendada"] == "Sim"
        assert values["Data agendada"] == "Data não informada"
        assert values["Contraste"] == "Não"
        assert values["Sedação"] == "Não informado"

    def test_not_applicable_fields_are_omitted(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_ROWS_SIMPLE")
        item = _create(
            admission,
            writer,
            slug="quadro-melhora-clinica",
            description="sintetica",
        )
        assert item.detail_rows == []

    def test_revision_rows_use_observed_metadata(
        self, writer: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_ROWS_REV")
        item = _create(
            admission,
            writer,
            slug="sumario-assinatura",
            details={"signature_at": SIGNED},
        )
        revision = _revision(item, 1)
        assert revision.details_known is True
        values = {row["label"]: row["value"] for row in revision.detail_rows}
        assert values["Assinatura do sumário em"] == "12/11/2026 09:30"

    def test_unknown_revision_reports_absence(self, writer: User) -> None:
        admission = _make_eligible(writer, "P_S2_ROWS_LEGACY")
        item = _create(
            admission,
            writer,
            slug="quadro-melhora-clinica",
            description="sintetica",
        )
        PendingItemRevision.objects.filter(item=item).update(
            profile=None, has_rnm_complements=None
        )
        revision = _revision(item, 1)
        assert revision.details_known is False
        assert revision.detail_rows == []


class TestConcurrencyAndAuthorization:
    """R5: details never bypass version or membership protection."""

    def test_stale_version_blocks_detail_write(self, writer: User, colleague: User) -> None:
        admission = _make_eligible(writer, "P_S2_CTX")
        item = _create(
            admission,
            writer,
            slug="imagem-rnm",
            details={"is_scheduled": True, "contrast": True},
        )
        update_pending_item(
            item=item,
            item_type=item.item_type,
            description="atualizada",
            details={"sedation": True},
            author=colleague,
            expected_version=1,
        )
        with pytest.raises(Exception) as exc:
            update_pending_item(
                item=item,
                item_type=item.item_type,
                description="envio antigo",
                details={"sedation": False},
                author=writer,
                expected_version=1,
            )
        assert type(exc.value).__name__ == "VersionConflictError"
        item.refresh_from_db()
        assert item.sedation is True
        assert item.version == 2

    def test_author_recorded_on_detail_revision(
        self, writer: User, colleague: User
    ) -> None:
        admission = _make_eligible(writer, "P_S2_AUTHOR")
        item = _create(
            admission,
            writer,
            slug="infeccioso-antibioticos",
            details={"treatment_start_date": START},
        )
        update_pending_item(
            item=item,
            item_type=item.item_type,
            description="",
            details={"treatment_end_date": END},
            author=colleague,
            expected_version=1,
        )
        revision = _revision(item, 2)
        assert revision.author_id == colleague.pk
        assert revision.created_at >= item.created_at - timedelta(seconds=1)
