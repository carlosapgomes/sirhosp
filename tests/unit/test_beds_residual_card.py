"""Residual-suspect card on /beds/ (v5 official section).

Strategy A: the count derives from the ``finding_map`` already computed by
``bed_status_view`` (PFIF-S4) — no new query. The 6th card links to
``/censo/`` with the exact ``finding=residual`` querystring.

Synthetic fixtures only: fake prontuario ranges, placeholder names.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
)
from apps.census.occupancy import materialize_occupancy_measurement
from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.ingestion.patient_flow_findings import (
    CODE_SUSPECTED_LEGACY_RESIDUAL,
)
from apps.patients.models import Admission, Patient

RESIDUAL_HREF = (
    reverse("services_portal:censo")
    + "?q=&unidade=&especialidade=&finding=residual&ordenar=tempo_desc"
)
RESIDUAL_LABEL = "Suspeita de paciente residual"


def _at(local_date, hour=12):
    return timezone.make_aware(
        datetime.combine(local_date, time(hour=hour)),
        timezone.get_current_timezone(),
    )


def _run():
    return IngestionRun.objects.create(
        intent="census_extraction", status="succeeded"
    )


def _catalog(effective_from, groups):
    catalog = CapacityCatalogVersion.objects.create(
        effective_from=effective_from,
        source_reference="synthetic occupancy-v5 residual card catalog",
        source_sha256=(f"{effective_from:%Y%m%d}occupancy-v5" + "0" * 40)[:64],
        schema_version="3.0",
        algorithm_version="occupancy-v5",
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


def _standard_group():
    return {
        "stable_key": "A",
        "display_name": "Group A",
        "capacity": 10,
        "policy": CalculationPolicy.STANDARD,
        "members": (("100", "Sector A", "Setor A", "all"),),
    }


def _snapshot(run, *, captured_at, index, record):
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=captured_at,
        setor_codigo="100",
        setor="Sector A",
        leito=f"BED-100-{index:03d}",
        prontuario=record,
        nome=f"PACIENTE SINTEtico {record}",
        especialidade="SYN",
        bed_status=BedStatus.OCCUPIED,
    )


def _make_residual_patient(prontuario: str) -> Patient:
    """Patient matching rule 5: active admission >= 48h, no event in 48h."""
    now = timezone.now()
    patient = Patient.objects.create(
        patient_source_key=prontuario,
        name=f"PACIENTE SINTEtico {prontuario}",
        date_of_birth=None,
    )
    admission = Admission.objects.create(
        patient=patient,
        source_admission_key=f"ADM-SINTETICO-{prontuario}",
        admission_date=now - timedelta(hours=96),
        discharge_date=None,
    )
    Admission.objects.filter(pk=admission.pk).update(
        created_at=now - timedelta(days=30)
    )
    admission.refresh_from_db()
    ClinicalEvent.objects.create(
        admission=admission,
        patient=patient,
        event_identity_key=f"evt-sintetico-{prontuario}",
        content_hash=f"hash-{prontuario}",
        happened_at=now - timedelta(hours=72),
        author_name="DR SINTEtico",
        profession_type="medica",
        content_text="Texto clínico sintético de teste.",
    )
    return patient


def _render_beds(admin_client):
    return admin_client.get(reverse("census:bed_status"))


@pytest.mark.django_db
class TestBedsResidualCard:
    def test_residual_card_renders_after_occupancy_rate(self, admin_client):
        today = timezone.localdate()
        _catalog(today, [_standard_group()])
        run = _run()
        captured_at = _at(today)
        _snapshot(run, captured_at=captured_at, index=0, record="9600001")
        _snapshot(run, captured_at=captured_at, index=1, record="9600002")
        _make_residual_patient("9600001")
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()

        assert response.status_code == 200
        # Count derives from the already-computed finding_map (strategy A).
        finding_map = response.context["finding_map"]
        expected = sum(
            1
            for f in finding_map.values()
            if f and f.code == CODE_SUSPECTED_LEGACY_RESIDUAL
        )
        assert expected == 1
        assert response.context["residual_count"] == expected
        # Exact deep-link href to /censo/ with the residual recorte.
        assert RESIDUAL_HREF in content
        assert RESIDUAL_HREF == (
            "/censo/?q=&unidade=&especialidade=&finding=residual"
            "&ordenar=tempo_desc"
        )
        assert RESIDUAL_LABEL in content
        # 6th card: rendered after the Taxa de ocupação card, v5 block only.
        assert "Taxa de ocupação" in content
        assert content.index("Taxa de ocupação") < content.index(RESIDUAL_LABEL)
        assert "Ver no censo" in content

    def test_residual_count_zero_without_residual(self, admin_client):
        today = timezone.localdate()
        _catalog(today, [_standard_group()])
        run = _run()
        captured_at = _at(today)
        _snapshot(run, captured_at=captured_at, index=0, record="9600011")
        materialize_occupancy_measurement(run_id=run.pk)

        response = _render_beds(admin_client)
        content = response.content.decode()

        assert response.status_code == 200
        assert response.context["residual_count"] == 0
        assert RESIDUAL_HREF in content
        assert RESIDUAL_LABEL in content
