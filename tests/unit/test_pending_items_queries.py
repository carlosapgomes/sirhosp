"""PEND-S3: aggregate resolver, filters, first unit and indicators.

Covers R1 (single conservative cut, equivalent repetitions, ambiguous
exclusions), R2 (combinable filters before grouping, exact open time),
R3 (episode first unit) and R5 (hospital indicators on the same cut).

Failing-before: ``apps/pending_items/queries.py`` does not exist yet and
``/pendencias/`` is unresolvable, so importing this module fails until
the slice is implemented. All fixtures are synthetic.

Time control: query functions receive an explicit ``now``; item
timestamps are rewritten deterministically after creation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext

from apps.census.models import (
    BedStatus,
    CensusSnapshot,
    PatientMovement,
    Specialty,
)
from apps.patients.models import Admission, Patient
from apps.pending_items.models import (
    OUTRO_SLUG,
    STATUS_ACTIVE,
    STATUS_CLOSED_UNRESOLVED,
    STATUS_RESOLVED,
    PendingItem,
    PendingItemType,
)
from apps.pending_items.queries import (
    FIRST_UNIT_UNKNOWN,
    AggregateFilters,
    aggregate_options,
    apply_aggregate_filters,
    apply_time_bounds,
    base_current_items,
    group_by_patient,
    hospital_indicators,
    open_duration,
    parse_aggregate_filters,
    resolve_current_cut,
    resolve_first_units,
    resolve_specialty,
    sort_aggregate_items,
    sort_patient_groups,
    specialty_labels,
)

TZ = ZoneInfo("America/Bahia")
NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=TZ)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _params(query: str = "") -> QueryDict:
    return QueryDict(query)


def _make_patient(key: str, source_system: str = "tasy") -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system=source_system,
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
    especialidade: str = "",
    captured_at: str = "2026-06-10T08:00:00",
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=_dt(captured_at),
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome="PACIENTE SINTETICO",
        especialidade=especialidade,
        bed_status=BedStatus.OCCUPIED,
    )


def _outro() -> PendingItemType:
    return PendingItemType.objects.get(slug=OUTRO_SLUG)


def _make_user(username: str) -> User:
    return User.objects.create_user(username=username, password="x")


def _make_item(
    admission: Admission,
    *,
    description: str = "pendencia sintetica",
    status: str = STATUS_ACTIVE,
    item_type: PendingItemType | None = None,
    created_by: User | None = None,
    updated_by: User | None = None,
    is_system_updated: bool = False,
    created_at: datetime | None = None,
    finalized_at: datetime | None = None,
) -> PendingItem:
    item = PendingItem.objects.create(
        admission=admission,
        item_type=item_type or _outro(),
        description=description,
        status=status,
        version=1,
        finalized_at=finalized_at,
        created_by=created_by,
        created_by_name=created_by.username if created_by else "",
        updated_by=updated_by,
        updated_by_name=(
            "Sistema"
            if is_system_updated
            else (updated_by.username if updated_by else "")
        ),
        is_system_updated=is_system_updated,
    )
    if created_at is not None:
        PendingItem.objects.filter(pk=item.pk).update(created_at=created_at)
        item.refresh_from_db()
    return item


def _make_movement(
    patient: Patient,
    *,
    admission: Admission | None,
    sector: str,
    movement_date: str,
    sequence: int = 0,
) -> PatientMovement:
    day = datetime.strptime(movement_date, "%Y-%m-%d").date()
    return PatientMovement.objects.create(
        patient=patient,
        admission=admission,
        movement_date=day,
        sector=sector,
        sequence=sequence,
        first_seen_at=_dt("2026-06-01T08:00:00"),
        last_seen_at=_dt("2026-06-01T08:00:00"),
    )


def _filtered_descriptions(
    query: str = "", *, now: datetime = NOW
) -> list[str]:
    """Descriptions surviving the full pre-grouping pipeline."""
    cut = resolve_current_cut()
    filters, error = parse_aggregate_filters(_params(query))
    assert error is None
    items = apply_time_bounds(
        list(apply_aggregate_filters(base_current_items(cut), cut, filters)),
        filters,
        now,
    )
    return sorted(item.description for item in items)


@pytest.mark.django_db
class TestResolveCurrentCut:
    def test_no_census_returns_empty_cut(self, db: object) -> None:
        cut = resolve_current_cut()
        assert cut.captured_at is None
        assert cut.occupations == {}
        assert list(base_current_items(cut)) == []

    def test_single_valid_patient_maps_to_open_admission(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_CUT1")
        admission = _make_admission(patient, "ADM_Q_CUT1")
        _make_census_row(
            "P_Q_CUT1", setor="UTI", leito="U01", especialidade="CIV"
        )
        cut = resolve_current_cut()
        assert cut.captured_at == _dt("2026-06-10T08:00:00")
        assert list(cut.occupations) == [admission.pk]
        occ = cut.occupations[admission.pk]
        assert occ.patient_id == patient.pk
        assert occ.prontuario == "P_Q_CUT1"
        assert occ.patient_name == patient.name
        assert occ.setor == "UTI"
        assert occ.leito == "U01"
        assert occ.especialidade == "CIV"

    def test_equivalent_repetition_counts_once(self, db: object) -> None:
        patient = _make_patient("P_Q_CUT2")
        admission = _make_admission(patient, "ADM_Q_CUT2")
        _make_census_row("P_Q_CUT2", setor="UTI", leito="U01")
        _make_census_row("P_Q_CUT2", setor="UTI", leito="U01")
        _make_item(admission, description="unica")
        cut = resolve_current_cut()
        assert list(cut.occupations) == [admission.pk]
        assert _filtered_descriptions() == ["unica"]

    def test_conflicting_beds_are_excluded(self, db: object) -> None:
        patient = _make_patient("P_Q_CUT3")
        admission = _make_admission(patient, "ADM_Q_CUT3")
        _make_census_row("P_Q_CUT3", setor="UTI", leito="U01")
        _make_census_row("P_Q_CUT3", setor="ENFERMARIA", leito="E02")
        _make_item(admission, description="conflitante")
        cut = resolve_current_cut()
        assert cut.occupations == {}
        assert _filtered_descriptions() == []

    def test_ambiguous_identity_is_excluded(self, db: object) -> None:
        patient = _make_patient("P_Q_CUT4")
        _make_patient("P_Q_CUT4", source_system="legacy")
        admission = _make_admission(patient, "ADM_Q_CUT4")
        _make_census_row("P_Q_CUT4")
        _make_item(admission, description="identidade ambigua")
        assert resolve_current_cut().occupations == {}
        assert _filtered_descriptions() == []

    def test_two_open_admissions_are_excluded(self, db: object) -> None:
        patient = _make_patient("P_Q_CUT5")
        first = _make_admission(patient, "ADM_Q_CUT5_A")
        _make_admission(patient, "ADM_Q_CUT5_B")
        _make_census_row("P_Q_CUT5")
        _make_item(first, description="duas abertas")
        assert resolve_current_cut().occupations == {}
        assert _filtered_descriptions() == []

    def test_residual_presence_after_confirmed_exit_is_excluded(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_CUT6")
        admission = _make_admission(
            patient, "ADM_Q_CUT6", end="2026-06-09T10:00:00"
        )
        _make_census_row("P_Q_CUT6")
        _make_item(admission, description="residual")
        assert resolve_current_cut().occupations == {}
        assert _filtered_descriptions() == []

    def test_previous_episode_items_never_enter(self, db: object) -> None:
        patient = _make_patient("P_Q_CUT7")
        current = _make_admission(patient, "ADM_Q_CUT7_NEW")
        old = _make_admission(
            patient, "ADM_Q_CUT7_OLD", end="2026-05-02T10:00:00"
        )
        _make_census_row("P_Q_CUT7")
        _make_item(current, description="episodio atual")
        _make_item(old, description="episodio antigo")
        assert _filtered_descriptions() == ["episodio atual"]
        assert _filtered_descriptions("status=all") == ["episodio atual"]

    def test_older_photo_and_vacant_rows_are_ignored(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_CUT8")
        admission = _make_admission(patient, "ADM_Q_CUT8")
        _make_census_row("P_Q_CUT8", captured_at="2026-06-09T08:00:00")
        _make_census_row(
            "OUTRO_SINTETICO", setor="UTI", leito="U09",
            captured_at="2026-06-10T08:00:00",
        )
        CensusSnapshot.objects.create(
            captured_at=_dt("2026-06-10T08:00:00"),
            setor="CLINICA MEDICA",
            leito="L99",
            prontuario="P_Q_CUT8",
            nome="DESOCUPADO",
            bed_status=BedStatus.EMPTY,
        )
        _make_item(admission, description="fora da foto atual")
        cut = resolve_current_cut()
        assert cut.captured_at == _dt("2026-06-10T08:00:00")
        assert cut.occupations == {}
        assert _filtered_descriptions() == []

    def test_merged_admission_is_hidden(self, db: object) -> None:
        patient = _make_patient("P_Q_CUT9")
        canonical = _make_admission(patient, "ADM_Q_CUT9_CAN")
        duplicate = _make_admission(patient, "ADM_Q_CUT9_DUP")
        duplicate.merged_into = canonical
        duplicate.save(update_fields=["merged_into"])
        canonical.discharge_date = _dt("2026-06-09T10:00:00")
        canonical.save(update_fields=["discharge_date"])
        _make_census_row("P_Q_CUT9")
        _make_item(canonical, description="unificada fechada")
        assert resolve_current_cut().occupations == {}


@pytest.mark.django_db
class TestAggregateFilters:
    def _two_patient_scene(self) -> tuple[User, User]:
        author = _make_user("q_author")
        other = _make_user("q_other")
        first = _make_patient("P_Q_F1")
        adm_first = _make_admission(first, "ADM_Q_F1")
        _make_census_row("P_Q_F1", setor="UTI", leito="U01")
        second = _make_patient("P_Q_F2")
        adm_second = _make_admission(second, "ADM_Q_F2")
        _make_census_row("P_Q_F2", setor="ENFERMARIA", leito="E02")
        _make_item(
            adm_first, description="alvo", created_by=author,
            updated_by=author,
        )
        _make_item(
            adm_first, description="outro criador", created_by=other,
            updated_by=other,
        )
        _make_item(
            adm_second, description="outro setor", created_by=author,
            updated_by=author,
        )
        return author, other

    def test_default_status_is_active(self, db: object) -> None:
        patient = _make_patient("P_Q_F3")
        admission = _make_admission(patient, "ADM_Q_F3")
        _make_census_row("P_Q_F3")
        _make_item(admission, description="ativa")
        _make_item(
            admission, description="resolvida", status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        _make_item(
            admission, description="encerrada",
            status=STATUS_CLOSED_UNRESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        filters, error = parse_aggregate_filters(_params(""))
        assert error is None
        assert filters.status == STATUS_ACTIVE
        assert _filtered_descriptions() == ["ativa"]
        assert _filtered_descriptions("status=resolved") == ["resolvida"]
        assert _filtered_descriptions("status=closed_unresolved") == [
            "encerrada"
        ]
        assert _filtered_descriptions("status=all") == [
            "ativa", "encerrada", "resolvida",
        ]

    def test_combined_filters_apply_before_grouping(
        self, db: object
    ) -> None:
        author, _other = self._two_patient_scene()
        extra_type = PendingItemType.objects.create(
            slug="q-extra", name="Extra Sintetico",
        )
        patient = Patient.objects.get(patient_source_key="P_Q_F1")
        admission = Admission.objects.get(
            patient=patient, discharge_date__isnull=True
        )
        _make_item(
            admission, description="tipo diferente", item_type=extra_type,
            created_by=author, updated_by=author,
        )
        query = (
            f"status=active&unidade=UTI&tipo={_outro().pk}"
            f"&criador={author.pk}"
        )
        assert _filtered_descriptions(query) == ["alvo"]
        cut = resolve_current_cut()
        filters, error = parse_aggregate_filters(_params(query))
        assert error is None
        items = list(
            apply_aggregate_filters(base_current_items(cut), cut, filters)
        )
        assert {item.description for item in items} == {"alvo"}
        groups = group_by_patient(items, cut)
        assert len(groups) == 1
        assert groups[0].occupation.prontuario == "P_Q_F1"
        assert [item.description for item in groups[0].items] == ["alvo"]

    def test_creator_and_updater_are_independent(
        self, db: object
    ) -> None:
        author, other = self._two_patient_scene()
        assert _filtered_descriptions(f"criador={author.pk}") == [
            "alvo", "outro setor",
        ]
        assert _filtered_descriptions(f"atualizador={other.pk}") == [
            "outro criador",
        ]
        assert _filtered_descriptions(
            f"criador={other.pk}&atualizador={other.pk}"
        ) == ["outro criador"]

    def test_system_updater_option(self, db: object) -> None:
        author, _other = self._two_patient_scene()
        patient = Patient.objects.get(patient_source_key="P_Q_F1")
        admission = Admission.objects.get(
            patient=patient, discharge_date__isnull=True
        )
        _make_item(
            admission, description="encerrada pelo sistema",
            status=STATUS_CLOSED_UNRESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
            created_by=author, is_system_updated=True,
        )
        assert _filtered_descriptions(
            "status=all&atualizador=system"
        ) == ["encerrada pelo sistema"]
        assert _filtered_descriptions(
            f"status=all&atualizador={author.pk}"
        ) == ["alvo", "outro setor"]

    def test_open_time_active_until_now_finalized_until_transition(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_F4")
        admission = _make_admission(patient, "ADM_Q_F4")
        _make_census_row("P_Q_F4")
        active = _make_item(
            admission, description="ativa dez dias",
            created_at=NOW - timedelta(days=10),
        )
        finalized = _make_item(
            admission, description="finalizada sete dias",
            status=STATUS_RESOLVED,
            created_at=NOW - timedelta(days=10),
            finalized_at=NOW - timedelta(days=3),
        )
        assert open_duration(active, NOW) == timedelta(days=10)
        assert open_duration(finalized, NOW) == timedelta(days=7)

    def test_time_bounds_compare_exactly_without_rounding(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_F5")
        admission = _make_admission(patient, "ADM_Q_F5")
        _make_census_row("P_Q_F5")
        _make_item(
            admission, description="quase dois dias",
            created_at=NOW - timedelta(days=1, hours=21, minutes=36),
        )
        assert _filtered_descriptions("min_dias=2") == []
        assert _filtered_descriptions("max_dias=2") == ["quase dois dias"]
        assert _filtered_descriptions("min_dias=1&max_dias=2") == [
            "quase dois dias"
        ]

    def test_time_bounds_use_finalized_transition(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_F6")
        admission = _make_admission(patient, "ADM_Q_F6")
        _make_census_row("P_Q_F6")
        _make_item(
            admission, description="sete dias exatos",
            status=STATUS_RESOLVED,
            created_at=NOW - timedelta(days=10),
            finalized_at=NOW - timedelta(days=3),
        )
        assert _filtered_descriptions(
            "status=all&min_dias=8"
        ) == []
        assert _filtered_descriptions(
            "status=all&max_dias=7"
        ) == ["sete dias exatos"]

    def test_negative_bound_is_rejected(self, db: object) -> None:
        _filters, error = parse_aggregate_filters(_params("min_dias=-1"))
        assert error is not None
        assert "negativ" in error

    def test_non_numeric_bound_is_rejected(self, db: object) -> None:
        _filters, error = parse_aggregate_filters(_params("max_dias=abc"))
        assert error is not None

    def test_inverted_bounds_are_rejected(self, db: object) -> None:
        _filters, error = parse_aggregate_filters(
            _params("min_dias=5&max_dias=2")
        )
        assert error is not None
        assert "nimo" in error and "ximo" in error

    def test_unparseable_id_filter_voids_result(self, db: object) -> None:
        patient = _make_patient("P_Q_F7")
        admission = _make_admission(patient, "ADM_Q_F7")
        _make_census_row("P_Q_F7")
        _make_item(admission, description="visivel")
        assert _filtered_descriptions() == ["visivel"]
        assert _filtered_descriptions("tipo=abc") == []
        assert _filtered_descriptions("criador=xyz") == []
        assert _filtered_descriptions("atualizador=??") == []

    def test_unknown_view_status_ordering_fall_back(
        self, db: object
    ) -> None:
        filters, error = parse_aggregate_filters(
            _params("view=bogus&status=bogus&ordenar=bogus")
        )
        assert error is None
        assert filters.view == "patients"
        assert filters.status == STATUS_ACTIVE
        assert filters.ordering == ""
        assert isinstance(filters, AggregateFilters)


@pytest.mark.django_db
class TestFirstUnit:
    def test_fk_movement_inside_interval_is_first(self, db: object) -> None:
        patient = _make_patient("P_Q_U1")
        admission = _make_admission(patient, "ADM_Q_U1")
        _make_movement(
            patient, admission=admission, sector="UTI GERAL",
            movement_date="2026-06-02",
        )
        _make_movement(
            patient, admission=admission, sector="ENFERMARIA 1",
            movement_date="2026-06-05",
        )
        assert resolve_first_units([admission.pk]) == {
            admission.pk: "UTI GERAL"
        }

    def test_fk_movement_outside_interval_is_ignored(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U2")
        admission = _make_admission(patient, "ADM_Q_U2")
        _make_movement(
            patient, admission=admission, sector="SETOR ANTIGO",
            movement_date="2026-05-01",
        )
        assert resolve_first_units([admission.pk]) == {
            admission.pk: FIRST_UNIT_UNKNOWN
        }

    def test_fk_less_movement_with_unique_interval_is_used(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U3")
        current = _make_admission(patient, "ADM_Q_U3_NEW")
        _make_admission(
            patient, "ADM_Q_U3_OLD", start="2026-04-01T08:00:00",
            end="2026-04-10T10:00:00",
        )
        _make_movement(
            patient, admission=None, sector="CLINICA MEDICA",
            movement_date="2026-06-03",
        )
        assert resolve_first_units([current.pk]) == {
            current.pk: "CLINICA MEDICA"
        }

    def test_overlapping_episodes_leave_fk_less_unknown(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U4")
        current = _make_admission(
            patient, "ADM_Q_U4_NEW", start="2026-06-05T08:00:00"
        )
        _make_admission(
            patient, "ADM_Q_U4_OLD", start="2026-06-01T08:00:00",
            end="2026-06-10T10:00:00",
        )
        _make_movement(
            patient, admission=None, sector="AMBIGUO",
            movement_date="2026-06-07",
        )
        assert resolve_first_units([current.pk]) == {
            current.pk: FIRST_UNIT_UNKNOWN
        }

    def test_same_day_readmission_leaves_fk_less_unknown(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U5")
        current = _make_admission(
            patient, "ADM_Q_U5_NEW", start="2026-06-10T15:00:00"
        )
        _make_admission(
            patient, "ADM_Q_U5_OLD", start="2026-06-01T08:00:00",
            end="2026-06-10T10:00:00",
        )
        _make_movement(
            patient, admission=None, sector="MESMO DIA",
            movement_date="2026-06-10",
        )
        assert resolve_first_units([current.pk]) == {
            current.pk: FIRST_UNIT_UNKNOWN
        }

    def test_pronto_socorro_is_first_when_earliest(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U6")
        admission = _make_admission(patient, "ADM_Q_U6")
        _make_movement(
            patient, admission=None, sector="PRONTO SOCORRO",
            movement_date="2026-06-01",
        )
        _make_movement(
            patient, admission=None, sector="UTI GERAL",
            movement_date="2026-06-03",
        )
        _make_movement(
            patient, admission=None, sector="ENFERMARIA 1",
            movement_date="2026-06-05",
        )
        assert resolve_first_units([admission.pk]) == {
            admission.pk: "PRONTO SOCORRO"
        }

    def test_previous_episode_fk_is_never_reused(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U7")
        current = _make_admission(patient, "ADM_Q_U7_NEW")
        old = _make_admission(
            patient, "ADM_Q_U7_OLD", start="2026-04-01T08:00:00",
            end="2026-04-10T10:00:00",
        )
        _make_movement(
            patient, admission=old, sector="SETOR ANTIGO",
            movement_date="2026-04-02",
        )
        assert resolve_first_units([current.pk]) == {
            current.pk: FIRST_UNIT_UNKNOWN
        }

    def test_missing_bounds_are_not_guessed(self, db: object) -> None:
        patient = _make_patient("P_Q_U8")
        admission = _make_admission(patient, "ADM_Q_U8", start=None)
        _make_movement(
            patient, admission=None, sector="SEM LIMITES",
            movement_date="2026-06-03",
        )
        assert resolve_first_units([admission.pk]) == {
            admission.pk: FIRST_UNIT_UNKNOWN
        }

    def test_order_prefers_date_then_sequence_then_pk(
        self, db: object
    ) -> None:
        patient = _make_patient("P_Q_U9")
        admission = _make_admission(patient, "ADM_Q_U9")
        _make_movement(
            patient, admission=None, sector="SEGUNDO",
            movement_date="2026-06-03", sequence=5,
        )
        _make_movement(
            patient, admission=None, sector="PRIMEIRO",
            movement_date="2026-06-03", sequence=2,
        )
        assert resolve_first_units([admission.pk]) == {
            admission.pk: "PRIMEIRO"
        }

    def test_links_are_not_rewritten(self, db: object) -> None:
        patient = _make_patient("P_Q_U10")
        admission = _make_admission(patient, "ADM_Q_U10")
        linked = _make_movement(
            patient, admission=admission, sector="UTI GERAL",
            movement_date="2026-06-02",
        )
        loose = _make_movement(
            patient, admission=None, sector="ENFERMARIA 1",
            movement_date="2026-06-05",
        )
        resolve_first_units([admission.pk])
        linked.refresh_from_db()
        loose.refresh_from_db()
        assert linked.admission_id == admission.pk
        assert loose.admission_id is None

    def test_empty_and_missing_ids(self, db: object) -> None:
        assert resolve_first_units([]) == {}
        assert resolve_first_units([999999]) == {
            999999: FIRST_UNIT_UNKNOWN
        }


@pytest.mark.django_db
class TestHospitalIndicators:
    def _ages_scene(self) -> None:
        first = _make_patient("P_Q_I1")
        adm_first = _make_admission(first, "ADM_Q_I1")
        _make_census_row("P_Q_I1")
        second = _make_patient("P_Q_I2")
        adm_second = _make_admission(second, "ADM_Q_I2")
        _make_census_row("P_Q_I2")
        _make_item(
            adm_first, description="dois dias",
            created_at=NOW - timedelta(days=2),
        )
        _make_item(
            adm_first, description="oito dias",
            created_at=NOW - timedelta(days=8),
        )
        _make_item(
            adm_second, description="cinco dias",
            created_at=NOW - timedelta(days=5),
        )

    def test_two_patients_mean_five_max_eight(self, db: object) -> None:
        self._ages_scene()
        indicators = hospital_indicators(resolve_current_cut(), NOW)
        assert indicators.patient_count == 2
        assert indicators.mean_days == 5.0
        assert indicators.max_days == 8.0

    def test_finalized_and_old_episodes_are_excluded(
        self, db: object
    ) -> None:
        self._ages_scene()
        patient = Patient.objects.get(patient_source_key="P_Q_I1")
        admission = Admission.objects.get(
            patient=patient, discharge_date__isnull=True
        )
        old = _make_admission(
            patient, "ADM_Q_I1_OLD", start="2026-04-01T08:00:00",
            end="2026-04-10T10:00:00",
        )
        _make_item(
            admission, description="resolvida",
            status=STATUS_RESOLVED,
            created_at=NOW - timedelta(days=30),
            finalized_at=NOW - timedelta(days=1),
        )
        _make_item(
            old, description="episodio antigo",
            created_at=NOW - timedelta(days=100),
        )
        indicators = hospital_indicators(resolve_current_cut(), NOW)
        assert indicators.patient_count == 2
        assert indicators.mean_days == 5.0
        assert indicators.max_days == 8.0

    def test_ambiguous_excluded_and_repetition_counted_once(
        self, db: object
    ) -> None:
        self._ages_scene()
        ambiguous = _make_patient("P_Q_I3")
        adm_ambiguous = _make_admission(ambiguous, "ADM_Q_I3")
        _make_census_row("P_Q_I3", setor="UTI", leito="U01")
        _make_census_row("P_Q_I3", setor="ENFERMARIA", leito="E02")
        _make_item(
            adm_ambiguous, description="ambigua",
            created_at=NOW - timedelta(days=50),
        )
        _make_census_row("P_Q_I1", setor="CLINICA MEDICA", leito="L01")
        indicators = hospital_indicators(resolve_current_cut(), NOW)
        assert indicators.patient_count == 2
        assert indicators.mean_days == 5.0
        assert indicators.max_days == 8.0

    def test_zero_actives(self, db: object) -> None:
        assert hospital_indicators(
            resolve_current_cut(), NOW
        ).patient_count == 0
        patient = _make_patient("P_Q_I4")
        admission = _make_admission(patient, "ADM_Q_I4")
        _make_census_row("P_Q_I4")
        _make_item(
            admission, description="resolvida",
            status=STATUS_RESOLVED,
            finalized_at=_dt("2026-06-11T10:00:00"),
        )
        indicators = hospital_indicators(resolve_current_cut(), NOW)
        assert indicators.patient_count == 0
        assert indicators.mean_days is None
        assert indicators.max_days is None


@pytest.mark.django_db
class TestSortingAndGrouping:
    def _ordered_scene(self) -> None:
        late = _make_patient("P_Q_S1")
        adm_late = _make_admission(late, "ADM_Q_S1")
        _make_census_row(
            "P_Q_S1", setor="UTI", leito="U02", captured_at="2026-06-10T08:00:00"
        )
        early = _make_patient("P_Q_S2")
        adm_early = _make_admission(early, "ADM_Q_S2")
        _make_census_row(
            "P_Q_S2", setor="CLINICA MEDICA", leito="L01",
            captured_at="2026-06-10T08:00:00",
        )
        _make_item(
            adm_late, description="uti nova",
            created_at=NOW - timedelta(days=1),
        )
        _make_item(
            adm_early, description="clinica antiga",
            created_at=NOW - timedelta(days=9),
        )
        _make_item(
            adm_early, description="clinica nova",
            created_at=NOW - timedelta(days=1),
        )

    def test_default_order_is_stable(self, db: object) -> None:
        self._ordered_scene()
        cut = resolve_current_cut()
        filters, _error = parse_aggregate_filters(_params(""))
        items = sort_aggregate_items(
            list(base_current_items(cut)), cut, filters, NOW
        )
        assert [item.description for item in items] == [
            "clinica antiga", "clinica nova", "uti nova",
        ]

    def test_time_ordering_keeps_stable_ties(self, db: object) -> None:
        self._ordered_scene()
        cut = resolve_current_cut()
        asc, _e1 = parse_aggregate_filters(_params("ordenar=tempo_asc"))
        desc, _e2 = parse_aggregate_filters(_params("ordenar=tempo_desc"))
        asc_items = sort_aggregate_items(
            list(base_current_items(cut)), cut, asc, NOW
        )
        desc_items = sort_aggregate_items(
            list(base_current_items(cut)), cut, desc, NOW
        )
        assert [item.description for item in asc_items] == [
            "clinica nova", "uti nova", "clinica antiga",
        ]
        assert [item.description for item in desc_items] == [
            "clinica antiga", "clinica nova", "uti nova",
        ]

    def test_groups_keep_every_match_together(self, db: object) -> None:
        patient = _make_patient("P_Q_S3")
        admission = _make_admission(patient, "ADM_Q_S3")
        _make_census_row("P_Q_S3")
        for index in range(3):
            _make_item(admission, description=f"grupo-{index}")
        cut = resolve_current_cut()
        filters, _error = parse_aggregate_filters(_params(""))
        items = sort_aggregate_items(
            list(base_current_items(cut)), cut, filters, NOW
        )
        groups = sort_patient_groups(group_by_patient(items, cut), filters, NOW)
        assert len(groups) == 1
        assert len(groups[0].items) == 3


@pytest.mark.django_db
class TestSpecialtyLabels:
    def test_resolve_specialty_like_censo(self, db: object) -> None:
        # update_or_create: the specialty catalog ships seeded rows (CIV
        # among them), so a plain create collides in the migrated test DB.
        Specialty.objects.update_or_create(
            code="CIV", defaults={"name": "CIRURGIA VASCULAR"}
        )
        code_to_name, name_to_code = specialty_labels()
        assert resolve_specialty("CIV", code_to_name, name_to_code) == (
            "CIV", "CIRURGIA VASCULAR",
        )
        assert resolve_specialty(
            "CIRURGIA VASCULAR", code_to_name, name_to_code
        ) == ("CIV", "CIRURGIA VASCULAR")
        assert resolve_specialty("XXX", code_to_name, name_to_code) == (
            "XXX", "XXX",
        )

    def test_options_come_from_the_cut(self, db: object) -> None:
        Specialty.objects.update_or_create(
            code="NEF", defaults={"name": "NEFROLOGIA"}
        )
        patient = _make_patient("P_Q_O1")
        admission = _make_admission(patient, "ADM_Q_O1")
        _make_census_row(
            "P_Q_O1", setor="UTI", leito="U01", especialidade="NEF"
        )
        author = _make_user("q_opt_author")
        _make_item(admission, created_by=author, updated_by=author)
        cut = resolve_current_cut()
        code_to_name, _name_to_code = specialty_labels()
        options = aggregate_options(cut, code_to_name)
        assert options.unidades == ["UTI"]
        assert options.leitos == ["U01"]
        assert options.especialidades == [
            {"value": "NEF", "label": "NEFROLOGIA", "code": "NEF"}
        ]
        assert [t.slug for t in options.tipos] == [OUTRO_SLUG]
        assert [u.username for u in options.criadores] == ["q_opt_author"]
        assert [u.username for u in options.atualizadores] == ["q_opt_author"]
        assert options.has_system_updates is False


@pytest.mark.django_db
class TestQueryBudget:
    def _scene(self, count: int, prefix: str) -> list[int]:
        admission_ids: list[int] = []
        for index in range(count):
            key = f"{prefix}{index}"
            patient = _make_patient(key)
            admission = _make_admission(patient, f"ADM_{key}")
            _make_census_row(key, leito=f"L{index:02d}")
            _make_item(admission, description=f"item {key} a")
            _make_item(admission, description=f"item {key} b")
            _make_movement(
                patient, admission=admission, sector="UTI GERAL",
                movement_date="2026-06-02",
            )
            admission_ids.append(admission.pk)
        return admission_ids

    def _panel_cost(self) -> int:
        with CaptureQueriesContext(connection) as queries:
            cut = resolve_current_cut()
            filters, error = parse_aggregate_filters(_params(""))
            assert error is None
            items = list(
                apply_aggregate_filters(
                    base_current_items(cut), cut, filters
                )
            )
            hospital_indicators(cut, NOW)
            resolve_first_units([item.admission_id for item in items])
            code_to_name, _name_to_code = specialty_labels()
            aggregate_options(cut, code_to_name)
        return len(queries)

    def test_cost_does_not_grow_with_volume(self, db: object) -> None:
        self._scene(2, "P_Q_BIG_A")
        small_cost = self._panel_cost()
        self._scene(6, "P_Q_BIG_B")
        big_cost = self._panel_cost()
        assert small_cost > 0
        assert big_cost <= small_cost
