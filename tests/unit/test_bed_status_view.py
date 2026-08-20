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
        adult = groups["OBST-3A-ADULTO"]
        auxiliary = next(
            (row for row in rows if "classificação etária" in row.display_name),
            None,
        )

        assert auxiliary is not None
        assert "classificação etária" in content
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
