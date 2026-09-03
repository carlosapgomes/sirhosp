"""Layered admission identity resolution (RPSA-S1).

Covers canonical admission resolution precedence (current key, alias, exact
start, unique Bahia local date), fail-closed ambiguity, alias persistence,
identical-period collapse and canonical versus unfiltered managers.

Also pins the fix-round regressions: patient-scoped key/alias lookups,
alias survival across legacy period consolidation, patient merge moving
merged rows, layer precedence tripwires and the Bahia local-date boundary.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.services import upsert_admission_snapshot
from apps.patients.models import Admission, Patient
from apps.patients.services import (
    MATCH_ALIAS,
    MATCH_CURRENT_KEY,
    MATCH_EXACT_START,
    merge_patients,
    resolve_admission_identity,
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
    start: str,
    end: str | None,
    *,
    ward: str = "",
    bed: str = "",
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=datetime.fromisoformat(start).replace(tzinfo=TZ_LOCAL),
        discharge_date=(
            datetime.fromisoformat(end).replace(tzinfo=TZ_LOCAL)
            if end
            else None
        ),
        ward=ward,
        bed=bed,
    )


def _item(key: str, start: str, end: str | None, ward="", bed=""):
    return {
        "admission_key": key,
        "admission_start": start,
        "admission_end": end,
        "ward": ward,
        "bed": bed,
    }


def _make_event(admission: Admission, suffix: str) -> ClinicalEvent:
    happened_at = admission.admission_date
    assert happened_at is not None
    return ClinicalEvent.objects.create(
        admission=admission,
        patient=admission.patient,
        event_identity_key=f"EVT-{admission.pk}-{suffix}",
        content_hash=f"hash-{admission.pk}-{suffix}",
        happened_at=happened_at,
        author_name="DR. TESTE",
        profession_type="medica",
        content_text=f"Evolucao sintetica {suffix}.",
        raw_payload_json={"source": "synthetic"},
    )


@pytest.mark.django_db
class TestAmbiguousPeriodFailsClosed:
    """Two same-day candidates must never be mutated or extended."""

    def test_two_same_day_candidates_fail_closed(self, db: object) -> None:
        patient = _make_patient("P_AMB1")
        open_row = _make_admission(
            patient, "ADM_AMB_OPEN", "2026-05-01T08:00:00", None, ward="UTI"
        )
        closed_row = _make_admission(
            patient,
            "ADM_AMB_CLOSED",
            "2026-05-01T14:00:00",
            "2026-05-03T18:00:00",
        )

        result = upsert_admission_snapshot(
            patient, [_item("ADM_AMB_NEW", "2026-05-01 09:00:00", None)]
        )

        assert result["ambiguous"] == 1
        assert result["created"] == 0
        assert result["updated"] == 0

        open_row.refresh_from_db()
        closed_row.refresh_from_db()
        assert open_row.discharge_date is None
        assert open_row.ward == "UTI"
        assert closed_row.discharge_date is not None
        assert Admission.objects.filter(patient=patient).count() == 2


@pytest.mark.django_db
class TestAliasPersistence:
    """Observed external keys are preserved as canonical admission aliases."""

    def test_reused_episode_persists_new_key_as_alias(self, db: object) -> None:
        patient = _make_patient("P_ALIAS1")
        original = _make_admission(
            patient, "ADM_AL1_A", "2026-05-01T08:00:00", "2026-05-10T18:00:00"
        )

        result = upsert_admission_snapshot(
            patient,
            [_item("ADM_AL1_B", "2026-05-01 08:00:00", "2026-05-10 18:00:00")],
        )

        assert result["created"] == 0
        assert Admission.objects.filter(patient=patient).count() == 1

        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        alias = alias_model.objects.get(
            source_system="tasy", alias_key="ADM_AL1_B"
        )
        assert alias.admission_id == original.pk

    def test_alias_is_reused_idempotently(self, db: object) -> None:
        patient = _make_patient("P_ALIAS2")
        _make_admission(
            patient, "ADM_AL2_A", "2026-05-01T08:00:00", "2026-05-10T18:00:00"
        )
        upsert_admission_snapshot(
            patient,
            [_item("ADM_AL2_B", "2026-05-01 08:00:00", "2026-05-10 18:00:00")],
        )
        result = upsert_admission_snapshot(
            patient,
            [_item("ADM_AL2_B", "2026-05-01 08:00:00", "2026-05-10 18:00:00")],
        )

        assert result["created"] == 0
        assert result["ambiguous"] == 0
        assert Admission.objects.filter(patient=patient).count() == 1
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        assert (
            alias_model.objects.filter(alias_key="ADM_AL2_B").count() == 1
        )

    def test_created_admission_stores_its_key_as_alias(self, db: object) -> None:
        patient = _make_patient("P_ALIAS3")
        result = upsert_admission_snapshot(
            patient, [_item("ADM_AL3_NEW", "2026-06-01 08:00:00", None)]
        )

        assert result["created"] == 1
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        alias = alias_model.objects.get(alias_key="ADM_AL3_NEW")
        admission = Admission.objects.get(
            source_admission_key="ADM_AL3_NEW"
        )
        assert alias.admission_id == admission.pk

    def test_alias_match_keeps_non_empty_ward(self, db: object) -> None:
        patient = _make_patient("P_ALIAS4")
        _make_admission(
            patient,
            "ADM_AL4_A",
            "2026-05-01T08:00:00",
            "2026-05-10T18:00:00",
            ward="UTI Adulto",
            bed="UTI-10",
        )
        upsert_admission_snapshot(
            patient,
            [_item("ADM_AL4_B", "2026-05-01 08:00:00", "2026-05-10 18:00:00")],
        )
        # Alias reuse with empty ward/bed must not overwrite persisted values.
        upsert_admission_snapshot(
            patient, [_item("ADM_AL4_B", "2026-05-01 08:00:00", "2026-05-10 18:00:00")]
        )
        admission = Admission.objects.get(patient=patient)
        assert admission.ward == "UTI Adulto"
        assert admission.bed == "UTI-10"


@pytest.mark.django_db
class TestCanonicalManagerSemantics:
    """Merged rows stay available for audit but leave clinical listings."""

    def test_default_manager_hides_merged_row(self, db: object) -> None:
        patient = _make_patient("P_CANON1")
        canonical = _make_admission(
            patient, "ADM_CAN_A", "2026-05-01T08:00:00", None
        )
        merged = _make_admission(
            patient, "ADM_CAN_B", "2026-05-02T08:00:00", None
        )
        merged.merged_into = canonical
        merged.save()

        assert Admission.objects.filter(patient=patient).count() == 1
        assert (
            Admission.objects.filter(patient=patient).get().pk == canonical.pk
        )
        assert Admission.all_objects.filter(patient=patient).count() == 2


@pytest.mark.django_db
class TestIdenticalPeriodCollapse:
    """Rows duplicating one identical episode resolve to a single episode."""

    def test_identical_periods_reuse_one_episode(self, db: object) -> None:
        patient = _make_patient("P_COLL1")
        first = _make_admission(
            patient,
            "ADM_COLL_A",
            "2026-04-01T08:00:00",
            "2026-04-10T18:00:00",
        )
        _make_admission(
            patient,
            "ADM_COLL_B",
            "2026-04-01T08:00:00",
            "2026-04-10T18:00:00",
        )

        result = upsert_admission_snapshot(
            patient,
            [_item("ADM_COLL_NEW", "2026-04-01 08:00:00", "2026-04-10 18:00:00")],
        )

        assert result["created"] == 0
        assert result["ambiguous"] == 0
        assert Admission.objects.filter(patient=patient).count() == 1
        assert Admission.objects.get(patient=patient).pk == first.pk


@pytest.mark.django_db
class TestClosedSnapshotClosesOpenEpisode:
    """A changed key with an end datetime closes the one compatible episode."""

    def test_changed_key_closes_unique_open_episode(self, db: object) -> None:
        patient = _make_patient("P_CLOSE1")
        original = _make_admission(
            patient, "ADM_CLS_A", "2026-05-01T08:00:00", None
        )

        result = upsert_admission_snapshot(
            patient,
            [_item("ADM_CLS_B", "2026-05-01 08:00:00", "2026-05-06 18:00:00")],
        )

        assert result["created"] == 0
        assert Admission.objects.filter(patient=patient).count() == 1
        original.refresh_from_db()
        assert original.discharge_date is not None
        assert original.source_admission_key == "ADM_CLS_A"


@pytest.mark.django_db
class TestCrossPatientIsolation:
    """Key/alias lookups are patient-scoped signals, never global identity."""

    def test_cross_patient_current_key_does_not_match(self, db: object) -> None:
        patient_a = _make_patient("P_XP_A")
        admission_a = _make_admission(
            patient_a, "ADM_XP_A", "2026-05-01T08:00:00", "2026-05-05T18:00:00"
        )
        patient_b = _make_patient("P_XP_B")
        admission_b = _make_admission(
            patient_b, "ADM_XP_B", "2026-05-01T10:00:00", None
        )

        result = upsert_admission_snapshot(
            patient_b,
            [
                _item(
                    "ADM_XP_A",
                    "2026-05-01 10:00:00",
                    "2026-05-07 18:00:00",
                    ward="ENFERMARIA",
                )
            ],
        )

        assert result["created"] == 0
        assert result["updated"] == 1
        assert result["ambiguous"] == 0

        admission_a.refresh_from_db()
        assert admission_a.patient_id == patient_a.pk
        assert admission_a.admission_date == datetime.fromisoformat(
            "2026-05-01T08:00:00"
        ).replace(tzinfo=TZ_LOCAL)
        assert admission_a.discharge_date == datetime.fromisoformat(
            "2026-05-05T18:00:00"
        ).replace(tzinfo=TZ_LOCAL)
        assert admission_a.ward == ""

        admission_b.refresh_from_db()
        assert admission_b.discharge_date == datetime.fromisoformat(
            "2026-05-07T18:00:00"
        ).replace(tzinfo=TZ_LOCAL)
        assert admission_b.ward == "ENFERMARIA"

    def test_cross_patient_alias_does_not_match(self, db: object) -> None:
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        patient_a = _make_patient("P_XP_C")
        admission_a = _make_admission(
            patient_a, "ADM_XP_C", "2026-05-01T08:00:00", "2026-05-05T18:00:00"
        )
        alias_model.objects.create(
            admission=admission_a,
            source_system="tasy",
            alias_key="ADM_XP_C_OLD",
        )
        patient_b = _make_patient("P_XP_D")
        admission_b = _make_admission(
            patient_b, "ADM_XP_D", "2026-05-01T12:00:00", None
        )

        result = upsert_admission_snapshot(
            patient_b,
            [_item("ADM_XP_C_OLD", "2026-05-01 12:00:00", None)],
        )

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["ambiguous"] == 0

        admission_a.refresh_from_db()
        assert admission_a.patient_id == patient_a.pk
        assert admission_a.admission_date == datetime.fromisoformat(
            "2026-05-01T08:00:00"
        ).replace(tzinfo=TZ_LOCAL)
        assert (
            alias_model.objects.get(
                alias_key="ADM_XP_C_OLD"
            ).admission_id
            == admission_a.pk
        )
        admission_b.refresh_from_db()
        assert admission_b.discharge_date is None


@pytest.mark.django_db
class TestConsolidationPreservesAliases:
    """Legacy consolidation must not destroy the resolver's identity signals."""

    def test_alias_survives_consolidation_disagreement(self, db: object) -> None:
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        patient = _make_patient("P_CONS1")
        _make_admission(
            patient, "ADM_CONS_OLD", "2026-05-01T08:00:00", "2026-05-05T18:00:00"
        )
        newer = _make_admission(
            patient, "ADM_CONS_NEW", "2026-05-01T09:00:00", "2026-05-05T18:00:00"
        )
        _make_event(newer, "a")
        _make_event(newer, "b")

        result = upsert_admission_snapshot(
            patient,
            [
                _item(
                    "ADM_CONS_NEWEST",
                    "2026-05-01 08:00:00",
                    "2026-05-05 18:00:00",
                )
            ],
        )

        assert result["created"] == 0
        assert result["ambiguous"] == 0
        assert Admission.objects.filter(patient=patient).count() == 1
        assert Admission.objects.get(patient=patient).pk == newer.pk

        newest_alias = alias_model.objects.filter(
            alias_key="ADM_CONS_NEWEST"
        ).first()
        assert newest_alias is not None
        assert newest_alias.admission_id == newer.pk

        oldest_key_alias = alias_model.objects.filter(
            alias_key="ADM_CONS_OLD"
        ).first()
        assert oldest_key_alias is not None
        assert oldest_key_alias.admission_id == newer.pk


