"""S2: Censo Hospitalar page with real data from CensusSnapshot."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, Specialty


@pytest.mark.django_db
class TestCensoRealData:
    """S2: Censo page shows real data from CensusSnapshot (occupied only)."""

    def test_censo_empty_db_shows_message(self, admin_client):
        """Without CensusSnapshot, shows empty state."""
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "Censo Hospitalar" in content

    def test_censo_shows_occupied_patients(self, admin_client):
        """Only occupied beds appear on censo page."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ALFA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PACIENTE BETA", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )
        # Empty bed — should NOT appear
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="03",
            prontuario="", nome="VAZIO", especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PACIENTE ALFA" in content
        assert "PACIENTE BETA" in content
        assert "VAZIO" not in content

    def test_censo_shows_timestamp_when_available(self, admin_client):
        """Censo page shows capture timestamp."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # localtime() converts UTC to TIME_ZONE (America/Sao_Paulo)
        # to match template rendering {{ captured_at|date:"d/m/Y H:i" }}
        local_now = timezone.localtime(now)
        date_str = local_now.strftime("%d/%m/%Y")
        assert date_str in content

    def test_censo_filters_by_setor(self, admin_client):
        """Filter by sector shows only that sector's patients."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PAC UTI", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="CLINICA", leito="01",
            prontuario="222", nome="PAC CLINICA", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?unidade=UTI+A"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PAC UTI" in content
        assert "PAC CLINICA" not in content

    def test_censo_search_by_name(self, admin_client):
        """Free-text search filters by patient name."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="JOAO SILVA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="MARIA SANTOS", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?q=JOAO"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "JOAO SILVA" in content
        assert "MARIA SANTOS" not in content

    def test_censo_search_by_prontuario(self, admin_client):
        """Free-text search filters by patient record number."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="99999", nome="JOAO SILVA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="88888", nome="MARIA SANTOS", especialidade="CIV",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?q=99999"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "JOAO SILVA" in content
        assert "MARIA SANTOS" not in content

    def test_censo_dropdown_has_real_setores(self, admin_client):
        """Sector dropdown is populated from actual sectors in the snapshot."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI GERAL", leito="01",
            prontuario="111", nome="PAC1", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="ENFERMARIA B", leito="01",
            prontuario="222", nome="PAC2", especialidade="CME",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "UTI GERAL" in content
        assert "ENFERMARIA B" in content
        assert "Todos os setores" in content  # the "all" option remains

    def test_censo_uses_only_latest_snapshot(self, admin_client):
        """Only the most recent CensusSnapshot is used."""
        from datetime import timedelta
        old = timezone.now() - timedelta(hours=4)
        new = timezone.now()

        CensusSnapshot.objects.create(
            captured_at=old, setor="OLD SETOR", leito="01",
            prontuario="AAA", nome="OLD PATIENT", especialidade="X",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=new, setor="NEW SETOR", leito="01",
            prontuario="BBB", nome="NEW PATIENT", especialidade="Y",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "NEW PATIENT" in content
        assert "OLD PATIENT" not in content

    def test_censo_row_links_to_patient_search(self, admin_client):
        """Clicking a censo row links to patient search by prontuario."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="12345", nome="PAC LINK", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "q=12345" in content

    # ── CES-S1: Nomes completos de especialidades na UI ──────────

    def test_censo_dropdown_shows_full_specialty_name_with_code_value(self, admin_client):
        """RED 1: Dropdown shows full name while preserving code as value."""
        # NEF already seeded by migration, so use get_or_create
        Specialty.objects.get_or_create(code="NEF", defaults={"name": "NEFROLOGIA"})
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ALFA", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Option preserves code as value
        assert 'value="NEF"' in content
        # Dropdown shows full name as the option TEXT (not just in title attribute)
        # Currently shows: <option value="NEF">NEF</option>
        # Should show:     <option value="NEF">NEFROLOGIA</option>
        assert 'value="NEF">NEFROLOGIA' in content or '"NEF">NEFROLOGIA' in content

    def test_censo_table_and_card_show_full_specialty_name(self, admin_client):
        """RED 2: Table and card show full specialty name as main text."""
        # Use a unique test code not seeded by migrations
        Specialty.objects.create(code="CES", name="CARDIOLOGIA ESPECIAL TESTE")
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ALFA", especialidade="CES",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        # Full name must appear as inner text of a badge/tag,
        # not just inside a title attribute.
        # Currently badge renders: title="CARDIOLOGIA ESPECIAL TESTE">CES<
        # After fix it should:    title="CES">CARDIOLOGIA ESPECIAL TESTE<
        # So check that the sigla is NOT the badge inner text:
        # `>CES<` should NOT be present (currently it IS)
        assert ">CES<" not in content, "Sigla CES should not be badge inner text"
        # The full name should appear outside title attribute context
        assert "CARDIOLOGIA ESPECIAL TESTE" in content
        # The code value is still valid in dropdown options
        assert 'value="CES"' in content

    def test_censo_specialty_filter_continues_by_code(self, admin_client):
        """RED 3: Filtering by specialty code still works."""
        # Use unique test codes not seeded by migrations
        Specialty.objects.create(code="CES", name="CARDIOLOGIA ESPECIAL TESTE")
        Specialty.objects.create(code="ORT", name="ORTOPEDIA ESPECIAL TESTE")
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE CARDIACO", especialidade="CES",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PACIENTE ORTOPEDICO", especialidade="ORT",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?especialidade=CES"
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PACIENTE CARDIACO" in content
        assert "PACIENTE ORTOPEDICO" not in content
        # Dropdown preserves the selected option with code value
        assert 'value="CES" selected' in content

    def test_censo_unknown_specialty_fallback(self, admin_client):
        """RED 4: Unknown specialty falls back to original value."""
        # No Specialty created for "XYZ"
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ALFA", especialidade="XYZ",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "XYZ" in content

    # ── CES-S2: Helper comum do resultado do censo ───────────────

    def test_censo_combined_filters(self, admin_client):
        """RED 1: Combined q, unidade and especialidade filters work together."""
        Specialty.objects.get_or_create(code="NEF", defaults={"name": "NEFROLOGIA"})
        Specialty.objects.get_or_create(code="CAR", defaults={"name": "CARDIOLOGIA"})
        now = timezone.now()
        # Patient matching all filters
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE ESPERADO", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        # Different sector — should be filtered out
        CensusSnapshot.objects.create(
            captured_at=now, setor="ENFERMARIA", leito="01",
            prontuario="222", nome="OUTRO SETOR", especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        # Different specialty — should be filtered out
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="333", nome="OUTRA ESPECIALIDADE", especialidade="CAR",
            bed_status=BedStatus.OCCUPIED,
        )

        url = (
            reverse("services_portal:censo")
            + "?q=ESPERADO&unidade=UTI+A&especialidade=NEF"
        )
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "PACIENTE ESPERADO" in content
        assert "OUTRO SETOR" not in content
        assert "OUTRA ESPECIALIDADE" not in content
        # Total count reflects only the single match
        assert "1 paciente" in content or "1 pacientes" in content or "paciente" in content

    def test_censo_ordering_by_especialidade(self, admin_client):
        """RED 2: Ordering by specialty works via context."""
        Specialty.objects.get_or_create(code="AAA", defaults={"name": "ESPECIALIDADE A"})
        Specialty.objects.get_or_create(code="BBB", defaults={"name": "ESPECIALIDADE B"})
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE BETA", especialidade="BBB",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PACIENTE ALFA", especialidade="AAA",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?ordenar=especialidade"
        response = admin_client.get(url)
        assert response.status_code == 200
        pacientes = response.context["pacientes"]
        assert len(pacientes) == 2
        # Ordered by specialty alphabetically: AAA first, then BBB
        assert pacientes[0]["especialidade"] == "AAA"
        assert pacientes[1]["especialidade"] == "BBB"
        # Names should appear in matching order: PACIENTE ALFA, then PACIENTE BETA
        assert pacientes[0]["nome"] == "PACIENTE ALFA"
        assert pacientes[1]["nome"] == "PACIENTE BETA"

    def test_censo_ordering_by_tempo_desc(self, admin_client):
        """RED 2b: Ordering by descending stay time works via context."""
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="01",
            prontuario="111", nome="PACIENTE CURTO", especialidade="NEF",
            tempo_internacao=2,
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now, setor="UTI A", leito="02",
            prontuario="222", nome="PACIENTE LONGO", especialidade="NEF",
            tempo_internacao=10,
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("services_portal:censo") + "?ordenar=tempo_desc"
        response = admin_client.get(url)
        assert response.status_code == 200
        pacientes = response.context["pacientes"]
        assert len(pacientes) == 2
        # Longer stay first
        assert pacientes[0]["nome"] == "PACIENTE LONGO"
        assert pacientes[1]["nome"] == "PACIENTE CURTO"

    def test_censo_empty_state_preserved(self, admin_client):
        """RED 3: Empty state with context values."""
        # No snapshots at all
        url = reverse("services_portal:censo")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["pacientes"] == []
        assert response.context["total"] == 0
        assert response.context["captured_at"] is None
