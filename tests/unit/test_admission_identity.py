"""Layered admission identity resolution (RPSA-S1).

Covers canonical admission resolution precedence (current key, alias, exact
start, unique Bahia local date), fail-closed ambiguity, alias persistence,
identical-period collapse and canonical versus unfiltered managers.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps

from apps.ingestion.services import upsert_admission_snapshot
from apps.patients.models import Admission, Patient

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