@pytest.mark.django_db
class TestPatientMergeMovesMergedRows:
    """Patient merge must move admissions even when merged_into is set."""

    def test_merge_moves_admission_with_merged_into_set(self, db: object) -> None:
        keep = _make_patient("P_MRG_KEEP")
        merge = _make_patient("P_MRG_MERGE")
        canonical = _make_admission(
            keep, "ADM_MRG_KEEP1", "2026-05-01T08:00:00", None
        )
        merged = _make_admission(
            merge, "ADM_MRG_MERGE1", "2026-05-02T08:00:00", None
        )
        merged.merged_into = canonical
        merged.save()

        result = merge_patients(keep=keep, merge=merge)

        moved = Admission.all_objects.filter(pk=merged.pk).first()
        assert moved is not None, (
            "admission with merged_into must survive patient merge"
        )
        assert moved.patient_id == keep.pk
        assert moved.merged_into_id == canonical.pk
        assert result["admissions_moved"] == 1
        assert not Patient.objects.filter(pk=merge.pk).exists()
        assert Admission.all_objects.filter(pk=canonical.pk).exists()


@pytest.mark.django_db
class TestResolverPrecedence:
    """Tripwires: reordering the resolver layers must break these tests."""

    def test_current_key_beats_alias(self, db: object) -> None:
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        patient = _make_patient("P_PREC_A")
        current = _make_admission(
            patient, "ADM_PREC_KEY", "2026-05-01T08:00:00", "2026-05-05T18:00:00"
        )
        other = _make_admission(
            patient, "ADM_PREC_OTHER", "2026-06-01T08:00:00", None
        )
        alias_model.objects.create(
            admission=other, source_system="tasy", alias_key="ADM_PREC_KEY"
        )

        match = resolve_admission_identity(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_PREC_KEY",
            admission_start=None,
            admission_end=None,
        )

        assert match.ambiguous is False
        assert match.match_reason == MATCH_CURRENT_KEY
        assert match.admission is not None
        assert match.admission.pk == current.pk
        assert match.admission.pk != other.pk

    def test_alias_beats_exact_start(self, db: object) -> None:
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        patient = _make_patient("P_PREC_B")
        older = _make_admission(
            patient, "ADM_PREC_OLD", "2026-05-01T08:00:00", "2026-05-05T18:00:00"
        )
        aliased = _make_admission(
            patient,
            "ADM_PREC_ALIASED",
            "2026-05-01T08:00:00",
            "2026-05-05T18:00:00",
        )
        alias_model.objects.create(
            admission=aliased, source_system="tasy", alias_key="ADM_PREC_HIST"
        )

        match = resolve_admission_identity(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_PREC_HIST",
            admission_start=aliased.admission_date,
            admission_end=aliased.discharge_date,
        )

        assert match.ambiguous is False
        assert match.match_reason == MATCH_ALIAS
        assert match.admission is not None
        assert match.admission.pk == aliased.pk
        assert match.admission.pk != older.pk

    def test_exact_start_beats_unique_local_date(self, db: object) -> None:
        patient = _make_patient("P_PREC_C")
        morning = _make_admission(
            patient, "ADM_PREC_MORNING", "2026-05-01T08:00:00", None
        )
        afternoon = _make_admission(
            patient, "ADM_PREC_AFTERNOON", "2026-05-01T14:00:00", None
        )

        match = resolve_admission_identity(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_PREC_UNKNOWN",
            admission_start=morning.admission_date,
            admission_end=None,
        )

        assert match.ambiguous is False
        assert match.match_reason == MATCH_EXACT_START
        assert match.admission is not None
        assert match.admission.pk == morning.pk
        assert match.admission.pk != afternoon.pk


@pytest.mark.django_db
class TestLocalDateBoundary:
    """Level-4 local-date matching must respect the America/Bahia day edge."""

    def test_midnight_snapshot_matches_same_bahia_local_date(
        self, db: object
    ) -> None:
        alias_model = apps.get_model("patients", "AdmissionSourceAlias")
        patient = _make_patient("P_TZ1")
        late_night = _make_admission(
            patient, "ADM_TZ_LATE", "2026-05-01T23:30:00", None
        )
        early_morning = _make_admission(
            patient, "ADM_TZ_EARLY", "2026-05-02T00:30:00", None
        )

        result = upsert_admission_snapshot(
            patient,
            [_item("ADM_TZ_NEW", "2026-05-02", None)],
        )

        assert result["ambiguous"] == 0
        assert result["created"] == 0
        new_alias = alias_model.objects.filter(alias_key="ADM_TZ_NEW").first()
        assert new_alias is not None
        assert new_alias.admission_id == early_morning.pk
        assert new_alias.admission_id != late_night.pk
        late_night.refresh_from_db()
        assert late_night.admission_date == datetime.fromisoformat(
            "2026-05-01T23:30:00"
        ).replace(tzinfo=TZ_LOCAL)
