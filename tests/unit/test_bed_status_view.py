"""Tests for bed_status_view (Slice S6)."""

from __future__ import annotations

import json
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.census.capacity_catalog import validate_catalog_document
from apps.census.models import (
    BedStatus,
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
)
from apps.ingestion.models import IngestionRun

INITIAL_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "census"
    / "data"
    / "initial_sector_capacity_catalog.json"
)
CORRECTED_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "census"
    / "data"
    / "corrected_sector_capacity_catalog.json"
)


@pytest.mark.django_db
class TestBedStatusView:
    def test_anonymous_redirected(self, client):
        url = reverse("census:bed_status")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_authenticated_can_access(self, admin_client):
        url = reverse("census:bed_status")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Nenhum dado de censo disponível" in response.content.decode()

    def test_shows_sector_data(self, admin_client):
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="01",
            prontuario="111",
            nome="PACIENTE UM",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="02",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "UTI A" in content
        assert "PACIENTE UM" in content

    def test_uses_only_latest_snapshot(self, admin_client):
        old_time = timezone.now() - timezone.timedelta(hours=4)
        new_time = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old_time,
            setor="OLD SETOR",
            leito="01",
            prontuario="AAA",
            nome="OLD PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new_time,
            setor="NEW SETOR",
            leito="01",
            prontuario="BBB",
            nome="NEW PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()

        assert "NEW SETOR" in content
        assert "OLD SETOR" not in content


@pytest.mark.django_db
class TestBedStatusTotals:
    """S3: Bed status view includes global totals context."""

    def test_view_includes_totals_in_context(self, admin_client):
        """The view context includes 'totals' dict with all statuses."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="", nome="", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        assert response.status_code == 200

        totals = response.context["totals"]
        assert totals["occupied"] == 1
        assert totals["empty"] == 1
        assert totals["total"] == 2

    def test_totals_sum_across_sectors(self, admin_client):
        """Global totals sum correctly across multiple sectors."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="A01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="A02",
            prontuario="222", nome="PAC2", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="A03",
            prontuario="", nome="", especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="ENFERMARIA", leito="E01",
            prontuario="333", nome="PAC3", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        assert response.status_code == 200

        totals = response.context["totals"]
        assert totals["occupied"] == 3
        assert totals["empty"] == 1
        assert totals["total"] == 4

    def test_totals_rendered_in_html(self, admin_client):
        """Global totals are rendered as summary cards at the top."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="SETOR X", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="SETOR X", leito="02",
            prontuario="", nome="", especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="SETOR X", leito="03",
            prontuario="", nome="MANUT", especialidade="",
            bed_status=BedStatus.MAINTENANCE,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "SETOR X" in content
        # Summary card values should appear
        assert "1" in content  # occupied
        assert "3" in content  # total

    def test_bed_view_uses_cards_not_table(self, admin_client):
        """The bed status page uses card layout, not <table>."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="CARDIACO", leito="01",
            prontuario="111", nome="PAC", especialidade="CAR",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "card" in content.lower()
        assert "collapse" in content


