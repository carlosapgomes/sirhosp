"""PFIF-S4: patient-flow findings on /beds and the admissions page.

The same current finding already shown on ``/censo`` (PFIF-S3) must appear,
with identical semantics, on every applicable patient presentation of
``/beds`` (v5 patient items, historical/physical positions, conflict
alternatives, no-bed quality cases, incomplete identity rows with a record)
and on the patient admissions page banner — with or without a selected
Admission. Official occupancy measurement, conflicts, authorization and the
query budget are unchanged.

Synthetic fixtures only: fake prontuario ranges, placeholder names, no
legacy/browser/network access. ``build_patient_flow_findings`` is consumed
unchanged (one bulk call per page render).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
    OccupancyGroupMeasurement,
    OccupancyMeasurement,
)
from apps.census.occupancy import materialize_occupancy_measurement
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric
from apps.patients.models import Admission, Patient

# Closed presentation contract from the S3 classifier (labels are constants).
LABEL_RECENT = "Atendimento recente sem internação"
LABEL_NEWBORN = "RN aguardando registro"
LABEL_COMPANION = "Possível RN acompanhante"
LABEL_FIRST_EVOLUTION = "Internação recente aguardando 1ª evolução"
LABEL_RESIDUAL = "Suspeita de paciente residual no legado"
ALL_LABELS = (
    LABEL_RECENT,
    LABEL_NEWBORN,
    LABEL_COMPANION,
    LABEL_FIRST_EVOLUTION,
    LABEL_RESIDUAL,
)

MANUAL_REVIEW_MARK = "requer revisão manual"
MANUAL_REVIEW_VISIBLE = "Requer revisão manual"
DISCHARGE_ASSERTIONS = ("alta confirmada", "alta hospitalar confirmada")


# ── Synthetic fixture builders (PFIF-S3 patterns, wall-clock relative) ──


def make_patient(prontuario: str, *, date_of_birth=None) -> Patient:
    return Patient.objects.create(
        patient_source_key=prontuario,
        name=f"PACIENTE SINTEtico {prontuario}",
        date_of_birth=date_of_birth,
    )


def make_legacy_census_row(
    prontuario: str,
    *,
    captured_at=None,
    leito: str = "01A",
    nome: str | None = None,
    setor: str = "ENFERMARIA SINTETICA",
    setor_codigo: str = "999",
) -> CensusSnapshot:
    """Census row without an ingestion run: no exact measurement (physical)."""
    return CensusSnapshot.objects.create(
        captured_at=captured_at or timezone.now(),
        setor=setor,
        setor_codigo=setor_codigo,
        leito=leito,
        prontuario=prontuario,
        nome=nome if nome is not None else f"PACIENTE SINTEtico {prontuario}",
        especialidade="",
        bed_status=BedStatus.OCCUPIED,
    )


def make_recent_outcome(
    prontuario: str, *, started_at: datetime | None = None
) -> IngestionRun:
    """Synthesize a recognized recent-encounter stage outcome (PFIF-S1/S2)."""
    started_at = started_at or (timezone.now() - timedelta(hours=2))
    run = IngestionRun.objects.create(
        status="succeeded",
        intent="admissions_only",
        parameters_json={"patient_record": prontuario},
    )
    IngestionRunStageMetric.objects.create(
        run=run,
        stage_name="encounter_fallback",
        status="succeeded",
        started_at=started_at,
        finished_at=started_at,
        details_json={
            "outcome": "recent_encounter_without_admission",
            "recency": "recent_confirmed",
        },
    )
    return run


def make_admission(
    patient: Patient,
    *,
    admission_date: datetime,
    created_at: datetime,
    discharge_date: datetime | None = None,
) -> Admission:
    adm = Admission.objects.create(
        patient=patient,
        source_admission_key=f"ADM-SINTETICO-{patient.patient_source_key}",
        admission_date=admission_date,
        discharge_date=discharge_date,
    )
    # created_at is auto_now_add; pin it deterministically for rule 1.
    Admission.objects.filter(pk=adm.pk).update(created_at=created_at)
    adm.refresh_from_db()
    return adm


# ── Exact-run (v4/v5) scenario helpers ───────────────────────────────


def _at(local_date, hour=12):
    return timezone.make_aware(
        datetime.combine(local_date, time(hour=hour)),
        timezone.get_current_timezone(),
    )


def _run() -> IngestionRun:
    return IngestionRun.objects.create(
        intent="census_extraction", status="succeeded"
    )


def _snapshot(
    run,
    *,
    captured_at,
    code,
    sector,
    status=BedStatus.EMPTY,
    index=0,
    record="",
    nome=None,
    age_band=None,
    bed=None,
):
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=captured_at,
        setor_codigo=code,
        setor=sector,
        leito=bed if bed is not None else f"BED-{code or 'BLANK'}-{index:03d}",
        prontuario=record if status == BedStatus.OCCUPIED else "",
        nome=(
            nome
            if nome is not None
            else (
                f"PACIENTE SINTEtico {record}"
                if status == BedStatus.OCCUPIED
                else status.upper()
            )
        ),
        especialidade="SYN",
        bed_status=status,
        age_band=(
            age_band
            if age_band is not None
            else (
                "age_12_or_over"
                if status == BedStatus.OCCUPIED
                else "not_applicable"
            )
        ),
    )


def _catalog(effective_from, algorithm_version, groups):
    catalog = CapacityCatalogVersion.objects.create(
        effective_from=effective_from,
        source_reference=f"synthetic {algorithm_version} findings catalog",
        source_sha256=(f"{effective_from:%Y%m%d}{algorithm_version}" + "0" * 40)[
            :64
        ],
        schema_version="3.0",
        algorithm_version=algorithm_version,
    )
    for raw_group in groups:
        group = CapacityGroupDefinition.objects.create(
            catalog=catalog,
            stable_key=raw_group["stable_key"],
            display_name=raw_group.get("display_name", raw_group["stable_key"]),
            official_capacity=raw_group.get("capacity"),
            calculation_policy=raw_group["policy"],
        )
        for member in raw_group["members"]:
            CapacitySectorMembership.objects.create(
                catalog=catalog,
                group=group,
                source_code=member[0],
                configured_source_name=member[1],
                source_display_name=member[2],
                age_selector=member[3] if len(member) > 3 else "all",
            )
    return catalog


def _standard_group(*, key="A", capacity=10):
    return {
        "stable_key": key,
        "display_name": f"Group {key}",
        "capacity": capacity,
        "policy": CalculationPolicy.STANDARD,
        "members": (("100", "Sector A", "Setor A", "all"),),
    }


def _render_beds(admin_client):
    return admin_client.get(reverse("census:bed_status"))


def _admissions_client() -> Client:
    user_model = get_user_model()
    staff = user_model.objects.filter(is_staff=True).first()
    if staff is None:
        staff = user_model.objects.create_user(
            username="staff-sintetico",
            password="senha-sintetica",
            is_staff=True,
        )
    client = Client()
    client.force_login(staff)
    return client


# ── /beds: v5 patient item shapes (R1, R2) ───────────────────────────


@pytest.mark.django_db
class TestBedStatusV5Finding:
    """V5 page: findings on patient items without touching official values."""

    def test_v5_patient_item_shows_finding_without_metric_change(
        self, admin_client
    ):
        today = timezone.localdate()
        _catalog(today, "occupancy-v5", [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            record="47201",
        )
        make_recent_outcome("47201")
        make_patient("47201")
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        # Badge with the same closed label as /censo.
        assert LABEL_RECENT in content
        # Official measurement untouched: one identified, counted patient.
        measurement = response.context["measurement"]
        assert measurement.occupied_for_rate == 1
        assert ">Pacientes identificados: 1<" in content

    def test_v5_patient_without_bed_shows_finding(self, admin_client):
        today = timezone.localdate()
        _catalog(today, "occupancy-v5", [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            record="47302",
            bed="",
        )
        make_patient(
            "47302",
            date_of_birth=(timezone.localdate() - timedelta(days=2)),
        )
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        assert "sem leito informado" in content
        assert LABEL_NEWBORN in content
        assert response.context["measurement"].occupied_for_rate == 1

    def test_v5_incomplete_row_with_record_shows_finding(self, admin_client):
        today = timezone.localdate()
        _catalog(today, "occupancy-v5", [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            record="47403",
            nome="",
        )
        make_recent_outcome("47403")
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Identificação incompleta" in content
        assert LABEL_RECENT in content
        # Incomplete rows stay out of the official count.
        assert response.context["measurement"].occupied_for_rate == 0

    def test_beds_none_finding_renders_no_placeholder(self, admin_client):
        today = timezone.localdate()
        _catalog(today, "occupancy-v5", [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            record="47504",
        )
        materialize_occupancy_measurement(run_id=run.pk)

        content = _render_beds(admin_client).content.decode()
        for label in ALL_LABELS:
            assert label not in content


# ── /beds: historical/physical and quality shapes (R2) ────────────────


@pytest.mark.django_db
class TestBedStatusLegacyShapes:
    """No-measurement physical positions and v4 quality cases."""

    def test_legacy_position_shows_finding(self, admin_client):
        make_patient(
            "48101",
            date_of_birth=(timezone.localdate() - timedelta(days=1)),
        )
        captured_at = timezone.now()
        make_legacy_census_row("48101", captured_at=captured_at)
        CensusSnapshot.objects.create(
            captured_at=captured_at,
            setor="ENFERMARIA SINTETICA",
            setor_codigo="999",
            leito="02B",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
            age_band="not_applicable",
        )

        response = _render_beds(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PACIENTE SINTEtico 48101" in content
        assert LABEL_NEWBORN in content

    def test_v4_conflict_alternative_shows_finding_without_authority_change(
        self, admin_client
    ):
        today = timezone.localdate()
        _catalog(today, "occupancy-v4", [_standard_group()])
        run = _run()
        captured_at = _at(today)
        _snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            record="48201",
            bed="BED-CONF-01",
        )
        _snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            record="48202",
            bed="BED-CONF-01",
        )
        make_recent_outcome("48201")
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        # The finding belongs to its patient, exactly one badge (each badge
        # carries the label twice: title attribute + visible text).
        assert content.count(LABEL_RECENT) == 2
        # Conflict presentation unchanged: no authoritative winner.
        assert content.count("registro divergente — não autoritativo") == 2
        assert response.context["measurement"].occupied_for_rate == 1

    def test_v4_unidentified_no_bed_case_shows_finding(self, admin_client):
        today = timezone.localdate()
        _catalog(today, "occupancy-v4", [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            record="48301",
            bed="",
        )
        make_patient(
            "48301",
            date_of_birth=(timezone.localdate() - timedelta(days=2)),
        )
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Linhas ocupadas sem posição" in content
        assert LABEL_NEWBORN in content


# ── Admissions page: with and without Admission (R3) ──────────────────


@pytest.mark.django_db
class TestAdmissionPageFinding:
    def _page(self, patient):
        return _admissions_client().get(
            reverse("patients:admission_list", args=[patient.pk])
        )

    def test_admission_page_without_admission_shows_recent_finding(self):
        patient = make_patient("49101")
        make_recent_outcome(patient.patient_source_key)

        response = self._page(patient)
        content = response.content.decode()
        assert response.status_code == 200
        assert LABEL_RECENT in content

    def test_admission_page_without_admission_shows_newborn_finding(self):
        patient = make_patient(
            "49202",
            date_of_birth=(timezone.localdate() - timedelta(days=2)),
        )
        make_legacy_census_row(patient.patient_source_key)

        response = self._page(patient)
        content = response.content.decode()
        assert response.status_code == 200
        assert LABEL_NEWBORN in content

    def test_admission_page_selected_admission_shows_residual_and_manual_review(
        self,
    ):
        now = timezone.now()
        patient = make_patient("49303")
        make_legacy_census_row(patient.patient_source_key)
        make_admission(
            patient,
            admission_date=now - timedelta(hours=72),
            created_at=now - timedelta(hours=72),
        )

        response = self._page(patient)
        content = response.content.decode()
        assert response.status_code == 200
        assert response.context["selected_admission"] is not None
        assert LABEL_RESIDUAL in content
        assert MANUAL_REVIEW_VISIBLE in content

    def test_residual_never_asserts_confirmed_discharge(self):
        now = timezone.now()
        patient = make_patient("49404")
        make_legacy_census_row(patient.patient_source_key)
        make_admission(
            patient,
            admission_date=now - timedelta(hours=72),
            created_at=now - timedelta(hours=72),
        )

        content = self._page(patient).content.decode()
        assert LABEL_RESIDUAL in content
        for phrase in DISCHARGE_ASSERTIONS:
            assert phrase not in content


# ── Authorization and cross-surface consistency (R5, R7) ──────────────


@pytest.mark.django_db
class TestFindingsAuthorization:
    def test_anonymous_redirected_on_beds_and_admissions(self, client: Client):
        patient = make_patient("49505")
        beds_url = reverse("census:bed_status")
        adm_url = reverse("patients:admission_list", args=[patient.pk])
        for url in (beds_url, adm_url):
            response = client.get(url)
            assert response.status_code == 302
            assert "/login/" in response.url  # type: ignore[attr-defined]


@pytest.mark.django_db
class TestCrossSurfaceConsistency:
    def test_same_fixture_same_label_on_three_surfaces(
        self, admin_client
    ):
        patient = make_patient(
            "49606",
            date_of_birth=(timezone.localdate() - timedelta(days=1)),
        )
        make_legacy_census_row(patient.patient_source_key)

        censo = admin_client.get(reverse("services_portal:censo"))
        beds = _render_beds(admin_client)
        admissions = admin_client.get(
            reverse("patients:admission_list", args=[patient.pk])
        )
        for response in (censo, beds, admissions):
            assert response.status_code == 200
        assert censo.content.decode().count(LABEL_NEWBORN) >= 1
        assert beds.content.decode().count(LABEL_NEWBORN) >= 1
        assert admissions.content.decode().count(LABEL_NEWBORN) >= 1


# ── Query budget and persistence contracts (R6, R5) ───────────────────


@pytest.mark.django_db
class TestQueryBudgetSurfaces:
    def test_beds_query_budget_constant_across_census_sizes(
        self, admin_client
    ):
        """Finding lookups add a constant number of queries, never per row."""
        now = timezone.now()

        def build_photo(prefix: str, size: int, captured_at):
            for index in range(size):
                record = f"{prefix}{index:03d}"
                make_legacy_census_row(
                    record,
                    captured_at=captured_at,
                    leito=f"L{index:03d}",
                )
                make_recent_outcome(record, started_at=now)

        build_photo("501", 3, now - timedelta(hours=5))
        with CaptureQueriesContext(connection) as ctx_small:
            response = _render_beds(admin_client)
        assert response.status_code == 200
        queries_small = len(ctx_small.captured_queries)

        # A newer, much larger census photo becomes the rendered one.
        build_photo("502", 21, now - timedelta(hours=1))
        with CaptureQueriesContext(connection) as ctx_big:
            response = _render_beds(admin_client)
        assert response.status_code == 200
        queries_big = len(ctx_big.captured_queries)
        assert LABEL_RECENT in response.content.decode()

        assert queries_big - queries_small <= 8, (
            f"query budget exceeded: {queries_small} -> {queries_big} "
            f"(delta {queries_big - queries_small} > 8); findings lookups "
            "are scaling with the census size"
        )


@pytest.mark.django_db
class TestNoFindingsPersistence:
    def test_no_measurement_or_finding_persisted_by_pages(self, admin_client):
        now = timezone.now()
        patient = make_patient("49707")
        make_legacy_census_row(patient.patient_source_key)
        make_recent_outcome(patient.patient_source_key, started_at=now)
        make_admission(
            patient,
            admission_date=now - timedelta(hours=72),
            created_at=now - timedelta(hours=72),
        )

        before = {
            "measurement": OccupancyMeasurement.objects.count(),
            "group": OccupancyGroupMeasurement.objects.count(),
            "stage": IngestionRunStageMetric.objects.count(),
            "admission": Admission.objects.count(),
            "patient": Patient.objects.count(),
        }
        assert _render_beds(admin_client).status_code == 200
        assert (
            admin_client.get(
                reverse("patients:admission_list", args=[patient.pk])
            ).status_code
            == 200
        )
        after = {
            "measurement": OccupancyMeasurement.objects.count(),
            "group": OccupancyGroupMeasurement.objects.count(),
            "stage": IngestionRunStageMetric.objects.count(),
            "admission": Admission.objects.count(),
            "patient": Patient.objects.count(),
        }
        assert before == after


# ── Characterization (passes from the start; not a RED) ───────────────


@pytest.mark.django_db
class TestCharacterization:
    def test_newborn_with_discharged_admission_keeps_finding(
        self, admin_client
    ):
        """D5: “sem internação” means no ACTIVE admission (design D5).

        A 0–4 day newborn in the census whose only Admission is already
        discharged (``discharge_date`` set) keeps the
        ``newborn_waiting_registration`` finding: a closed admission is
        historical fact and never cancels the census presence reading.
        Fixes at DB level the “no active admission” rule without touching
        the classifier.
        """
        now = timezone.now()
        patient = make_patient(
            "49808",
            date_of_birth=(timezone.localdate() - timedelta(days=2)),
        )
        make_legacy_census_row(patient.patient_source_key)
        make_admission(
            patient,
            admission_date=now - timedelta(days=3),
            created_at=now - timedelta(days=3),
            discharge_date=now - timedelta(hours=6),
        )

        censo = admin_client.get(reverse("services_portal:censo"))
        assert censo.status_code == 200
        assert LABEL_NEWBORN in censo.content.decode()

        # The discharged admission still exists and is selectable.
        admissions_page = admin_client.get(
            reverse("patients:admission_list", args=[patient.pk])
        )
        assert admissions_page.status_code == 200
        assert admissions_page.context["selected_admission"] is not None
