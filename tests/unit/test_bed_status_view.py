"""Tests for bed_status_view (Slice S6)."""

from __future__ import annotations

import json
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import pytest
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

        assert "Lotação registrada no sistema legado" in content

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
