from __future__ import annotations

import pytest
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot


@pytest.mark.django_db
class TestBedStatus:
    def test_choices_exist(self):
        """All five bed status choices are defined."""
        assert BedStatus.OCCUPIED == "occupied"
        assert BedStatus.EMPTY == "empty"
        assert BedStatus.MAINTENANCE == "maintenance"
        assert BedStatus.RESERVED == "reserved"
        assert BedStatus.ISOLATION == "isolation"

    def test_labels(self):
        """Labels are in Portuguese."""
        assert BedStatus.OCCUPIED.label == "Ocupado"
        assert BedStatus.EMPTY.label == "Vago"
        assert BedStatus.MAINTENANCE.label == "Em Manutenção"
        assert BedStatus.RESERVED.label == "Reservado"
        assert BedStatus.ISOLATION.label == "Isolamento"


@pytest.mark.django_db
class TestCensusSnapshot:
    def test_create_occupied_bed(self):
        """Can create a snapshot row for an occupied bed."""
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI GERAL ADULTO 1 - HGRS",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        assert snap.pk is not None
        assert snap.bed_status == BedStatus.OCCUPIED
        assert "14160147" in str(snap)
        assert "UTI" in str(snap)

    def test_create_empty_bed(self):
        """Can create a snapshot row for an empty bed."""
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI GERAL ADULTO 1 - HGRS",
            leito="UG09I",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert snap.prontuario == ""
        assert snap.bed_status == BedStatus.EMPTY

    def test_create_all_statuses(self):
        """Can create snapshots with all five statuses."""
        statuses = list(BedStatus.values)
        for status in statuses:
            snap = CensusSnapshot.objects.create(
                captured_at=timezone.now(),
                setor="TEST",
                leito=f"BED-{status}",
                prontuario="123" if status == "occupied" else "",
                nome="TEST" if status == "occupied" else status.upper(),
                especialidade="TST",
                bed_status=status,
            )
            assert snap.bed_status == status

    def test_ordering_by_captured_at_desc(self):
        """Default ordering is by captured_at descending."""
        _old = CensusSnapshot.objects.create(
            captured_at=timezone.now() - timezone.timedelta(hours=1),
            setor="A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        new = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        qs = CensusSnapshot.objects.all()
        assert qs[0].pk == new.pk

    def test_filter_by_setor(self):
        """Can filter by setor."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="ENFARIA B",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert CensusSnapshot.objects.filter(setor="UTI A").count() == 1

    def test_filter_by_prontuario(self):
        """Can filter by prontuario."""
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="99999",
            nome="FULANO",
            especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="02",
            prontuario="",
            nome="VAZIO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert CensusSnapshot.objects.filter(prontuario="99999").count() == 1

    def test_fk_to_ingestion_run_nullable(self):
        """ingestion_run FK can be null."""
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="A",
            leito="01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert snap.ingestion_run is None