@pytest.mark.django_db
class TestBedStatusOfficialOccupancy:
    """SCOH-S4: /beds enriched with the exact latest-census measurement."""

    @staticmethod
    def _at(local_date, hour=12):
        return timezone.make_aware(
            datetime.combine(local_date, time(hour=hour)),
            timezone.get_current_timezone(),
        )

    @staticmethod
    def _run():
        return IngestionRun.objects.create(
            intent="census_extraction", status="succeeded"
        )

    @staticmethod
    def _snapshot(
        run, *, captured_at, code, sector, status=BedStatus.EMPTY, index=0, patient_marker=""
    ):
        return CensusSnapshot.objects.create(
            ingestion_run=run,
            captured_at=captured_at,
            setor_codigo=code,
            setor=sector,
            leito=f"BED-{code or 'BLANK'}-{index:03d}",
            prontuario=patient_marker if status == BedStatus.OCCUPIED else "",
            nome=(
                f"Synthetic Patient {patient_marker}"
                if status == BedStatus.OCCUPIED
                else status.upper()
            ),
            especialidade="SYN",
            bed_status=status,
        )

    @staticmethod
    def _catalog(effective_from, groups):
        catalog = CapacityCatalogVersion.objects.create(
            effective_from=effective_from,
            source_reference="synthetic bed-status test catalog",
            source_sha256=(f"{effective_from:%Y%m%d}" + "b" * 64)[:64],
            schema_version="1.0",
        )
        for raw_group in groups:
            group = CapacityGroupDefinition.objects.create(
                catalog=catalog,
                stable_key=raw_group["stable_key"],
                display_name=raw_group.get("display_name", raw_group["stable_key"]),
                official_capacity=raw_group.get("capacity"),
                calculation_policy=raw_group["policy"],
            )
            for code, configured_name in raw_group["members"]:
                CapacitySectorMembership.objects.create(
                    catalog=catalog,
                    group=group,
                    source_code=code,
                    configured_source_name=configured_name,
                )
        return catalog

    @staticmethod
    def _standard_group(
        *,
        key="A",
        capacity=10,
        members=(("100", "Sector A"),),
    ):
        return {
            "stable_key": key,
            "display_name": f"Group {key}",
            "capacity": capacity,
            "policy": CalculationPolicy.STANDARD,
            "members": members,
        }

    @staticmethod
    def _materialize(run_id):
        from apps.census.occupancy import materialize_occupancy_measurement

        return materialize_occupancy_measurement(run_id=run_id)

    def _render(self, admin_client):
        return admin_client.get(reverse("census:bed_status"))

    def test_exact_measurement_displays_capture_time_and_effective_date(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today, 8)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert response.status_code == 200
        assert "08:00" in content
        assert today.strftime("%d/%m/%Y") in content
        assert "Group A" in content

    def test_no_exact_measurement_preserves_raw_table_and_shows_pending(self, admin_client):
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="01",
            prontuario="111",
            nome="PACIENTE UM",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )

        response = self._render(admin_client)
        content = response.content.decode()

        assert "UTI A" in content
        assert "PACIENTE UM" in content
        assert "Pendente" in content

    def test_older_measurement_is_never_shown_for_newer_census(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group()])
        old_run = self._run()
        self._snapshot(
            old_run,
            captured_at=self._at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="OLD-001",
        )
        self._materialize(old_run.pk)
        new_run = self._run()
        self._snapshot(
            new_run,
            captured_at=self._at(today, 20),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="NEW-001",
        )

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Pendente" in content
        assert "Group A" not in content
        assert "80,00%" not in content

    def test_shared_groups_render_one_official_row_each(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                self._standard_group(
                    key="ENF-2B-CARD",
                    capacity=15,
                    members=(("719", "Cardio A"), ("2156", "Cardio B")),
                ),
                self._standard_group(
                    key="CO",
                    capacity=8,
                    members=(("20", "CO 20"), ("1110", "CO 1110")),
                ),
            ],
        )
        run = self._run()
        for index, (code, sector) in enumerate(
            [("719", "Cardio A"), ("2156", "Cardio B"), ("20", "CO 20"), ("1110", "CO 1110")]
        ):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code=code,
                sector=sector,
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()

        assert [row.stable_key for row in rows] == ["CO", "ENF-2B-CARD"]
        assert "Group CO" in content
        assert "Group ENF-2B-CARD" in content

    def test_shared_row_expansion_keeps_source_sectors_and_beds(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                self._standard_group(
                    key="ENF-2B-CARD",
                    capacity=15,
                    members=(("719", "Cardio A"), ("2156", "Cardio B")),
                ),
            ],
        )
        run = self._run()
        for index, (code, sector) in enumerate([("719", "Cardio A"), ("2156", "Cardio B")]):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code=code,
                sector=sector,
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()
        cardio = next(row for row in rows if row.stable_key == "ENF-2B-CARD")

        assert set(cardio.source_sectors) == {"Cardio A", "Cardio B"}
        assert len(cardio.beds) == 2
        assert cardio.official_capacity == 15
        assert "Cardio A" in content
        assert "Cardio B" in content
        assert "BED-719-000" in content
        assert "BED-2156-001" in content

    def test_persisted_counts_capacity_and_percentage_render(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group(key="A", capacity=10)])
        run = self._run()
        captured_at = self._at(today)
        for index in range(8):
            self._snapshot(
                run,
                captured_at=captured_at,
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.EMPTY,
            index=8,
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.RESERVED,
            index=9,
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()
        row = rows[0]

        assert row.official_capacity == 10
        assert row.occupied_count == 8
        assert row.occupancy_percentage == Decimal("80.00")
        assert row.status_counts == {
            "occupied": 8,
            "empty": 1,
            "reserved": 1,
            "maintenance": 0,
            "isolation": 0,
        }
        assert "Capacidade: 10" in content
        assert "80,00%" in content
        assert "8 ocupados" in content
        assert "1 vagos" in content
        assert "1 reserv." in content

    def test_over_capacity_shows_visual_textual_warning_and_exceeded_by(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                self._standard_group(
                    key="CO",
                    capacity=8,
                    members=(("20", "CO 20"),),
                ),
            ],
        )
        run = self._run()
        for index in range(54):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code="20",
                sector="CO 20",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"STALE-{index:03d}",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()
        row = rows[0]

        assert row.over_capacity is True
        assert row.occupancy_percentage == Decimal("675.00")
        assert row.exceeded_by == 46
        assert "675,00%" in content
        assert "Acima da capacidade" in content
        assert "Excedente: 46" in content
        assert "border-danger" in content

    def test_at_or_below_capacity_has_no_over_capacity_warning(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group(key="A", capacity=10)])
        run = self._run()
        captured_at = self._at(today)
        for index in range(8):
            self._snapshot(
                run,
                captured_at=captured_at,
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "80,00%" in content
        assert "Acima da capacidade" not in content
        assert "Excedente:" not in content
        assert "border-danger" not in content

    def test_registered_legacy_occupancy_label_is_present(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Posições registradas no sistema de origem" in content

    def _initial_catalog_groups(self):
        document = json.loads(INITIAL_CATALOG.read_text(encoding="utf-8"))
        validated = validate_catalog_document(document)
        return [
            {
                "stable_key": group.stable_key,
                "display_name": group.display_name,
                "capacity": group.official_capacity,
                "policy": group.calculation_policy,
                "members": tuple(
                    (member.source_code, member.configured_source_name)
                    for member in group.memberships
                ),
            }
            for group in validated.groups
        ]

    def test_initial_catalog_dual_coverage_and_hospital_totals_render(self, admin_client):
        today = timezone.localdate()
        groups = self._initial_catalog_groups()
        self._catalog(today, groups)
        run = self._run()
        index = 0
        for group in groups:
            for code, sector in group["members"]:
                self._snapshot(
                    run,
                    captured_at=self._at(today),
                    code=code,
                    sector=sector,
                    index=index,
                )
                index += 1
        self._materialize(run.pk)

        response = self._render(admin_client)
        measurement = response.context["measurement"]
        content = response.content.decode()

        assert measurement.observed_sector_count == 47
        assert measurement.capacity_covered_sector_count == 44
        assert measurement.calculable_sector_count == 43
        assert measurement.known_capacity == 658
        assert measurement.calculable_capacity == 626
        assert "44 de 47" in content
        assert "setores com capacidade cadastrada" in content
        assert "43 de 47" in content
        assert "setores com lotação calculável" in content
        assert "Capacidade conhecida: 658" in content
        assert "Capacidade calculável: 626" in content

    def test_obstetricia_3a_shows_capacity_and_pending_mapping_never_percentage(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                {
                    "stable_key": "OBST-3A",
                    "display_name": "Obstetricia 3A",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("654", "3A Source"),),
                },
            ],
        )
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-3A",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()
        row = rows[0]

        assert row.stable_key == "OBST-3A"
        assert row.official_capacity == 32
        assert row.occupancy_percentage is None
        assert row.over_capacity is False
        assert "Obstetricia 3A" in content
        assert "Capacidade: 32" in content
        assert "cama-berço" in content
        assert "0.00%" not in content
        assert "0,00%" not in content

    def test_unrated_and_unmapped_show_unavailable_never_zero(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                {
                    "stable_key": "UNRATED-MED-PED",
                    "display_name": "Unrated Med Ped",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("1002", "Unrated Source"),),
                },
            ],
        )
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="1002",
            sector="Unrated Source",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-U1",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="007",
            sector="Unknown Leading",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="SYN-U2",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Capacidade não cadastrada" in content
        assert "Unknown Leading" in content
        assert "0.00%" not in content
        assert "0,00%" not in content
        assert "0%" not in content

    def test_name_mismatch_shows_hint_without_remapping_group(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Renamed Source Sector",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-R",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()

        assert rows[0].stable_key == "A"
        assert rows[0].name_mismatch is True
        assert "Group A" in content
        assert "Nome divergente" in content
        assert "Renamed Source Sector" in content

    def test_measurement_expansion_keeps_patient_link_and_status_labels(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Synthetic Patient SYN-001" in content
        assert "Ocupado" in content
        assert "collapse" in content

    def test_ambiguous_provenance_falls_back_without_stale_statistics(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [self._standard_group()])
        run_a = self._run()
        run_b = self._run()
        self._snapshot(
            run_a,
            captured_at=self._at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-A",
        )
        self._snapshot(
            run_b,
            captured_at=self._at(today, 8),
            code="100",
            sector="Sector B",
            index=1,
            patient_marker="SYN-B",
        )

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Pendente" in content
        assert "Group A" not in content


@pytest.mark.django_db
class TestBedStatusCorrectedPresentation:
    """CCO3A-S4: corrected occupancy-v2 presentation on /beds.

    Synthetic v2 catalogs partition code 654 into Adulto/Infantil and keep
    CO unrated; every assertion consumes only persisted measurement values
    plus the exact-run census snapshots.
    """

    @staticmethod
    def _at(local_date, hour=12):
        return timezone.make_aware(
            datetime.combine(local_date, time(hour=hour)),
            timezone.get_current_timezone(),
        )

    @staticmethod
    def _run():
        return IngestionRun.objects.create(
            intent="census_extraction", status="succeeded"
        )

    @staticmethod
    def _snapshot(
        run,
        *,
        captured_at,
        code,
        sector,
        status=BedStatus.EMPTY,
        index=0,
        patient_marker="",
        age_band=None,
    ):
        return CensusSnapshot.objects.create(
            ingestion_run=run,
            captured_at=captured_at,
            setor_codigo=code,
            setor=sector,
            leito=f"BED-{code or 'BLANK'}-{index:03d}",
            prontuario=patient_marker if status == BedStatus.OCCUPIED else "",
            nome=(
                f"Synthetic Patient {patient_marker}"
                if status == BedStatus.OCCUPIED
                else status.upper()
            ),
            especialidade="SYN",
            bed_status=status,
            age_band=(
                age_band
                if age_band is not None
                else ("not_applicable" if status != BedStatus.OCCUPIED else "unknown")
            ),
        )

    @staticmethod
    def _catalog(effective_from, groups):
        catalog = CapacityCatalogVersion.objects.create(
            effective_from=effective_from,
            source_reference="synthetic corrected bed-status test catalog",
            source_sha256=(f"{effective_from:%Y%m%d}" + "c" * 64)[:64],
            schema_version="1.0",
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
                selector = member[2] if len(member) > 2 else "all"
                CapacitySectorMembership.objects.create(
                    catalog=catalog,
                    group=group,
                    source_code=member[0],
                    configured_source_name=member[1],
                    age_selector=selector,
                )
        return catalog

    @staticmethod
    def _partitioned_3a():
        """Corrected-style catalog: 654 split exclusively into Adulto/Infantil."""
        return [
            {
                "stable_key": "OBST-3A-ADULTO",
                "display_name": "Enfermaria 3A – Adulto",
                "capacity": 32,
                "policy": CalculationPolicy.STANDARD,
                "members": (("654", "3A Source", "age_12_or_over"),),
            },
            {
                "stable_key": "OBST-3A-INFANTIL",
                "display_name": "Enfermaria 3A – Infantil",
                "capacity": 16,
                "policy": CalculationPolicy.STANDARD,
                "members": (("654", "3A Source", "under_12"),),
            },
        ]

    @staticmethod
    def _co_unrated():
        return {
            "stable_key": "CO",
            "display_name": "Centro Obstétrico",
            "capacity": None,
            "policy": CalculationPolicy.UNRATED,
            "members": tuple(
                (code, f"CO {code}", "all")
                for code in ("20", "1110", "1112", "1114", "1116")
            ),
        }

    def _materialize(self, run_id):
        from apps.census.occupancy import materialize_occupancy_measurement

        return materialize_occupancy_measurement(run_id=run_id)

    def _render(self, admin_client):
        return admin_client.get(reverse("census:bed_status"))

    def test_v2_co_appears_once_with_raw_counts_and_exclusion_texts(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, [*self._partitioned_3a(), self._co_unrated()])
        run = self._run()
        codes = ("20", "1110", "1112", "1114", "1116")
        for index in range(54):
            code = codes[index % len(codes)]
            self._snapshot(
                run,
                captured_at=self._at(today),
                code=code,
                sector=f"CO {code}",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()
        co_rows = [row for row in rows if row.stable_key == "CO"]

        assert len(co_rows) == 1
        co = co_rows[0]
        assert co.official_capacity is None
        assert co.occupancy_percentage is None
        assert co.exceeded_by is None
        assert co.status_counts["occupied"] == 54
        assert "Centro Obstétrico" in content
        assert "Capacidade não cadastrada" in content
        assert "Não incluído na taxa de ocupação da unidade" in content
        assert "675,00%" not in content
        assert "Capacidade: 8" not in content
        assert "Excedente: 46" not in content
        assert "Aguardando mapeamento cama-berço" not in content

    def test_v1_co_historical_percentage_and_overcapacity_are_preserved(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstétrico",
                    "capacity": 8,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (("20", "CO 20"),),
                },
            ],
        )
        run = self._run()
        for index in range(54):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code="20",
                sector="CO 20",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"STALE-{index:03d}",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "675,00%" in content
        assert "Capacidade: 8" in content
        assert "Acima da capacidade" in content
        assert "Excedente: 46" in content

    def test_v2_adult_32_and_child_16_render_persisted_percentages(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        rows = [
            ("age_12_or_over", "A-1"),
            ("age_12_or_over", "A-2"),
            ("age_12_or_over", "A-3"),
            ("age_12_or_over", "A-4"),
            ("age_12_or_over", "A-5"),
            ("under_12", "C-1"),
            ("under_12", "C-2"),
            ("under_12", "C-3"),
        ]
        for index, (band, marker) in enumerate(rows):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code="654",
                sector="3A Source",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=marker,
                age_band=band,
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        groups = {row.stable_key: row for row in response.context["measured_groups"]}
        content = response.content.decode()
        adult = groups["OBST-3A-ADULTO"]
        child = groups["OBST-3A-INFANTIL"]

        assert adult.official_capacity == 32
        assert adult.occupied_count == 5
        assert adult.occupancy_percentage == Decimal("15.63")
        assert child.official_capacity == 16
        assert child.occupied_count == 3
        assert child.occupancy_percentage == Decimal("18.75")
        assert "Enfermaria 3A – Adulto" in content
        assert "Enfermaria 3A – Infantil" in content
        assert "Capacidade: 32" in content
        assert "Capacidade: 16" in content
        assert "15,63%" in content
        assert "18,75%" in content
        assert "cama-berço" not in content

    def test_v2_occupied_valid_beds_appear_once_in_their_own_sector(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        bands = ["age_12_or_over"] * 2 + ["under_12"] * 2
        markers = ["ADULT-1", "ADULT-2", "CHILD-1", "CHILD-2"]
        for index, (band, marker) in enumerate(
            zip(bands, markers, strict=True)
        ):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code="654",
                sector="3A Source",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=marker,
                age_band=band,
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        groups = {row.stable_key: row for row in response.context["measured_groups"]}
        adult = groups["OBST-3A-ADULTO"]
        child = groups["OBST-3A-INFANTIL"]

        assert {bed["prontuario"] for bed in adult.beds} == {"ADULT-1", "ADULT-2"}
        assert {bed["prontuario"] for bed in child.beds} == {"CHILD-1", "CHILD-2"}
        assert len(adult.beds) + len(child.beds) == 4

    def test_v2_non_occupied_and_unknown_654_beds_appear_once_in_auxiliary(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="UNKNOWN-1",
            age_band="unknown",
        )
        for index, status in enumerate(
            [BedStatus.EMPTY, BedStatus.RESERVED, BedStatus.MAINTENANCE],
            start=2,
        ):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code="654",
                sector="3A Source",
                status=status,
                index=index,
            )

        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        groups = {row.stable_key: row for row in rows}
        content = response.content.decode()
        units = response.context["units"]
        adult = groups["OBST-3A-ADULTO"]
        auxiliary = next(
            (row for row in rows if "classificação etária" in row.display_name),
            None,
        )

        assert auxiliary is not None
        assert len(units) == 1
        assert units[0].sources[0].source_code == "654"
        assert content.count("BED-654-000") == 1
        assert content.count("BED-654-001") == 1
        assert content.count("BED-654-002") == 1
        assert content.count("BED-654-003") == 1
        assert content.count("BED-654-004") == 1
        assert [bed["prontuario"] for bed in adult.beds] == ["ADULT-1"]
        assert groups["OBST-3A-INFANTIL"].beds == []
        assert len(auxiliary.beds) == 4
        assert sum(1 for bed in auxiliary.beds if bed["prontuario"] == "UNKNOWN-1") == 1
        assert sum(1 for bed in auxiliary.beds if not bed["prontuario"]) == 3
        assert auxiliary.official_capacity is None
        assert auxiliary.occupancy_percentage is None
        assert auxiliary.exceeded_by is None
        assert "cama-berço" not in content

    def test_v2_auxiliary_group_keeps_official_coverage_untouched(self, admin_client):
        today = timezone.localdate()
        self._catalog(
            today,
            [
                *self._partitioned_3a(),
                self._co_unrated(),
                {
                    "stable_key": "ENF-2B-CARD",
                    "display_name": "Cardio 2B",
                    "capacity": 15,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (("719", "Cardio A", "all"),),
                },
            ],
        )
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.EMPTY,
            index=0,
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="719",
            sector="Cardio A",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="CARDIO-1",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        measurement = response.context["measurement"]
        rows = response.context["measured_groups"]
        auxiliary = next(
            (row for row in rows if "classificação etária" in row.display_name),
            None,
        )

        assert auxiliary is not None
        assert len(rows) == 5
        assert measurement.official_sector_count == 4
        assert measurement.official_capacity_sector_count == 3
        assert measurement.official_calculable_sector_count == 3
        assert measurement.known_capacity == 63
        assert measurement.calculable_capacity == 63
        assert measurement.unknown_age_count == 0

    def test_v2_full_corrected_catalog_39_43_666_666(self, admin_client):
        today = timezone.localdate()
        document = json.loads(CORRECTED_CATALOG.read_text(encoding="utf-8"))
        validated = validate_catalog_document(document)
        groups = [
            {
                "stable_key": group.stable_key,
                "display_name": group.display_name,
                "capacity": group.official_capacity,
                "policy": group.calculation_policy,
                "members": tuple(
                    (m.source_code, m.configured_source_name, m.age_selector)
                    for m in group.memberships
                ),
            }
            for group in validated.groups
        ]
        self._catalog(today, groups)
        run = self._run()
        for index, group in enumerate(validated.groups):
            for member in group.memberships:
                self._snapshot(
                    run,
                    captured_at=self._at(today),
                    code=member.source_code,
                    sector=member.configured_source_name,
                    index=index,
                )
        self._materialize(run.pk)

        response = self._render(admin_client)
        measurement = response.context["measurement"]
        content = response.content.decode()

        assert measurement.official_sector_count == 43
        assert measurement.official_capacity_sector_count == 39
        assert measurement.official_calculable_sector_count == 39
        assert measurement.known_capacity == 666
        assert measurement.calculable_capacity == 666
        assert "39 de 43" in content
        assert "setores oficiais com capacidade cadastrada" in content
        assert "setores oficiais com lotação calculável" in content
        assert "Capacidade conhecida: 666" in content
        assert "Capacidade calculável: 666" in content

    def test_v2_partial_alert_shows_aggregate_count_and_daily_exclusion(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="UNKNOWN-1",
            age_band="unknown",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        measurement = response.context["measurement"]
        content = response.content.decode()

        assert measurement.age_partial is True
        assert measurement.unknown_age_count == 1
        assert "Taxa pontual parcial" in content
        assert "médias oficiais diárias" in content
        assert "(parcial)" in content

    def test_v2_complete_measurement_has_no_partial_alert(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Taxa pontual parcial" not in content
        assert "médias oficiais diárias" not in content

    def test_v1_historical_44_47_43_47_658_626_preserved(self, admin_client):
        today = timezone.localdate()
        document = json.loads(INITIAL_CATALOG.read_text(encoding="utf-8"))
        validated = validate_catalog_document(document)
        groups = [
            {
                "stable_key": group.stable_key,
                "display_name": group.display_name,
                "capacity": group.official_capacity,
                "policy": group.calculation_policy,
                "members": tuple(
                    (m.source_code, m.configured_source_name)
                    for m in group.memberships
                ),
            }
            for group in validated.groups
        ]
        self._catalog(today, groups)
        run = self._run()
        for index, group in enumerate(validated.groups):
            for member in group.memberships:
                self._snapshot(
                    run,
                    captured_at=self._at(today),
                    code=member.source_code,
                    sector=member.configured_source_name,
                    index=index,
                )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "44 de 47" in content
        assert "43 de 47" in content
        assert "Capacidade conhecida: 658" in content
        assert "Capacidade calculável: 626" in content
        assert "setores oficiais com" not in content

    def test_v2_3a_overcapacity_alert_remains_accessible(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        for index in range(40):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code="654",
                sector="3A Source",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"ADULT-{index:03d}",
                age_band="age_12_or_over",
            )
        self._materialize(run.pk)

        response = self._render(admin_client)
        rows = response.context["measured_groups"]
        content = response.content.decode()
        adult = next(row for row in rows if row.stable_key == "OBST-3A-ADULTO")

        assert adult.over_capacity is True
        assert adult.occupancy_percentage == Decimal("125.00")
        assert adult.exceeded_by == 8
        assert "125,00%" in content
        assert "Acima da capacidade" in content
        assert "Excedente: 8" in content

    def test_v2_exact_measurement_fallback_and_anonymous_redirect(self, admin_client, client):
        url = reverse("census:bed_status")
        anonymous = client.get(url)
        assert anonymous.status_code == 302
        assert "/login/" in anonymous.url

        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        old_run = self._run()
        self._snapshot(
            old_run,
            captured_at=self._at(today, 8),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="OLD-1",
            age_band="age_12_or_over",
        )
        self._materialize(old_run.pk)

        response = self._render(admin_client)
        assert "Enfermaria 3A – Adulto" in response.content.decode()

        new_run = self._run()
        self._snapshot(
            new_run,
            captured_at=self._at(today, 20),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="NEW-1",
            age_band="age_12_or_over",
        )
        fallback = self._render(admin_client)
        content = fallback.content.decode()
        assert "Pendente" in content
        assert "Enfermaria 3A – Adulto" not in content
        assert "OLD-1" not in content

    def test_partial_alert_exposes_only_aggregate_count_never_patient_data(self, admin_client):
        today = timezone.localdate()
        self._catalog(today, self._partitioned_3a())
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="UNKNOWN-PRONT-777",
            age_band="unknown",
        )
        self._materialize(run.pk)

        response = self._render(admin_client)
        content = response.content.decode()

        assert "Taxa pontual parcial" in content
        alert_start = content.index("Taxa pontual parcial")
        alert_end = content.index("</div>", alert_start)
        alert = content[alert_start:alert_end]
        assert "UNKNOWN-PRONT-777" not in alert
        assert "Synthetic Patient" not in alert
        assert "anos" not in alert
        assert "meses" not in alert


@pytest.mark.django_db
class TestBedSidebarLink:
    """S3: Sidebar includes link to /beds/."""

    def test_sidebar_has_leitos_link(self, admin_client):
        """Sidebar renders with 'Leitos' link pointing to /beds/."""
        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Leitos" in content
        assert "/beds/" in content


@pytest.mark.django_db
class TestBedStatusTwoRealities:
    """SOPBR-S3: /beds shows official and physical realities side by side.

    Synthetic ``occupancy-v3`` catalogs declare the algorithm explicitly; the
    physical section consumes the exact latest census with the same v3
    normalization contract (each unambiguous position once, exact duplicates
    collapsed, conflicts once without a chosen patient). Every official value
    asserted here comes from the persisted measurement, never recalculated.
    """

    @staticmethod
    def _at(local_date, hour=12):
        return timezone.make_aware(
            datetime.combine(local_date, time(hour=hour)),
            timezone.get_current_timezone(),
        )

    @staticmethod
    def _run():
        return IngestionRun.objects.create(
            intent="census_extraction", status="succeeded"
        )

    @staticmethod
    def _snapshot(
        run,
        *,
        captured_at,
        code,
        sector,
        status=BedStatus.EMPTY,
        index=0,
        patient_marker="",
        age_band=None,
        bed=None,
    ):
        return CensusSnapshot.objects.create(
            ingestion_run=run,
            captured_at=captured_at,
            setor_codigo=code,
            setor=sector,
            leito=bed if bed is not None else f"BED-{code or 'BLANK'}-{index:03d}",
            prontuario=patient_marker if status == BedStatus.OCCUPIED else "",
            nome=(
                f"Synthetic Patient {patient_marker}"
                if status == BedStatus.OCCUPIED
                else status.upper()
            ),
            especialidade="SYN",
            bed_status=status,
            age_band=(
                age_band
                if age_band is not None
                else ("not_applicable" if status != BedStatus.OCCUPIED else "unknown")
            ),
        )

    @staticmethod
    def _v3_catalog(effective_from, groups):
        catalog = CapacityCatalogVersion.objects.create(
            effective_from=effective_from,
            source_reference="synthetic v3 bed-status test catalog",
            source_sha256=(f"{effective_from:%Y%m%d}" + "d" * 64)[:64],
            schema_version="2.0",
            algorithm_version="occupancy-v3",
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
                selector = member[2] if len(member) > 2 else "all"
                CapacitySectorMembership.objects.create(
                    catalog=catalog,
                    group=group,
                    source_code=member[0],
                    configured_source_name=member[1],
                    age_selector=selector,
                )
        return catalog

    @staticmethod
    def _standard_group(*, key="A", capacity=10, members=(("100", "Sector A", "all"),)):
        return {
            "stable_key": key,
            "display_name": f"Group {key}",
            "capacity": capacity,
            "policy": CalculationPolicy.STANDARD,
            "members": members,
        }

    def _materialize(self, run_id):
        from apps.census.occupancy import materialize_occupancy_measurement

        return materialize_occupancy_measurement(run_id=run_id)

    def _render(self, admin_client):
        return admin_client.get(reverse("census:bed_status"))

    def _v3_duplicate_census(self, today):
        """7 occupied rows where one bed is an exact duplicate, plus one empty.

        Positions: 6 occupied + 1 empty; raw occupied rows 7; duplicate
        occupied rows 1; official numerator 6 over capacity 10.
        """
        self._v3_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        for index in range(6):
            self._snapshot(
                run,
                captured_at=captured_at,
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
                age_band="not_applicable",
            )
        # exact duplicate of the first row (same bed, record, name, band)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-000",
            age_band="not_applicable",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.EMPTY,
            index=7,
        )
        return run, captured_at

    def test_both_section_headings_are_simultaneously_visible(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "Capacidade oficial e ocupação" in content
        assert "Posições registradas no sistema de origem" in content

    def test_official_cards_use_v3_labels_and_persisted_values(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        measurement = response.context["measurement"]
        assert measurement.algorithm_version == "occupancy-v3"
        assert measurement.occupied_for_rate == 6
        assert measurement.official_availability == 4
        assert measurement.exceeded_by == 0
        assert measurement.occupancy_percentage == Decimal("60.00")
        assert "Capacidade oficial" in content
        assert "Ocupações consideradas na taxa" in content
        assert "Disponibilidade na capacidade oficial" in content
        assert "Excedente à capacidade" in content
        assert "Taxa oficial de ocupação" in content
        assert "60,00%" in content

    def test_total_de_leitos_and_ambiguous_labels_are_gone(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "Total de leitos" not in content
        assert "Lotação registrada no sistema legado" not in content

    def test_legacy_vacant_is_never_called_official_availability(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "saldo calculado por setor" in content.lower()
        assert "Vagos no sistema de origem" in content

    def test_duplicate_renders_one_position_and_aggregate_diagnostic(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        physical = response.context["physical"]
        measurement = response.context["measurement"]
        rec = measurement.physical_reconciliation_json
        assert physical.positions_by_status["occupied"] == 6
        assert physical.duplicate_extra_rows == 1
        assert rec["duplicate_occupied_rows"] == 1
        assert content.count("BED-100-000") == 1

    def test_conflict_renders_once_without_chosen_patient(self, admin_client):
        today = timezone.localdate()
        self._v3_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-A",
            age_band="not_applicable",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-B",
            age_band="not_applicable",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        physical = response.context["physical"]
        measurement = response.context["measurement"]
        assert physical.conflict_positions == 1
        assert measurement.position_partial is True
        assert "Conflito no sistema de origem" in content
        assert content.count("BED-100-000") == 1
        assert "Synthetic Patient SYN-A" not in content
        assert "Synthetic Patient SYN-B" not in content

    def test_physical_status_counts_close_identified_total(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        response = self._render(admin_client)
        physical = response.context["physical"]
        statuses = physical.positions_by_status
        assert physical.identified_total == (
            statuses["occupied"]
            + statuses["empty"]
            + statuses["reserved"]
            + statuses["maintenance"]
            + statuses["isolation"]
        )
        assert physical.duplicate_extra_rows == 1
        assert physical.unidentified_rows == 0

    def test_3a_physical_once_and_official_partition_twice(self, admin_client):
        today = timezone.localdate()
        self._v3_catalog(
            today,
            [
                {
                    "stable_key": "OBST-3A-ADULTO",
                    "display_name": "Enfermaria 3A – Adulto",
                    "capacity": 32,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (("654", "3A Source", "age_12_or_over"),),
                },
                {
                    "stable_key": "OBST-3A-INFANTIL",
                    "display_name": "Enfermaria 3A – Infantil",
                    "capacity": 16,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (("654", "3A Source", "under_12"),),
                },
            ],
        )
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="CHILD-1",
            age_band="under_12",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        physical = response.context["physical"]
        measured = response.context["measured_groups"]
        content = response.content.decode()
        official_keys = [row.stable_key for row in measured]
        assert "OBST-3A-ADULTO" in official_keys
        assert "OBST-3A-INFANTIL" in official_keys
        sources = [sector.source_name for sector in physical.sectors]
        assert sources.count("3A Source") == 1
        assert "Enfermaria 3A – Adulto" in content
        assert "Enfermaria 3A – Infantil" in content

    def test_co_unrated_appears_physically_with_states_and_no_official_rate(self, admin_client):
        today = timezone.localdate()
        self._v3_catalog(
            today,
            [
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstétrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO 20", "all"),),
                },
                self._standard_group(),
            ],
        )
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="20",
            sector="CO 20",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="CO-1",
            age_band="not_applicable",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="20",
            sector="CO 20",
            status=BedStatus.EMPTY,
            index=1,
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        measured = response.context["measured_groups"]
        physical = response.context["physical"]
        content = response.content.decode()
        co = next(row for row in measured if row.stable_key == "CO")
        assert co.occupancy_percentage is None
        assert co.official_availability is None
        assert "Não incluído na taxa de ocupação da unidade" in content
        co_sector = next(s for s in physical.sectors if s.source_name == "CO 20")
        assert co_sector.positions_by_status["occupied"] == 1
        assert co_sector.positions_by_status["empty"] == 1

    def test_bridge_closes_and_stays_private(self, admin_client):
        today = timezone.localdate()
        run, _ = self._v3_duplicate_census(today)
        self._materialize(run.pk)
        response = self._render(admin_client)
        measurement = response.context["measurement"]
        rec = measurement.physical_reconciliation_json
        content = response.content.decode()
        bridge = (
            rec["duplicate_occupied_rows"]
            + rec["conflict_occupied_rows"]
            + rec["unidentified_occupied_rows"]
            + rec["unknown_age_3a_rows"]
            + rec["unambiguous_occupied_outside_calculable"]
            + rec["official_numerator"]
        )
        assert bridge == rec["raw_occupied_rows"]
        start = content.index("Ponte de reconciliação")
        end = content.index("Posições registradas no sistema de origem")
        bridge_html = content[start:end]
        for marker in ("SYN-", "BED-100", "Synthetic Patient", "Sector A"):
            assert marker not in bridge_html

    def test_v3_partial_alert_labels_rate_partial_and_daily_ineligible(self, admin_client):
        today = timezone.localdate()
        self._v3_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-A",
            age_band="not_applicable",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-B",
            age_band="not_applicable",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        measurement = response.context["measurement"]
        content = response.content.decode()
        assert measurement.position_partial is True
        assert "(parcial)" in content
        assert "médias oficiais diárias" in content

    def test_v2_measurement_is_historical_without_v3_availability(self, admin_client):
        today = timezone.localdate()
        catalog = CapacityCatalogVersion.objects.create(
            effective_from=today,
            source_reference="synthetic v2 historical bed-status test catalog",
            source_sha256=(f"{today:%Y%m%d}" + "e" * 64)[:64],
            schema_version="1.0",
        )
        adult = CapacityGroupDefinition.objects.create(
            catalog=catalog,
            stable_key="OBST-3A-ADULTO",
            display_name="Enfermaria 3A – Adulto",
            official_capacity=32,
            calculation_policy=CalculationPolicy.STANDARD,
        )
        CapacitySectorMembership.objects.create(
            catalog=catalog,
            group=adult,
            source_code="654",
            configured_source_name="3A Source",
            age_selector="age_12_or_over",
        )
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        measurement = response.context["measurement"]
        content = response.content.decode()
        assert measurement.algorithm_version == "occupancy-v2"
        assert measurement.official_availability is None
        assert "Disponibilidade na capacidade oficial" not in content
        assert "Ponte de reconciliação" not in content
        assert "occupancy-v2" in content

    def test_old_measurement_is_never_reused_for_newer_census(self, admin_client):
        today = timezone.localdate()
        self._v3_catalog(today, [self._standard_group()])
        old_run = self._run()
        self._snapshot(
            old_run,
            captured_at=self._at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="OLD-1",
            age_band="not_applicable",
        )
        self._materialize(old_run.pk)
        response = self._render(admin_client)
        assert "Pendente" not in response.content.decode()

        new_run = self._run()
        self._snapshot(
            new_run,
            captured_at=self._at(today, 20),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="NEW-1",
            age_band="not_applicable",
        )
        content = self._render(admin_client).content.decode()
        assert "Pendente" in content
        assert "Group A" not in content
        assert "OLD-1" not in content

    def test_no_exact_measurement_keeps_official_pending_and_physical_visible(self, admin_client):
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="01",
            prontuario="111",
            nome="PACIENTE UM",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        content = self._render(admin_client).content.decode()
        assert "Pendente" in content
        assert "Posições registradas no sistema de origem" in content
        assert "UTI A" in content
        assert "PACIENTE UM" in content

    def test_anonymous_access_remains_redirected(self, client):
        response = client.get(reverse("census:bed_status"))
        assert response.status_code == 302
        assert "/login/" in response.url


@pytest.mark.django_db
class TestBedStatusV4ActionablePresentation:
    """MOQA-S3: v4 exact-run page with two summaries and one unit list.

    A synthetic schema 3.0 catalog declares ``occupancy-v4`` and clean source
    aliases; the page must render two aggregate summaries plus exactly one
    detailed ``Setores e posições`` list whose units are connected components
    of the group<->code graph, with every physical position once, typed
    conflicts without a winner and quality cases visible to any authenticated
    user. No official value is recalculated here and no PHI is expected
    outside the authenticated unit detail.
    """

    @staticmethod
    def _at(local_date, hour=12):
        return timezone.make_aware(
            datetime.combine(local_date, time(hour=hour)),
            timezone.get_current_timezone(),
        )

    @staticmethod
    def _run():
        return IngestionRun.objects.create(
            intent="census_extraction", status="succeeded"
        )

    @staticmethod
    def _snapshot(
        run,
        *,
        captured_at,
        code,
        sector,
        status=BedStatus.EMPTY,
        index=0,
        patient_marker="",
        age_band=None,
        bed=None,
    ):
        return CensusSnapshot.objects.create(
            ingestion_run=run,
            captured_at=captured_at,
            setor_codigo=code,
            setor=sector,
            leito=bed if bed is not None else f"BED-{code or 'BLANK'}-{index:03d}",
            prontuario=patient_marker if status == BedStatus.OCCUPIED else "",
            nome=(
                f"Synthetic Patient {patient_marker}"
                if status == BedStatus.OCCUPIED
                else status.upper()
            ),
            especialidade="SYN",
            bed_status=status,
            age_band=(
                age_band
                if age_band is not None
                else ("not_applicable" if status != BedStatus.OCCUPIED else "unknown")
            ),
        )

    @staticmethod
    def _v4_catalog(effective_from, groups):
        catalog = CapacityCatalogVersion.objects.create(
            effective_from=effective_from,
            source_reference="synthetic v4 bed-status test catalog",
            source_sha256=(f"{effective_from:%Y%m%d}" + "f" * 64)[:64],
            schema_version="3.0",
            algorithm_version="occupancy-v4",
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
                selector = member[3] if len(member) > 3 else "all"
                CapacitySectorMembership.objects.create(
                    catalog=catalog,
                    group=group,
                    source_code=member[0],
                    configured_source_name=member[1],
                    source_display_name=member[2],
                    age_selector=selector,
                )
        return catalog

    @staticmethod
    def _standard_group(
        *,
        key="A",
        capacity=10,
        members=(("100", "Sector A", "Setor A", "all"),),
    ):
        return {
            "stable_key": key,
            "display_name": f"Group {key}",
            "capacity": capacity,
            "policy": CalculationPolicy.STANDARD,
            "members": members,
        }

    @staticmethod
    def _partitioned_3a():
        return [
            {
                "stable_key": "OBST-3A-ADULTO",
                "display_name": "Enfermaria 3A – Adulto",
                "capacity": 32,
                "policy": CalculationPolicy.STANDARD,
                "members": (
                    (
                        "654",
                        "3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS",
                        "Enfermaria 3A Obstetrícia Clínica",
                        "age_12_or_over",
                    ),
                ),
            },
            {
                "stable_key": "OBST-3A-INFANTIL",
                "display_name": "Enfermaria 3A – Infantil",
                "capacity": 16,
                "policy": CalculationPolicy.STANDARD,
                "members": (
                    (
                        "654",
                        "3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS",
                        "Enfermaria 3A Obstetrícia Clínica",
                        "under_12",
                    ),
                ),
            },
        ]

    def _materialize(self, run_id):
        from apps.census.occupancy import materialize_occupancy_measurement

        return materialize_occupancy_measurement(run_id=run_id)

    def _render(self, admin_client):
        return admin_client.get(reverse("census:bed_status"))

    # ---- R3: two aggregate summaries and exactly one detailed list ----

    def test_two_aggregate_heads_and_one_detailed_section(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
            age_band="age_12_or_over",
        )
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "Capacidade oficial e ocupação" in content
        assert "Posições registradas no sistema de origem" in content
        assert "Setores e posições" in content

    def test_no_tabs_and_no_second_long_list(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
            age_band="age_12_or_over",
        )
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert content.count("Setores e posições") == 1
        assert 'data-bs-toggle="tab"' not in content
        assert "group-detail-" not in content
        assert "sector-detail-" not in content

    # ---- R6: terminology ----

    def test_origin_terminology_replaces_legacy(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-A",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-B",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "sistema de origem" in content
        assert "Conflitos no sistema de origem" in content
        assert "legado" not in content

    # ---- R2: clean alias primary and raw name subordinate ----

    def test_clean_alias_primary_and_raw_subordinate(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(
            today,
            [
                {
                    "stable_key": "GASTRO",
                    "display_name": "Enfermaria Gastroenterologia",
                    "capacity": 12,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (
                        (
                            "2702",
                            "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
                            "Enfermaria Gastroenterologia",
                            "all",
                        ),
                    ),
                },
            ],
        )
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="2702",
            sector="0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-2702",
            age_band="not_applicable",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        units = response.context["units"]
        assert len(units) == 1
        assert units[0].sources[0].alias == "Enfermaria Gastroenterologia"
        assert units[0].sources[0].raw_name == (
            "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS"
        )
        assert "Enfermaria Gastroenterologia" in content
        assert "Nome no sistema de origem" in content
        assert "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS" in content
        assert content.index("Enfermaria Gastroenterologia") < content.index(
            "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS"
        )

    def test_legacy_catalog_without_alias_uses_configured_name_fallback(self, admin_client):
        today = timezone.localdate()
        catalog = CapacityCatalogVersion.objects.create(
            effective_from=today,
            source_reference="synthetic v3 alias-fallback bed-status test catalog",
            source_sha256=(f"{today:%Y%m%d}" + "a9" * 32)[:64],
            schema_version="2.0",
            algorithm_version="occupancy-v3",
        )
        group = CapacityGroupDefinition.objects.create(
            catalog=catalog,
            stable_key="A",
            display_name="Group A",
            official_capacity=10,
            calculation_policy=CalculationPolicy.STANDARD,
        )
        CapacitySectorMembership.objects.create(
            catalog=catalog,
            group=group,
            source_code="100",
            configured_source_name="Sector Raw A",
        )
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector Raw A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-A",
            age_band="not_applicable",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        units = response.context["units"]
        assert len(units) == 1
        assert units[0].title == "Group A"
        assert units[0].sources[0].alias == "Sector Raw A"
        assert units[0].sources[0].raw_name is None
        assert "Nome no sistema de origem" not in content

    # ---- R1: connected-component graph units ----

    def test_one_to_one_component_unit(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(
            today,
            [
                {
                    "stable_key": "GASTRO",
                    "display_name": "Enfermaria Gastroenterologia",
                    "capacity": 12,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (
                        (
                            "2702",
                            "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
                            "Enfermaria Gastroenterologia",
                            "all",
                        ),
                    ),
                },
            ],
        )
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="2702",
            sector="0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-2702",
            age_band="not_applicable",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        units = response.context["units"]
        assert len(units) == 1
        unit = units[0]
        assert unit.title == "Enfermaria Gastroenterologia"
        assert [row.stable_key for row in unit.official_rows] == ["GASTRO"]
        assert [source.source_code for source in unit.sources] == ["2702"]
        assert len(unit.sources[0].positions) == 1
        assert unit.sources[0].positions_by_status["occupied"] == 1

    def test_cardio_shared_group_two_sources_capacity_once(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(
            today,
            [
                {
                    "stable_key": "ENF-2B-CARD",
                    "display_name": "Enfermaria 2B Cardio",
                    "capacity": 15,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (
                        ("719", "0 N - CARDIOCLINICA", "Cardioclínica", "all"),
                        (
                            "2156",
                            "2 7 - 2B - CARDIO - HGRS",
                            "Enfermaria 2B Cardio",
                            "all",
                        ),
                    ),
                },
            ],
        )
        run = self._run()
        for index, code in enumerate(["719", "2156"]):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code=code,
                sector=f"Sector {code}",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{code}",
                age_band="not_applicable",
            )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        units = response.context["units"]
        assert len(units) == 1
        unit = units[0]
        assert unit.title == "Enfermaria 2B Cardio"
        assert [source.source_code for source in unit.sources] == ["2156", "719"]
        assert content.count("Capacidade: 15") == 1
        assert "Cardioclínica" in content
        assert "Enfermaria 2B Cardio" in content

    def test_3a_two_groups_one_source_physical_once(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, self._partitioned_3a())
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
            bed="3A-01",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="CHILD-1",
            age_band="under_12",
            bed="3A-02",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        units = response.context["units"]
        assert len(units) == 1
        unit = units[0]
        assert unit.title == "Enfermaria 3A Obstetrícia Clínica"
        assert [row.stable_key for row in unit.official_rows] == [
            "OBST-3A-ADULTO",
            "OBST-3A-INFANTIL",
        ]
        assert [source.source_code for source in unit.sources] == ["654"]
        assert content.count("3A-01") == 1
        assert content.count("3A-02") == 1
        assert content.count("Capacidade: 32") == 1
        assert content.count("Capacidade: 16") == 1
        assert "Enfermaria 3A – Adulto" in content
        assert "Enfermaria 3A – Infantil" in content

    def test_co_unrated_many_sources_with_clean_aliases(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(
            today,
            [
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstétrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (
                        ("20", "0 T - CENTRO OBSTETRICO (CO) - HGRS", "Centro Obstétrico", "all"),
                        (
                            "1110",
                            "0 T - SALA DE OBSERVACAO GINECOLOGICA",
                            "Observação Ginecológica",
                            "all",
                        ),
                        (
                            "1112",
                            "0 T - SALA DE MEDICACAO - OBSERVACAO CO",
                            "Sala de Medicação (CO)",
                            "all",
                        ),
                        (
                            "1114",
                            "0 T - SALA DE ESTABILIZAÇÃO CO (RN)",
                            "Estabilização RN (CO)",
                            "all",
                        ),
                        (
                            "1116",
                            "0 T - INTERNAÇÃO CENTRO OBSTETRICO",
                            "Internação Centro Obstétrico",
                            "all",
                        ),
                    ),
                },
            ],
        )
        run = self._run()
        codes = ("20", "1110", "1112", "1114", "1116")
        for index, code in enumerate(codes):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code=code,
                sector=f"CO {code}",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-CO-{index:03d}",
                age_band="not_applicable",
            )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        units = response.context["units"]
        assert len(units) == 1
        unit = units[0]
        assert unit.title == "Centro Obstétrico"
        assert [source.source_code for source in unit.sources] == sorted(codes)
        assert content.count("Capacidade não cadastrada") == 1
        assert "Observação Ginecológica" in content
        assert "Sala de Medicação (CO)" in content
        assert "posição válida fora do escopo da taxa oficial" in content

    def test_unmapped_source_gets_warning_unit(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-A",
            age_band="not_applicable",
        )
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="777",
            sector="Setor Fantasma",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="SYN-777",
            age_band="not_applicable",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        units = response.context["units"]
        assert len(units) == 2
        unit = next(unit for unit in units if unit.is_unmapped)
        assert unit.title == "Setor Fantasma"
        assert unit.official_rows == []
        assert content.count("Capacidade: 10") == 1
        assert "sem mapeamento no catálogo" in content
        assert "Setor Fantasma" in content

    # ---- R4: one physical position once ----

    def test_exact_duplicate_renders_once_and_consolidated_label(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        for index in range(2):
            self._snapshot(
                run,
                captured_at=captured_at,
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker="SYN-DUP",
                age_band="age_12_or_over",
                bed="BED-DUP-01",
            )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        measurement = response.context["measurement"]
        assert measurement.quality_warning is False
        assert content.count("BED-DUP-01") == 1
        assert "Linhas duplicadas consolidadas" in content
        assert "posição contada uma vez" in content

    # ---- R7: non-authoritative quality details for authenticated users ----

    def test_occupant_conflict_counted_with_non_authoritative_alternatives(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-A",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-B",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        measurement = response.context["measurement"]
        units = response.context["units"]
        source = units[0].sources[0]
        assert measurement.quality_warning is True
        assert measurement.occupied_for_rate == 1
        assert len(source.positions) == 1
        assert source.positions[0].note is not None
        assert len(source.conflicts) == 1
        conflict = source.conflicts[0]
        assert conflict.conflict_type == "occupant"
        assert conflict.counted is True
        assert len(conflict.alternatives) == 2
        assert content.count("registro divergente — não autoritativo") == 2
        assert "Synthetic Patient REC-A" in content
        assert "Synthetic Patient REC-B" in content

    def test_status_conflict_shows_alternatives_without_winner(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-ST",
            age_band="age_12_or_over",
            bed="BED-ST-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.EMPTY,
            index=1,
            bed="BED-ST-01",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        measurement = response.context["measurement"]
        units = response.context["units"]
        source = units[0].sources[0]
        assert measurement.occupied_for_rate == 0
        assert source.positions == []
        assert len(source.conflicts) == 1
        conflict = source.conflicts[0]
        assert conflict.conflict_type == "status"
        assert conflict.counted is False
        assert len(conflict.alternatives) == 2
        assert "não computadas por status ambíguo" in content
        assert "Synthetic Patient REC-ST" in content
        assert "Ocupado" in content
        assert "Vago" in content

    def test_age_conflict_not_assigned_with_alternatives(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, self._partitioned_3a())
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-X",
            age_band="age_12_or_over",
            bed="BED-AGE-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="CHILD-X",
            age_band="under_12",
            bed="BED-AGE-01",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        measurement = response.context["measurement"]
        units = response.context["units"]
        source = units[0].sources[0]
        assert measurement.occupied_for_rate == 0
        assert source.positions == []
        assert len(source.conflicts) == 1
        conflict = source.conflicts[0]
        assert conflict.conflict_type == "age"
        assert conflict.counted is False
        assert len(conflict.alternatives) == 2
        assert "não atribuída a grupo etário" in content
        assert "Synthetic Patient ADULT-X" in content
        assert "Synthetic Patient CHILD-X" in content
        assert "12 anos ou mais" in content
        assert "Menor de 12 anos" in content

    def test_occupied_without_bed_actionable_not_position(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="NOBED-1",
            age_band="age_12_or_over",
            bed="",
        )
        self._materialize(run.pk)
        response = self._render(admin_client)
        content = response.content.decode()
        measurement = response.context["measurement"]
        physical = response.context["physical"]
        assert measurement.occupied_for_rate == 0
        assert physical.unidentified_rows == 1
        assert physical.unidentified_occupied_rows == 1
        assert physical.positions_by_status["occupied"] == 0
        assert "Linhas ocupadas sem posição" in content
        assert "não computadas por ausência de posição" in content
        assert "Synthetic Patient NOBED-1" in content

    # ---- R5/R8: treatment and eligibility ----

    def test_treatment_labels_and_out_of_rate_wording(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(
            today,
            [
                self._standard_group(),
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstétrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (
                        ("20", "0 T - CENTRO OBSTETRICO (CO) - HGRS", "Centro Obstétrico", "all"),
                    ),
                },
                {
                    "stable_key": "PEND",
                    "display_name": "Grupo Pendente",
                    "capacity": 10,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (
                        ("900", "Sector Pending", "Setor Pendente", "all"),
                    ),
                },
            ],
        )
        run = self._run()
        for index, (code, sector) in enumerate(
            [
                ("100", "Sector A"),
                ("20", "CO 20"),
                ("900", "Sector Pending"),
                ("777", "Setor Fantasma"),
            ]
        ):
            self._snapshot(
                run,
                captured_at=self._at(today),
                code=code,
                sector=sector,
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-T{index:03d}",
                age_band="not_applicable",
            )
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "Como as ocupações foram tratadas" in content
        assert "posição válida fora do escopo da taxa oficial" in content
        assert "sem mapeamento no catálogo" in content
        assert "cálculo pendente" in content

    def test_v4_warning_eligible_with_reservations_badge(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-A",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-B",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        assert "com ressalvas de qualidade" in content
        assert "Ocupações consideradas" in content
        assert "continua elegível" in content
        assert "estatísticas diárias" in content
        assert "(parcial)" not in content
        assert "médias oficiais diárias" not in content

    # ---- R9: authentication and exact-run ----

    def test_non_staff_authenticated_user_sees_quality_details(self, client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-A",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-B",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._materialize(run.pk)
        user = get_user_model().objects.create_user(
            username="medico", password="synthetic-password-1"
        )
        assert user.is_staff is False
        client.force_login(user)
        response = client.get(reverse("census:bed_status"))
        content = response.content.decode()
        assert response.status_code == 200
        assert "Synthetic Patient REC-A" in content
        assert "Synthetic Patient REC-B" in content
        assert "registro divergente — não autoritativo" in content

    def test_anonymous_redirected(self, client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        self._snapshot(
            run,
            captured_at=self._at(today),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="REC-A",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._materialize(run.pk)
        response = client.get(reverse("census:bed_status"))
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_exact_run_pending_never_reuses_older_measurement(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(
            today,
            [
                {
                    "stable_key": "GASTRO",
                    "display_name": "Enfermaria Gastroenterologia",
                    "capacity": 12,
                    "policy": CalculationPolicy.STANDARD,
                    "members": (
                        (
                            "2702",
                            "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
                            "Enfermaria Gastroenterologia",
                            "all",
                        ),
                    ),
                },
            ],
        )
        old_run = self._run()
        self._snapshot(
            old_run,
            captured_at=self._at(today, 8),
            code="2702",
            sector="0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="OLD-1",
            age_band="not_applicable",
        )
        self._materialize(old_run.pk)

        new_run = self._run()
        self._snapshot(
            new_run,
            captured_at=self._at(today, 20),
            code="2702",
            sector="Setor B",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="NEW-1",
            age_band="not_applicable",
        )
        response = self._render(admin_client)
        content = response.content.decode()
        assert "Pendente" in content
        assert "Enfermaria Gastroenterologia" not in content
        assert "Setor B" in content
        assert "Synthetic Patient NEW-1" in content
        assert "OLD-1" not in content

    # ---- R5 privacy: aggregate bridge never nominal ----

    def test_aggregate_bridge_never_exposes_nominal_markers(self, admin_client):
        today = timezone.localdate()
        self._v4_catalog(today, [self._standard_group()])
        run = self._run()
        captured_at = self._at(today)
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-A",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-B",
            age_band="age_12_or_over",
            bed="BED-CONF-01",
        )
        self._snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="NOBED-1",
            age_band="age_12_or_over",
            bed="",
        )
        self._materialize(run.pk)
        content = self._render(admin_client).content.decode()
        start = content.index("Como as ocupações foram tratadas")
        end = content.index("Setores e posições")
        bridge_html = content[start:end]
        for marker in ("SYN-", "BED-", "Synthetic Patient", "Sector A"):
            assert marker not in bridge_html
