"""Tests for SCOH-S1: versioned sector capacity catalog publication."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.census import capacity_catalog as catalog_module
from apps.census.capacity_catalog import (
    CatalogConflictError,
    CatalogValidationError,
    activate_sector_capacity_catalog,
    validate_catalog_document,
)
from apps.census.models import (
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
)

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

V3_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "census"
    / "data"
    / "sector_capacity_catalog_v3.json"
)

V4_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "census"
    / "data"
    / "sector_capacity_catalog_v4.json"
)

# C1: nomes exatos esperados no sistema fonte (CensusSnapshot.setor).
EXPECTED_SOURCE_NAMES = {
    "751": "0 - SALA DE PROCEDIMENTO ADULTO HGRS",
    "728": "0 0 - CHD - HGRS",
    "721": "0 L - INTERMEDIARIO ALA C - HGRS",
    "719": "0 N - CARDIOCLINICA",
    "720": "0 S - INTERMEDIÁRIO ALA B - HGRS",
    "20": "0 T - CENTRO OBSTETRICO (CO) - HGRS",
    "733": "0 T - CRPA - HGRS",
    "1522": "0 T - CRPA - HH",
    "2702": "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS",
    "1116": "0 T - INTERNAÇÃO CENTRO OBSTETRICO",
    "731": "0 T - SALA AMARELA ADULTO HGRS",
    "738": "0 T - SALA AMARELA PED HGRS",
    "1114": "0 T - SALA DE ESTABILIZAÇÃO CO (RN)",
    "1112": "0 T - SALA DE MEDICACAO - OBSERVACAO CO",
    "1002": "0 T - SALA DE MEDICACAO PED HGRS",
    "954": "0 T - SALA DE OBSERVACAO ADULTO HGRS",
    "1110": "0 T - SALA DE OBSERVACAO GINECOLOGICA",
    "747": "0 T - SALA DE OBSERVACAO PED HGRS",
    "745": "0 T - SALA LARANJA ADULTO HGRS",
    "1004": "0 T - SALA LARANJA PED HGRS",
    "729": "0 T - SALA VERMELHA ADULTO HGRS",
    "732": "0 T - SALA VERMELHA PED HGRS",
    "637": "0 T - UNIDADE DE AVC - HGRS",
    "628": "0 T - UTI CARDIOVASCULAR - HGRS",
    "630": "0 T - UTI CIRÚRGICA - HGRS",
    "633": "0 T - UTI GERAL ADULTO 1 - HGRS",
    "634": "0 T - UTI GERAL ADULTO 2 - HGRS",
    "629": "0 T - UTI NEUROLÓGICA - HGRS",
    "631": "0 T - UTI PEDIATRICA - HGRS",
    "640": "1 6 - 1A - CIRURGIA GERAL - HGRS",
    "642": "1 7 - 1B - HGRS",
    "644": "1 8 - 1C - CIRURGIAS ELETIVAS - HGRS",
    "2155": "2 6 - 2A - CLINICA ISOLAMENTO",
    "643": "2 6 - 2A - ONCOHEMATO - HGRS",
    "2156": "2 7 - 2B - CARDIO - HGRS",
    "651": "2 7 - 2B - NEUROCLINICA - HGRS",
    "652": "2 8 - 2C - CLINICA MÉDICA - HGRS",
    "2158": "2 8 - 2C - ENDOCRINO - HGRS",
    "654": "3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS",
    "653": "3 7 - 3B - OBSTETRÍCIA CIRÚRGICA - HGRS",
    "655": "3 8 - 3C - UNID. CUIDADOS INTERM. NEONATAL CANGURU (UCINCA) - HGRS",
    "635": "3 8 - 3C - UNID. CUIDADOS INTERM. NEONATAL CONV. (UCINCO) - HGRS",
    "636": "3 8 - 3C - UTI NEONATAL (UTIN) - HGRS",
    "656": "4 6 - 4A - ONCOHEMATOLOGIA - HGRS",
    "1926": "4 6 - UTI ONCOHEMATO - HGRS",
    "658": "4 7 - 4B - NEUROCIRURGIA - HGRS",
    "659": "4 8 - 4C - CLINICA MÉDICA PEDIÁTRICA - HGRS",
}

# C1: rótulos resumidos aprovados para exibição (correspondência oficial).
EXPECTED_DISPLAY_NAMES = {
    "CHD": "CHD",
    "GASTRO": "Enfermaria Gastroenterologia",
    "UAVC": "Unidade de AVC",
    "UTI-CARDIO": "UTI Cardiovascular",
    "UTI-CIR": "UTI Cirúrgica",
    "UTI-G1": "UTI Geral Adulto 1",
    "UTI-G2": "UTI Geral Adulto 2",
    "UTI-NEURO": "UTI Neurológica",
    "UTI-PED": "UTI Pediátrica",
    "UTI-NEO": "UTI Neonatal",
    "UTI-ONCO": "UTI Oncohematologia",
    "UCINCA": "Cuidado Intermediário Neonatal Canguru",
    "UCINCO": "Cuidado Intermediário Neonatal Convencional",
    "INT-B": "Intermediário Ala B",
    "INT-C": "Intermediário Ala C",
    "ENF-1A": "Enfermaria 1A Cirurgia Geral",
    "ENF-1B": "Enfermaria 1B",
    "ENF-1C": "Enfermaria 1C Cirurgias Eletivas",
    "ENF-2A-HEMA": "Enfermaria 2A Oncohemato",
    "ENF-2A-ISO": "Enfermaria 2A Isolamento",
    "ENF-2B-CARD": "Cardioclinica / Enfermaria 2B Cardio",
    "ENF-2B-NEURO": "Enfermaria 2B Neuroclínica",
    "ENF-2C-CLIN": "Enfermaria 2C Clínica Médica",
    "ENF-2C-ENDO": "Enfermaria 2C Endócrino",
    "OBST-3A": "Enfermaria 3A Obstetrícia Clínica",
    "OBST-3B": "Enfermaria 3B Obstetrícia Cirúrgica",
    "ENF-4A": "Enfermaria 4A Oncohematologia",
    "ENF-4B": "Enfermaria 4B Neurocirurgia",
    "ENF-4C": "Enfermaria 4C Pediatria",
    "EM-ADULTO-AMAR": "Sala Amarela Adulto",
    "EM-ADULTO-LAR": "Sala Laranja Adulto",
    "EM-ADULTO-VERM": "Sala Vermelha Adulto",
    "EM-ADULTO-PROC": "Sala de Procedimento Adulto",
    "EM-ADULTO-OBS": "Sala de Observação Adulto",
    "EM-PED-AMAR": "Sala Amarela Pediátrica",
    "EM-PED-LAR": "Sala Laranja Pediátrica",
    "EM-PED-VERM": "Sala Vermelha Pediátrica",
    "EM-PED-OBS": "Sala de Observação Pediátrica",
    "CO": "Centro Obstétrico",
    "UNRATED-CRPA-HGRS": "CRPA HGRS",
    "UNRATED-CRPA-HOMEM": "CRPA Hospital do Homem",
    "UNRATED-MED-PED": "Sala de Medicação Pediátrica",
}


def _set_nested(document: dict, path: list, value: object) -> None:
    """Set a value at a nested path (int indexes lists)."""
    node = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _future_date(days: int = 1) -> str:
    return (timezone.localdate() + timedelta(days=days)).isoformat()


def _write_document(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _valid_document() -> dict:
    return {
        "schema_version": "1.0",
        "source_reference": "test",
        "groups": [
            {
                "stable_key": "A",
                "display_name": "Sector A",
                "official_capacity": 10,
                "calculation_policy": CalculationPolicy.STANDARD,
                "source_codes": [
                    {
                        "source_code": "100",
                        "configured_source_name": "Sector A",
                    }
                ],
            },
            {
                "stable_key": "B",
                "display_name": "Sector B",
                "official_capacity": 5,
                "calculation_policy": CalculationPolicy.STANDARD,
                "source_codes": [
                    {
                        "source_code": "200",
                        "configured_source_name": "Sector B",
                    }
                ],
            },
        ],
    }


def _initial_document() -> dict:
    return json.loads(INITIAL_CATALOG.read_text(encoding="utf-8"))


def _corrected_document() -> dict:
    return json.loads(CORRECTED_CATALOG.read_text(encoding="utf-8"))


def _v3_document() -> dict:
    return json.loads(V3_CATALOG.read_text(encoding="utf-8"))


def _v4_document() -> dict:
    return json.loads(V4_CATALOG.read_text(encoding="utf-8"))


def _alias_document() -> dict:
    """Minimal schema 3.0 document with a clean alias on every membership."""
    document = _valid_document()
    document["schema_version"] = "3.0"
    document["occupancy_algorithm_version"] = "occupancy-v4"
    for group in document["groups"]:
        for membership in group["source_codes"]:
            membership["source_display_name"] = (
                f"Setor {membership['source_code']}"
            )
    return document


def _partitioned_alias_document() -> dict:
    """Schema 3.0 partitioned document with one shared physical alias."""
    document = _partitioned_document()
    document["schema_version"] = "3.0"
    document["occupancy_algorithm_version"] = "occupancy-v4"
    for group in document["groups"]:
        for membership in group["source_codes"]:
            membership["source_display_name"] = (
                "Setor Particionado"
                if membership["source_code"] == "654"
                else f"Setor {membership['source_code']}"
            )
    return document


def _partitioned_document() -> dict:
    """Minimal valid document with one age-partitioned source code."""
    document = _valid_document()
    source_name = "SETOR PARTICIONADO"
    document["groups"][1] = {
        "stable_key": "B",
        "display_name": "Sector B Child",
        "official_capacity": 16,
        "calculation_policy": CalculationPolicy.STANDARD,
        "source_codes": [
            {
                "source_code": "654",
                "configured_source_name": source_name,
                "age_selector": "under_12",
            }
        ],
    }
    document["groups"].append(
        {
            "stable_key": "C",
            "display_name": "Sector C Adult",
            "official_capacity": 32,
            "calculation_policy": CalculationPolicy.STANDARD,
            "source_codes": [
                {
                    "source_code": "654",
                    "configured_source_name": source_name,
                    "age_selector": "age_12_or_over",
                }
            ],
        }
    )
    return document


class TestSchemaConstraints:
    """R1: minimal temporal catalog schema with DB-enforced rules."""

    @pytest.mark.django_db
    def test_db_duplicate_effective_date_rejected(self):
        CapacityCatalogVersion.objects.create(
            effective_from="2030-01-01",
            source_reference="r1",
            source_sha256="a" * 64,
            schema_version="1.0",
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CapacityCatalogVersion.objects.create(
                    effective_from="2030-01-01",
                    source_reference="r2",
                    source_sha256="b" * 64,
                    schema_version="1.0",
                )

    @pytest.mark.django_db
    def test_db_policy_capacity_check_constraints(self):
        version = CapacityCatalogVersion.objects.create(
            effective_from="2030-01-02",
            source_reference="r",
            source_sha256="c" * 64,
            schema_version="1.0",
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CapacityGroupDefinition.objects.create(
                    catalog=version,
                    stable_key="UNRATED-WITH-CAP",
                    display_name="X",
                    official_capacity=1,
                    calculation_policy=CalculationPolicy.UNRATED,
                )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CapacityGroupDefinition.objects.create(
                    catalog=version,
                    stable_key="ZERO-CAP",
                    display_name="Y",
                    official_capacity=0,
                    calculation_policy=CalculationPolicy.STANDARD,
                )

    @pytest.mark.django_db
    def test_db_null_capacity_rejected_for_calculable_policies(self):
        """C3: NULL capacity must be rejected for calculable policies."""
        version = CapacityCatalogVersion.objects.create(
            effective_from="2030-01-04",
            source_reference="r",
            source_sha256="c" * 64,
            schema_version="1.0",
        )
        for policy in (
            CalculationPolicy.STANDARD,
            CalculationPolicy.LINKED_SLOTS_PENDING,
        ):
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    CapacityGroupDefinition.objects.create(
                        catalog=version,
                        stable_key=f"NULL-CAP-{policy}",
                        display_name="X",
                        official_capacity=None,
                        calculation_policy=policy,
                    )

    @pytest.mark.django_db
    def test_db_duplicate_stable_key_and_source_code_rejected(self):
        version = CapacityCatalogVersion.objects.create(
            effective_from="2030-01-03",
            source_reference="r",
            source_sha256="d" * 64,
            schema_version="1.0",
        )
        group = CapacityGroupDefinition.objects.create(
            catalog=version,
            stable_key="A",
            display_name="A",
            official_capacity=1,
            calculation_policy=CalculationPolicy.STANDARD,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CapacityGroupDefinition.objects.create(
                    catalog=version,
                    stable_key="A",
                    display_name="A2",
                    official_capacity=1,
                    calculation_policy=CalculationPolicy.STANDARD,
                )
        CapacitySectorMembership.objects.create(
            catalog=version,
            group=group,
            source_code="100",
            configured_source_name="A",
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CapacitySectorMembership.objects.create(
                    catalog=version,
                    group=group,
                    source_code="100",
                    configured_source_name="A2",
                )


class TestDocumentValidation:
    """R2: whole-document validation rejects ambiguous or malformed input."""

    def test_duplicate_source_code_rejected(self):
        document = _valid_document()
        document["groups"][1]["source_codes"] = [
            {
                "source_code": "100",
                "configured_source_name": "Outro setor",
            }
        ]
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        assert "100" in str(excinfo.value)

    def test_duplicate_stable_key_rejected(self):
        document = _valid_document()
        document["groups"][1]["stable_key"] = document["groups"][0]["stable_key"]
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    @pytest.mark.parametrize(
        ("policy", "capacity"),
        [
            ("standard", None),
            ("standard", 0),
            ("standard", -5),
            ("linked_slots_pending", None),
            ("linked_slots_pending", 0),
            ("linked_slots_pending", -5),
            ("unrated", 1),
            ("unrated", 0),
            ("unrated", -1),
            ("policy_desconhecida", 10),
        ],
    )
    def test_invalid_policy_capacity_rejected(self, policy: str, capacity: int | None):
        document = _valid_document()
        document["groups"][0]["calculation_policy"] = policy
        document["groups"][0]["official_capacity"] = capacity
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    def test_missing_required_fields_rejected(self):
        document = _valid_document()
        del document["groups"][0]["display_name"]
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

        document = _valid_document()
        document["groups"][0]["source_codes"] = []
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

        document = _valid_document()
        document["groups"][0]["source_codes"][0]["source_code"] = ""
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    def test_missing_document_sections_rejected(self):
        with pytest.raises(CatalogValidationError):
            validate_catalog_document({})
        with pytest.raises(CatalogValidationError):
            validate_catalog_document({"schema_version": "1.0"})
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(
                {"schema_version": "1.0", "source_reference": "r", "groups": []}
            )

    def test_malformed_json_rejected(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(bad, _future_date())


class TestInitialCatalog:
    """R5: the approved initial catalog totals and special mappings."""

    def test_initial_catalog_totals_and_mappings(self):
        catalog = validate_catalog_document(_initial_document())
        assert catalog.group_count == 42
        assert catalog.code_count == 47
        assert catalog.capacity_group_count == 39
        assert catalog.capacity_covered_code_count == 44
        assert catalog.calculable_code_count == 43
        assert catalog.known_capacity == 658
        assert catalog.calculable_capacity == 626

        by_key = {g.stable_key: g for g in catalog.groups}

        cardiologia = by_key["ENF-2B-CARD"]
        assert cardiologia.official_capacity == 15
        assert {m.source_code for m in cardiologia.memberships} == {
            "719",
            "2156",
        }

        centro_obstetrico = by_key["CO"]
        assert centro_obstetrico.official_capacity == 8
        assert {m.source_code for m in centro_obstetrico.memberships} == {
            "20",
            "1110",
            "1112",
            "1114",
            "1116",
        }

        obstetricia_3a = by_key["OBST-3A"]
        assert obstetricia_3a.official_capacity == 32
        assert obstetricia_3a.calculation_policy == (
            CalculationPolicy.LINKED_SLOTS_PENDING
        )
        assert [m.source_code for m in obstetricia_3a.memberships] == ["654"]

        for key in (
            "UNRATED-CRPA-HGRS",
            "UNRATED-CRPA-HOMEM",
            "UNRATED-MED-PED",
        ):
            group = by_key[key]
            assert group.calculation_policy == CalculationPolicy.UNRATED
            assert group.official_capacity is None

    def test_initial_catalog_codes_unique(self):
        document = _initial_document()
        codes = [
            m["source_code"]
            for group in document["groups"]
            for m in group["source_codes"]
        ]
        assert len(codes) == len(set(codes)) == 47

    def test_initial_catalog_configured_source_names_exact(self):
        """C1: full 47-code dictionary matches the source system names."""
        document = _initial_document()
        configured = {
            m["source_code"]: m["configured_source_name"]
            for group in document["groups"]
            for m in group["source_codes"]
        }
        assert len(EXPECTED_SOURCE_NAMES) == 47
        assert configured == EXPECTED_SOURCE_NAMES

    def test_initial_catalog_display_names_approved(self):
        """C1: display_name labels match the approved summarized names."""
        document = _initial_document()
        configured = {
            group["stable_key"]: group["display_name"]
            for group in document["groups"]
        }
        assert len(EXPECTED_DISPLAY_NAMES) == 42
        assert configured == EXPECTED_DISPLAY_NAMES

    def test_initial_catalog_provenance(self):
        """C2: provenance identifies source file, hash and 2026 dates."""
        document = _initial_document()
        reference = document["source_reference"]
        assert len(reference) <= 255
        assert "setores-leitos.xls" in reference
        assert (
            "fa5c4e95941794b4a90f2011d0584ae9eb5d4a5178e7e4022debeef4db8ca4dd"
            in reference
        )
        assert "29/07/2026" in reference
        assert "16/08/2026" in reference
        assert "2025" not in reference
        assert "sem dados de pacientes" in reference


class TestControlledActivation:
    """R3: future-dated, atomic, idempotent activation via service/command."""

    @pytest.mark.django_db
    def test_today_or_past_effective_date_rejected_zero_rows(self, tmp_path: Path):
        path = _write_document(tmp_path, _valid_document())
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(path, timezone.localdate().isoformat())
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(
                path, (timezone.localdate() - timedelta(days=1)).isoformat()
            )
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_dry_run_creates_no_rows(self, tmp_path: Path, capsys):
        path = _write_document(tmp_path, _valid_document())
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(path),
            "--effective-from",
            _future_date(),
            "--dry-run",
        )
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0
        out = capsys.readouterr().out
        assert "grupos oficiais: 2" in out
        assert "associações: 2" in out
        assert "códigos-fonte distintos: 2" in out
        assert "capacidade conhecida: 15" in out
        assert "SHA-256" in out

    @pytest.mark.django_db
    def test_valid_future_activation_creates_complete_graph_atomically(
        self, tmp_path: Path
    ):
        path = _write_document(tmp_path, _valid_document())
        effective = _future_date()
        result = activate_sector_capacity_catalog(path, effective)
        assert result.created is True
        version = CapacityCatalogVersion.objects.get()
        assert version.effective_from.isoformat() == effective
        assert version.schema_version == "1.0"
        assert version.source_reference == "test"
        assert len(version.source_sha256) == 64
        assert version.groups.count() == 2
        assert version.memberships.count() == 2
        assert result.group_count == 2
        assert result.member_count == 2
        assert result.code_count == 2
        assert result.known_capacity == 15
        assert result.calculable_capacity == 15


class TestMembershipSelectors:
    """R1: persistent membership selector with safe legacy default."""

    def test_selector_choices_are_the_three_supported_values(self):
        from apps.census.models import CapacityMembershipSelector

        assert set(CapacityMembershipSelector.values) == {
            "all",
            "under_12",
            "age_12_or_over",
        }

    def test_legacy_membership_without_selector_defaults_to_all(self):
        catalog = validate_catalog_document(_valid_document())
        selectors = {
            membership.age_selector
            for group in catalog.groups
            for membership in group.memberships
        }
        assert selectors == {"all"}

    def test_initial_catalog_parsing_defaults_every_selector_to_all(self):
        catalog = validate_catalog_document(_initial_document())
        selectors = {
            membership.age_selector
            for group in catalog.groups
            for membership in group.memberships
        }
        assert selectors == {"all"}
        assert catalog.membership_count == 47
        assert catalog.code_count == 47

    @pytest.mark.django_db
    def test_db_membership_defaults_to_all(self):
        version = CapacityCatalogVersion.objects.create(
            effective_from="2030-01-05",
            source_reference="r",
            source_sha256="a" * 64,
            schema_version="1.0",
        )
        group = CapacityGroupDefinition.objects.create(
            catalog=version,
            stable_key="A",
            display_name="A",
            official_capacity=1,
            calculation_policy=CalculationPolicy.STANDARD,
        )
        membership = CapacitySectorMembership.objects.create(
            catalog=version,
            group=group,
            source_code="100",
            configured_source_name="A",
        )
        membership.refresh_from_db()
        assert membership.age_selector == "all"


class TestSelectorCombinationValidation:
    """R2: domain rejects ambiguous code/group combinations before writing."""

    def test_duplicate_all_for_same_code_rejected(self):
        document = _valid_document()
        document["groups"][1]["source_codes"] = [
            {
                "source_code": "100",
                "configured_source_name": "Outro setor",
                "age_selector": "all",
            }
        ]
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        assert "100" in str(excinfo.value)

    def test_all_mixed_with_age_partition_rejected(self):
        document = _partitioned_document()
        document["groups"].append(
            {
                "stable_key": "D",
                "display_name": "Sector D",
                "official_capacity": 5,
                "calculation_policy": CalculationPolicy.STANDARD,
                "source_codes": [
                    {
                        "source_code": "654",
                        "configured_source_name": "SETOR",
                        "age_selector": "all",
                    }
                ],
            }
        )
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    def test_incomplete_age_partition_rejected(self):
        document = _partitioned_document()
        del document["groups"][2]
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        assert "654" in str(excinfo.value)

    def test_duplicate_age_partition_rejected(self):
        document = _partitioned_document()
        document["groups"][2]["source_codes"][0]["age_selector"] = "under_12"
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    @pytest.mark.parametrize("selector", ["unknown", "over_12", "", "todas"])
    def test_unknown_selector_rejected(self, selector: str):
        document = _partitioned_document()
        document["groups"][1]["source_codes"][0]["age_selector"] = selector
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    def test_age_partition_inside_single_group_rejected(self):
        document = _valid_document()
        document["groups"][1]["source_codes"] = [
            {
                "source_code": "654",
                "configured_source_name": "SETOR",
                "age_selector": "under_12",
            },
            {
                "source_code": "654",
                "configured_source_name": "SETOR",
                "age_selector": "age_12_or_over",
            },
        ]
        with pytest.raises(CatalogValidationError):
            validate_catalog_document(document)

    def test_complete_partition_in_different_groups_accepted(self):
        catalog = validate_catalog_document(_partitioned_document())
        assert catalog.group_count == 3
        assert catalog.membership_count == 3
        assert catalog.code_count == 2

    @pytest.mark.django_db
    def test_invalid_partition_leaves_no_partial_rows(self, tmp_path: Path):
        document = _partitioned_document()
        del document["groups"][2]
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(path, _future_date())
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0


class TestSelectorPersistence:
    """R6: atomic activation persists selectors bound to catalog and group."""

    @pytest.mark.django_db
    def test_activation_persists_partitioned_memberships(self, tmp_path: Path):
        path = _write_document(tmp_path, _partitioned_document())
        result = activate_sector_capacity_catalog(path, _future_date())
        assert result.created is True
        assert result.member_count == 3
        assert result.code_count == 2
        version = CapacityCatalogVersion.objects.get()
        assert version.groups.count() == 3
        assert version.memberships.count() == 3
        partitioned = {
            membership.age_selector: membership
            for membership in CapacitySectorMembership.objects.filter(
                source_code="654"
            )
        }
        assert set(partitioned) == {"under_12", "age_12_or_over"}
        child = partitioned["under_12"]
        adult = partitioned["age_12_or_over"]
        assert child.catalog_id == adult.catalog_id == version.pk
        assert child.group.stable_key == "B"
        assert adult.group.stable_key == "C"

    @pytest.mark.django_db
    def test_partitioned_activation_is_idempotent(self, tmp_path: Path):
        path = _write_document(tmp_path, _partitioned_document())
        effective = _future_date()
        first = activate_sector_capacity_catalog(path, effective)
        second = activate_sector_capacity_catalog(path, effective)
        assert first.created is True
        assert second.created is False
        assert first.document_sha256 == second.document_sha256
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacitySectorMembership.objects.count() == 3

    @pytest.mark.django_db
    def test_db_constraint_blocks_duplicate_catalog_code_selector(self):
        version = CapacityCatalogVersion.objects.create(
            effective_from="2030-01-06",
            source_reference="r",
            source_sha256="a" * 64,
            schema_version="1.0",
        )
        group = CapacityGroupDefinition.objects.create(
            catalog=version,
            stable_key="A",
            display_name="A",
            official_capacity=1,
            calculation_policy=CalculationPolicy.STANDARD,
        )
        CapacitySectorMembership.objects.create(
            catalog=version,
            group=group,
            source_code="100",
            configured_source_name="A",
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                CapacitySectorMembership.objects.create(
                    catalog=version,
                    group=group,
                    source_code="100",
                    configured_source_name="A2",
                    age_selector="all",
                )
        CapacitySectorMembership.objects.create(
            catalog=version,
            group=group,
            source_code="100",
            configured_source_name="A2",
            age_selector="under_12",
        )
        assert version.memberships.count() == 2


class TestCorrectedCatalogDocument:
    """R4: corrected artifact changes only CO and the 3A partition."""

    def test_unaffected_groups_are_copied_exactly(self):
        initial = _initial_document()
        corrected = _corrected_document()
        initial_groups = {g["stable_key"]: g for g in initial["groups"]}
        corrected_groups = {g["stable_key"]: g for g in corrected["groups"]}
        unaffected = set(initial_groups) - {"CO", "OBST-3A"}
        assert len(unaffected) == 40
        for key in unaffected:
            assert corrected_groups[key] == initial_groups[key]

    def test_only_approved_group_changes_exist(self):
        initial = _initial_document()
        corrected = _corrected_document()
        initial_keys = {g["stable_key"] for g in initial["groups"]}
        corrected_keys = {g["stable_key"] for g in corrected["groups"]}
        assert initial_keys - corrected_keys == {"OBST-3A"}
        assert corrected_keys - initial_keys == {
            "OBST-3A-ADULTO",
            "OBST-3A-INFANTIL",
        }
        assert len(corrected_keys) == 43

    def test_co_is_unrated_without_capacity_and_all_selector(self):
        corrected = _corrected_document()
        co = next(
            g for g in corrected["groups"] if g["stable_key"] == "CO"
        )
        assert co["calculation_policy"] == "unrated"
        assert co["official_capacity"] is None
        assert {
            (m["source_code"], m.get("age_selector", "all"))
            for m in co["source_codes"]
        } == {
            ("20", "all"),
            ("1110", "all"),
            ("1112", "all"),
            ("1114", "all"),
            ("1116", "all"),
        }

    def test_3a_is_split_into_adult_and_child_official_sectors(self):
        corrected = _corrected_document()
        groups = {g["stable_key"]: g for g in corrected["groups"]}
        adult = groups["OBST-3A-ADULTO"]
        child = groups["OBST-3A-INFANTIL"]
        assert adult["calculation_policy"] == "standard"
        assert adult["official_capacity"] == 32
        assert adult["source_codes"] == [
            {
                "source_code": "654",
                "configured_source_name": (
                    "3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS"
                ),
                "age_selector": "age_12_or_over",
            }
        ]
        assert child["calculation_policy"] == "standard"
        assert child["official_capacity"] == 16
        assert child["source_codes"] == [
            {
                "source_code": "654",
                "configured_source_name": (
                    "3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS"
                ),
                "age_selector": "under_12",
            }
        ]

    def test_corrected_document_has_no_extra_fields(self):
        corrected = _corrected_document()
        group_keys = {
            "stable_key",
            "display_name",
            "official_capacity",
            "calculation_policy",
            "source_codes",
        }
        membership_keys = {
            "source_code",
            "configured_source_name",
            "age_selector",
        }
        for group in corrected["groups"]:
            assert set(group) <= group_keys
            for membership in group["source_codes"]:
                assert set(membership) <= membership_keys
        assert "sem dados de pacientes" in corrected["source_reference"]


class TestCorrectedCatalogTotals:
    """R5: exact derived totals for the corrected photography."""

    def test_corrected_totals_derived_from_document(self):
        catalog = validate_catalog_document(_corrected_document())
        assert catalog.group_count == 43
        assert catalog.membership_count == 48
        assert catalog.code_count == 47
        assert catalog.capacity_group_count == 39
        assert catalog.standard_group_count == 39
        assert catalog.unrated_group_count == 4
        assert catalog.capacity_covered_code_count == 39
        assert catalog.calculable_code_count == 39
        assert catalog.known_capacity == 666
        assert catalog.calculable_capacity == 666

    @pytest.mark.django_db
    def test_dry_run_reports_corrected_totals_and_persists_nothing(
        self, capsys
    ):
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(CORRECTED_CATALOG),
            "--effective-from",
            _future_date(),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert "grupos oficiais: 43" in out
        assert "associações: 48" in out
        assert "códigos-fonte distintos: 47" in out
        assert "grupos com capacidade: 39" in out
        assert "grupos standard: 39" in out
        assert "grupos unrated: 4" in out
        assert "capacidade conhecida: 666" in out
        assert "capacidade calculável: 666" in out
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_command_activation_reports_and_persists(self, tmp_path: Path, capsys):
        path = _write_document(tmp_path, _valid_document())
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(path),
            "--effective-from",
            _future_date(),
        )
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 2
        assert CapacitySectorMembership.objects.count() == 2
        out = capsys.readouterr().out
        assert "publicado" in out

    @pytest.mark.django_db
    def test_command_output_contains_no_document_dump(self, tmp_path: Path, capsys):
        path = _write_document(tmp_path, _valid_document())
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(path),
            "--effective-from",
            _future_date(),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert '"groups"' not in out
        assert "display_name" not in out
        assert "source_codes" not in out


class TestIdempotencyAndConflicts:
    """R4: same hash no-op, different hash hard conflict, no partial state."""

    @pytest.mark.django_db
    def test_same_date_same_hash_is_idempotent(self, tmp_path: Path):
        path = _write_document(tmp_path, _valid_document())
        effective = _future_date()
        first = activate_sector_capacity_catalog(path, effective)
        second = activate_sector_capacity_catalog(path, effective)
        assert first.created is True
        assert second.created is False
        assert first.document_sha256 == second.document_sha256
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 2
        assert CapacitySectorMembership.objects.count() == 2

    @pytest.mark.django_db
    def test_same_date_different_hash_rejected_without_mutation(
        self, tmp_path: Path
    ):
        path1 = _write_document(tmp_path, _valid_document())
        document2 = _valid_document()
        document2["groups"][0]["display_name"] = "Sector A renomeado"
        path2 = tmp_path / "catalog2.json"
        path2.write_text(json.dumps(document2), encoding="utf-8")
        effective = _future_date()
        activate_sector_capacity_catalog(path1, effective)
        with pytest.raises(CatalogConflictError):
            activate_sector_capacity_catalog(path2, effective)
        version = CapacityCatalogVersion.objects.get()
        assert version.groups.count() == 2
        assert version.groups.get(stable_key="A").display_name == "Sector A"
        assert CapacityGroupDefinition.objects.count() == 2
        assert CapacitySectorMembership.objects.count() == 2

    @pytest.mark.django_db
    def test_command_conflict_raises_command_error(self, tmp_path: Path):
        path1 = _write_document(tmp_path, _valid_document())
        effective = _future_date()
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(path1),
            "--effective-from",
            effective,
        )
        document2 = _valid_document()
        document2["groups"][0]["display_name"] = "renomeado"
        path2 = tmp_path / "catalog2.json"
        path2.write_text(json.dumps(document2), encoding="utf-8")
        with pytest.raises(CommandError):
            call_command(
                "activate_sector_capacity_catalog",
                "--input",
                str(path2),
                "--effective-from",
                effective,
            )
        assert CapacityCatalogVersion.objects.count() == 1

    @pytest.mark.django_db
    def test_concurrent_duplicate_publication_is_handled(self, tmp_path: Path):
        effective = _future_date()
        preexisting = CapacityCatalogVersion.objects.create(
            effective_from=effective,
            source_reference="pre",
            source_sha256="e" * 64,
            schema_version="1.0",
        )
        path = _write_document(tmp_path, _valid_document())
        with pytest.raises(CatalogConflictError):
            activate_sector_capacity_catalog(path, effective)
        assert CapacityCatalogVersion.objects.count() == 1
        assert (
            CapacityCatalogVersion.objects.get(pk=preexisting.pk).source_sha256
            == "e" * 64
        )
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_validation_failure_leaves_no_partial_rows(self, tmp_path: Path):
        document = _valid_document()
        document["groups"][1]["source_codes"] = [
            {
                "source_code": "100",
                "configured_source_name": "duplicado",
            }
        ]
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(path, _future_date())
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0


class TestInitialCatalogCommand:
    """R5+R6: dry-run of the approved initial catalog via the command."""

    @pytest.mark.django_db
    def test_initial_catalog_dry_run_reports_approved_totals(self, capsys):
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(INITIAL_CATALOG),
            "--effective-from",
            _future_date(),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert "grupos oficiais: 42" in out
        assert "associações: 47" in out
        assert "códigos-fonte distintos: 47" in out
        assert "grupos com capacidade: 39" in out
        assert "grupos standard: 38" in out
        assert "grupos unrated: 3" in out
        assert "capacidade conhecida: 658" in out
        assert "capacidade calculável: 626" in out
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_initial_catalog_activates_full_graph(self):
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(INITIAL_CATALOG),
            "--effective-from",
            _future_date(),
        )
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 42
        assert CapacitySectorMembership.objects.count() == 47


class TestStrictDateFormat:
    """C7: only strict YYYY-MM-DD with a real, future local date is accepted."""

    @pytest.mark.parametrize(
        "raw_date",
        [
            "20270915",
            "2027-W37-3",
            "2026/08/17",
            "17-08-2026",
            "2026-13-01",
            "2026-02-30",
            "abc",
            "2026-8-17",
        ],
    )
    @pytest.mark.django_db
    def test_activation_rejects_non_iso_dates(self, tmp_path: Path, raw_date: str):
        path = _write_document(tmp_path, _valid_document())
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(path, raw_date)
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_activation_accepts_exact_iso_date_format(self, tmp_path: Path):
        path = _write_document(tmp_path, _valid_document())
        effective = (timezone.localdate() + timedelta(days=10)).isoformat()
        result = activate_sector_capacity_catalog(path, effective)
        assert result.created is True
        assert CapacityCatalogVersion.objects.count() == 1


class TestFieldLimits:
    """C6: dry-run validation rejects fields above the persisted max_length."""

    @pytest.mark.parametrize(
        ("path_keys", "limit"),
        [
            (["schema_version"], 20),
            (["source_reference"], 255),
            (["groups", 0, "stable_key"], 100),
            (["groups", 0, "display_name"], 255),
            (["groups", 0, "source_codes", 0, "source_code"], 50),
            (["groups", 0, "source_codes", 0, "configured_source_name"], 255),
        ],
    )
    @pytest.mark.django_db
    def test_validation_rejects_overlong_fields(
        self, tmp_path: Path, path_keys: list, limit: int
    ):
        document = _valid_document()
        _set_nested(document, path_keys, "x" * (limit + 1))
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError) as excinfo:
            activate_sector_capacity_catalog(path, _future_date(), dry_run=True)
        message = str(excinfo.value)
        assert '"groups"' not in message
        assert "source_codes" not in message
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_command_dry_run_rejects_overlong_schema_version(
        self, tmp_path: Path, capsys
    ):
        document = _valid_document()
        document["schema_version"] = "x" * 21
        path = _write_document(tmp_path, document)
        with pytest.raises(CommandError):
            call_command(
                "activate_sector_capacity_catalog",
                "--input",
                str(path),
                "--effective-from",
                _future_date(),
                "--dry-run",
            )
        assert CapacityCatalogVersion.objects.count() == 0


class _NoWinnerQuerySet:
    """Fake queryset that hides the winning row (concurrent race simulation)."""

    def filter(self, **kwargs) -> "_NoWinnerQuerySet":
        return self

    def first(self) -> None:
        return None


class TestConcurrentRecovery:
    """C4: recovery after IntegrityError re-reads the winner by hash."""

    def _hide_winner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            CapacityCatalogVersion.objects,
            "select_for_update",
            lambda: _NoWinnerQuerySet(),
        )

    def _simulate_lost_insert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_integrity(*args, **kwargs):
            raise IntegrityError("unique constraint violation")

        monkeypatch.setattr(catalog_module, "_persist_catalog", _raise_integrity)

    @pytest.mark.django_db
    def test_same_hash_race_recovers_as_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        document = _valid_document()
        path = _write_document(tmp_path, document)
        effective = _future_date()
        winner_hash = hashlib.sha256(
            json.dumps(document).encode("utf-8")
        ).hexdigest()
        CapacityCatalogVersion.objects.create(
            effective_from=effective,
            source_reference="winner",
            source_sha256=winner_hash,
            schema_version="1.0",
        )
        self._hide_winner(monkeypatch)
        self._simulate_lost_insert(monkeypatch)
        result = activate_sector_capacity_catalog(path, effective)
        assert result.created is False
        assert result.document_sha256 == winner_hash
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 0

    @pytest.mark.django_db
    def test_different_hash_race_recovers_as_conflict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        document = _valid_document()
        path = _write_document(tmp_path, document)
        effective = _future_date()
        CapacityCatalogVersion.objects.create(
            effective_from=effective,
            source_reference="winner",
            source_sha256="f" * 64,
            schema_version="1.0",
        )
        self._hide_winner(monkeypatch)
        self._simulate_lost_insert(monkeypatch)
        with pytest.raises(CatalogConflictError):
            activate_sector_capacity_catalog(path, effective)
        assert CapacityCatalogVersion.objects.count() == 1
        assert (
            CapacityCatalogVersion.objects.get(effective_from=effective)
            .source_sha256
            == "f" * 64
        )
        assert CapacityGroupDefinition.objects.count() == 0

    @pytest.mark.django_db
    def test_lost_race_without_winner_raises_safe_conflict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        path = _write_document(tmp_path, _valid_document())
        effective = _future_date()
        self._hide_winner(monkeypatch)
        self._simulate_lost_insert(monkeypatch)
        with pytest.raises(CatalogConflictError) as excinfo:
            activate_sector_capacity_catalog(path, effective)
        message = str(excinfo.value)
        assert "corrida" in message or "concorrente" in message
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0


class TestSingleRead:
    """C5: activation reads the payload exactly once; hash comes from it."""

    @pytest.mark.django_db
    def test_activation_reads_payload_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        document = _valid_document()
        path = _write_document(tmp_path, document)
        expected_hash = hashlib.sha256(
            json.dumps(document).encode("utf-8")
        ).hexdigest()
        real_read_bytes = Path.read_bytes
        calls = {"n": 0}

        def counting_read_bytes(self) -> bytes:
            calls["n"] += 1
            return real_read_bytes(self)

        monkeypatch.setattr(catalog_module.Path, "read_bytes", counting_read_bytes)
        result = activate_sector_capacity_catalog(path, _future_date())
        assert calls["n"] == 1
        assert result.document_sha256 == expected_hash
        version = CapacityCatalogVersion.objects.get()
        assert version.source_sha256 == expected_hash


class TestAlgorithmSchemaEvolution:
    """SOPBR-S2 R1/R6: schema novo exige algoritmo explícito suportado.

    Documentos históricos (schema atual, sem algoritmo) permanecem válidos;
    o algoritmo nunca é inferido por nome de arquivo, hash, data ou
    estrutura do documento.
    """

    def test_legacy_schemas_without_algorithm_remain_valid(self):
        for document in (_initial_document(), _corrected_document()):
            catalog = validate_catalog_document(document)
            assert catalog.algorithm_version is None

    @pytest.mark.django_db
    def test_new_schema_without_algorithm_is_rejected_before_write(
        self, tmp_path: Path
    ):
        document = _valid_document()
        document["schema_version"] = "2.0"
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError) as excinfo:
            activate_sector_capacity_catalog(path, _future_date())
        assert "occupancy_algorithm_version" in str(excinfo.value)
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.parametrize("algorithm", ["occupancy-v9", "", "   "])
    @pytest.mark.django_db
    def test_unknown_or_empty_algorithm_is_rejected_before_write(
        self, tmp_path: Path, algorithm: str
    ):
        document = _valid_document()
        document["schema_version"] = "2.0"
        document["occupancy_algorithm_version"] = algorithm
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError) as excinfo:
            activate_sector_capacity_catalog(path, _future_date())
        message = str(excinfo.value)
        assert "não suportado" in message or "não vazio" in message
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_overlong_algorithm_is_rejected(self, tmp_path: Path):
        document = _valid_document()
        document["schema_version"] = "2.0"
        document["occupancy_algorithm_version"] = "x" * 31
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(path, _future_date(), dry_run=True)

    def test_supported_algorithms_are_exactly_the_implemented_ones(self):
        assert catalog_module.ALLOWED_ALGORITHM_VERSIONS == frozenset(
            {"occupancy-v1", "occupancy-v2", "occupancy-v3", "occupancy-v4"}
        )

    def test_each_supported_algorithm_validates(self):
        for algorithm in catalog_module.ALLOWED_ALGORITHM_VERSIONS:
            document = _valid_document()
            document["schema_version"] = "2.0"
            document["occupancy_algorithm_version"] = algorithm
            catalog = validate_catalog_document(document)
            assert catalog.algorithm_version == algorithm

    def test_algorithm_field_in_legacy_schema_is_rejected(self):
        document = _corrected_document()
        document["occupancy_algorithm_version"] = "occupancy-v3"
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        assert "schema_version" in str(excinfo.value)

    @pytest.mark.parametrize("schema_version", ["1.2", "2.1", "3.1"])
    def test_unknown_schema_version_is_rejected(self, schema_version: str):
        document = _valid_document()
        document["schema_version"] = schema_version
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        assert "schema" in str(excinfo.value)

    @pytest.mark.django_db
    def test_v3_is_not_inferred_from_filename_date_or_duplicates(
        self, tmp_path: Path
    ):
        """Schema histórico mantém algoritmo nulo mesmo com nome de arquivo
        v3, data futura e 3A particionada: nada é inferido."""
        document = _corrected_document()
        path = tmp_path / "occupancy-v3-full-catalog.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        result = activate_sector_capacity_catalog(path, _future_date())
        assert result.created is True
        assert result.algorithm_version is None
        version = CapacityCatalogVersion.objects.get()
        assert version.algorithm_version is None


class TestV3CatalogDocument:
    """SOPBR-S2 R3: catálogo integral futuro declarando occupancy-v3."""

    def test_v3_document_declares_new_schema_and_v3(self):
        document = _v3_document()
        assert document["schema_version"] == "2.0"
        assert document["occupancy_algorithm_version"] == "occupancy-v3"

    def test_v3_document_totals_algorithm_and_special_groups(self):
        catalog = validate_catalog_document(_v3_document())
        assert catalog.schema_version == "2.0"
        assert catalog.algorithm_version == "occupancy-v3"
        assert catalog.group_count == 43
        assert catalog.membership_count == 48
        assert catalog.code_count == 47
        assert catalog.capacity_group_count == 39
        assert catalog.standard_group_count == 39
        assert catalog.unrated_group_count == 4
        assert catalog.known_capacity == 666
        assert catalog.calculable_capacity == 666

        by_key = {group.stable_key: group for group in catalog.groups}

        co = by_key["CO"]
        assert co.calculation_policy == CalculationPolicy.UNRATED
        assert co.official_capacity is None
        assert {(m.source_code, m.age_selector) for m in co.memberships} == {
            ("20", "all"),
            ("1110", "all"),
            ("1112", "all"),
            ("1114", "all"),
            ("1116", "all"),
        }

        adult = by_key["OBST-3A-ADULTO"]
        child = by_key["OBST-3A-INFANTIL"]
        assert adult.calculation_policy == CalculationPolicy.STANDARD
        assert adult.official_capacity == 32
        assert [
            (m.source_code, m.age_selector) for m in adult.memberships
        ] == [("654", "age_12_or_over")]
        assert child.calculation_policy == CalculationPolicy.STANDARD
        assert child.official_capacity == 16
        assert [
            (m.source_code, m.age_selector) for m in child.memberships
        ] == [("654", "under_12")]

    def test_v3_groups_are_structurally_identical_to_corrected(self):
        """CO, 3A Adulto/Infantil e os outros 40 grupos copiados exatamente."""
        assert _v3_document()["groups"] == _corrected_document()["groups"]

    def test_v3_document_has_new_safe_source_reference(self):
        v3 = _v3_document()
        reference = v3["source_reference"]
        assert reference != _corrected_document()["source_reference"]
        assert len(reference) <= 255
        assert "occupancy-v3" in reference
        assert "sem dados de pacientes" in reference
        lowered = reference.lower()
        for marker in ("prontuário", "nome de paciente", "sha-256 de paciente"):
            assert marker not in lowered


class TestV3DryRun:
    """SOPBR-S2 R4: dry-run observável com algoritmo v3 e zero escrita."""

    @pytest.mark.django_db
    def test_dry_run_reports_v3_and_totals_without_writes(self, capsys):
        before = (
            CapacityCatalogVersion.objects.count(),
            CapacityGroupDefinition.objects.count(),
            CapacitySectorMembership.objects.count(),
        )
        assert before == (0, 0, 0)

        result = activate_sector_capacity_catalog(
            V3_CATALOG, _future_date(30), dry_run=True
        )
        assert result.algorithm_version == "occupancy-v3"
        assert result.created is False
        assert result.group_count == 43
        assert result.member_count == 48
        assert result.code_count == 47
        assert result.standard_group_count == 39
        assert result.unrated_group_count == 4
        assert result.known_capacity == 666
        assert result.calculable_capacity == 666

        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(V3_CATALOG),
            "--effective-from",
            _future_date(30),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert "validado (dry-run)" in out
        assert "algoritmo de ocupação: occupancy-v3" in out
        assert "grupos oficiais: 43" in out
        assert "associações: 48" in out
        assert "códigos-fonte distintos: 47" in out
        assert "grupos com capacidade: 39" in out
        assert "grupos standard: 39" in out
        assert "grupos unrated: 4" in out
        assert "capacidade conhecida: 666" in out
        assert "capacidade calculável: 666" in out

        after = (
            CapacityCatalogVersion.objects.count(),
            CapacityGroupDefinition.objects.count(),
            CapacitySectorMembership.objects.count(),
        )
        assert after == before == (0, 0, 0)

    @pytest.mark.django_db
    def test_dry_run_labels_legacy_algorithm_as_structural(self, capsys):
        call_command(
            "activate_sector_capacity_catalog",
            "--input",
            str(INITIAL_CATALOG),
            "--effective-from",
            _future_date(),
            "--dry-run",
        )
        out = capsys.readouterr().out
        assert (
            "algoritmo de ocupação: histórico (despacho estrutural)" in out
        )


class TestV3FutureActivation:
    """SOPBR-S2 R5: ativação futura atômica, idempotente e conflitante."""

    @pytest.mark.django_db
    def test_today_and_past_rejected_for_v3_document(self):
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(
                V3_CATALOG, timezone.localdate().isoformat()
            )
        with pytest.raises(CatalogValidationError):
            activate_sector_capacity_catalog(
                V3_CATALOG,
                (timezone.localdate() - timedelta(days=1)).isoformat(),
            )
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.django_db
    def test_future_activation_persists_v3_atomically(self):
        effective = _future_date(30)
        result = activate_sector_capacity_catalog(V3_CATALOG, effective)
        assert result.created is True
        assert result.algorithm_version == "occupancy-v3"
        version = CapacityCatalogVersion.objects.get()
        assert version.effective_from.isoformat() == effective
        assert version.schema_version == "2.0"
        assert version.algorithm_version == "occupancy-v3"
        assert version.groups.count() == 43
        assert version.memberships.count() == 48

        dry = activate_sector_capacity_catalog(
            V3_CATALOG, _future_date(31), dry_run=True
        )
        assert dry.algorithm_version == result.algorithm_version
        assert (dry.group_count, dry.member_count, dry.code_count) == (
            43,
            48,
            47,
        )

    @pytest.mark.django_db
    def test_v3_activation_is_idempotent_for_same_document_and_date(self):
        effective = _future_date(30)
        first = activate_sector_capacity_catalog(V3_CATALOG, effective)
        second = activate_sector_capacity_catalog(V3_CATALOG, effective)
        assert first.created is True
        assert second.created is False
        assert first.document_sha256 == second.document_sha256
        assert second.algorithm_version == "occupancy-v3"
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 43
        assert CapacitySectorMembership.objects.count() == 48
        assert (
            CapacityCatalogVersion.objects.get().algorithm_version
            == "occupancy-v3"
        )

    @pytest.mark.django_db
    def test_divergent_document_same_date_conflicts_without_mutation(
        self, tmp_path: Path
    ):
        effective = _future_date(30)
        activate_sector_capacity_catalog(V3_CATALOG, effective)
        divergent = _v3_document()
        divergent["source_reference"] = "divergente"
        path = _write_document(tmp_path, divergent)
        with pytest.raises(CatalogConflictError):
            activate_sector_capacity_catalog(path, effective)
        version = CapacityCatalogVersion.objects.get()
        assert version.algorithm_version == "occupancy-v3"
        assert version.groups.count() == 43
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 43
        assert CapacitySectorMembership.objects.count() == 48


# Hashes SHA-256 dos artefatos históricos (baseline MOQA-S2; byte preservation).
HISTORICAL_JSON_SHA256 = {
    "initial": "7e346a74503d2ea797740bc8773d6a45702fed2e6aa0497f91c7d25e7f2a6bb3",
    "corrected": "d11e26b349b84c7c8f369867348f0ad261c2a2cdfab51cb991055aca1dc27acc",
    "v3": "62298efb138af3b0ecec38974e6d2c922f4031a3304c932d230cebb5eb85455c",
}


class TestAliasSchemaEvolution:
    """MOQA-S2 R2/R3: schema 3.0 exige alias limpo e consistente por código."""

    @pytest.mark.django_db
    def test_new_schema_without_alias_is_rejected_before_write(
        self, tmp_path: Path
    ):
        document = _alias_document()
        for group in document["groups"]:
            for membership in group["source_codes"]:
                del membership["source_display_name"]
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError) as excinfo:
            activate_sector_capacity_catalog(path, _future_date())
        message = str(excinfo.value)
        assert "source_display_name" in message
        assert "Grupo" in message
        assert '"groups"' not in message
        assert "source_codes" not in message
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    @pytest.mark.parametrize("alias", ["", "   ", "\t", "\n"])
    def test_whitespace_alias_is_rejected(self, alias: str):
        document = _alias_document()
        document["groups"][0]["source_codes"][0]["source_display_name"] = alias
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        assert "source_display_name" in str(excinfo.value)

    @pytest.mark.django_db
    def test_overlong_alias_rejected_with_safe_path(self, tmp_path: Path):
        document = _alias_document()
        document["groups"][0]["source_codes"][0]["source_display_name"] = (
            "x" * 256
        )
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError) as excinfo:
            activate_sector_capacity_catalog(
                path, _future_date(), dry_run=True
            )
        message = str(excinfo.value)
        assert "source_display_name" in message
        assert "Grupo 0" in message
        assert "255" in message
        assert '"groups"' not in message
        assert "source_codes" not in message
        assert CapacityCatalogVersion.objects.count() == 0

    def test_legacy_schemas_reject_alias_field(self):
        for document in (_valid_document(), _v3_document()):
            document["groups"][0]["source_codes"][0][
                "source_display_name"
            ] = "Alias indevido"
            with pytest.raises(CatalogValidationError) as excinfo:
                validate_catalog_document(document)
            assert "schema_version" in str(excinfo.value)

    def test_divergent_aliases_for_partitioned_code_rejected(self):
        document = _partitioned_alias_document()
        document["groups"][2]["source_codes"][0]["source_display_name"] = (
            "Alias Divergente"
        )
        with pytest.raises(CatalogValidationError) as excinfo:
            validate_catalog_document(document)
        message = str(excinfo.value)
        assert "654" in message
        assert "source_display_name" in message

    def test_partitioned_code_with_shared_alias_accepted(self):
        catalog = validate_catalog_document(_partitioned_alias_document())
        assert catalog.algorithm_version == "occupancy-v4"
        aliases = {
            membership.source_display_name
            for group in catalog.groups
            for membership in group.memberships
            if membership.source_code == "654"
        }
        assert aliases == {"Setor Particionado"}

    @pytest.mark.parametrize("algorithm", ["occupancy-v9", "", "   "])
    @pytest.mark.django_db
    def test_unknown_or_empty_algorithm_still_rejected_on_new_schema(
        self, tmp_path: Path, algorithm: str
    ):
        document = _alias_document()
        document["occupancy_algorithm_version"] = algorithm
        path = _write_document(tmp_path, document)
        with pytest.raises(CatalogValidationError) as excinfo:
            activate_sector_capacity_catalog(path, _future_date())
        message = str(excinfo.value)
        assert "não suportado" in message or "não vazio" in message
        assert CapacityCatalogVersion.objects.count() == 0
        assert CapacityGroupDefinition.objects.count() == 0
        assert CapacitySectorMembership.objects.count() == 0

    def test_historical_documents_stay_valid_without_alias(self):
        for document in (
            _initial_document(),
            _corrected_document(),
            _v3_document(),
        ):
            catalog = validate_catalog_document(document)
            assert catalog.aliased_membership_count == 0
            assert all(
                membership.source_display_name is None
                for group in catalog.groups
                for membership in group.memberships
            )


class TestV4CatalogDocument:
    """MOQA-S2 R5/R6: catálogo integral v4 com aliases curados."""

    def test_v4_document_declares_new_schema_and_v4(self):
        document = _v4_document()
        assert document["schema_version"] == "3.0"
        assert document["occupancy_algorithm_version"] == "occupancy-v4"

    def test_v4_document_totals_and_alias_coverage(self):
        catalog = validate_catalog_document(_v4_document())
        assert catalog.schema_version == "3.0"
        assert catalog.algorithm_version == "occupancy-v4"
        assert catalog.group_count == 43
        assert catalog.membership_count == 48
        assert catalog.code_count == 47
        assert catalog.capacity_group_count == 39
        assert catalog.standard_group_count == 39
        assert catalog.unrated_group_count == 4
        assert catalog.known_capacity == 666
        assert catalog.calculable_capacity == 666
        assert catalog.aliased_membership_count == 48

    def test_v4_preserves_co_policy_and_3a_partition(self):
        catalog = validate_catalog_document(_v4_document())
        by_key = {group.stable_key: group for group in catalog.groups}
        co = by_key["CO"]
        assert co.calculation_policy == CalculationPolicy.UNRATED
        assert co.official_capacity is None
        assert {(m.source_code, m.age_selector) for m in co.memberships} == {
            ("20", "all"),
            ("1110", "all"),
            ("1112", "all"),
            ("1114", "all"),
            ("1116", "all"),
        }
        adult = by_key["OBST-3A-ADULTO"]
        child = by_key["OBST-3A-INFANTIL"]
        assert adult.calculation_policy == CalculationPolicy.STANDARD
        assert adult.official_capacity == 32
        assert [m.source_code for m in adult.memberships] == ["654"]
        assert child.calculation_policy == CalculationPolicy.STANDARD
        assert child.official_capacity == 16
        assert [m.source_code for m in child.memberships] == ["654"]

    def test_v4_structural_groups_match_v3_except_aliases(self):
        v3 = _v3_document()
        v4 = _v4_document()
        assert [g["stable_key"] for g in v4["groups"]] == [
            g["stable_key"] for g in v3["groups"]
        ]
        for group4, group3 in zip(
            v4["groups"], v3["groups"], strict=True
        ):
            for key in ("display_name", "official_capacity", "calculation_policy"):
                assert group4[key] == group3[key]
            assert [m["source_code"] for m in group4["source_codes"]] == [
                m["source_code"] for m in group3["source_codes"]
            ]

    def test_curated_aliases_gastro_3a_cardio_and_co(self):
        document = _v4_document()
        aliases = {
            m["source_code"]: m["source_display_name"]
            for group in document["groups"]
            for m in group["source_codes"]
        }
        assert aliases["2702"] == "Enfermaria Gastroenterologia"
        assert aliases["654"] == "Enfermaria 3A Obstetrícia Clínica"
        assert aliases["719"] == "Cardioclínica"
        assert aliases["2156"] == "Enfermaria 2B Cardio"
        assert aliases["20"] == "Centro Obstétrico"
        assert aliases["1110"] == "Observação Ginecológica"
        assert aliases["1112"] == "Sala de Medicação (CO)"
        assert aliases["1114"] == "Estabilização RN (CO)"
        assert aliases["1116"] == "Internação Centro Obstétrico"

    def test_3a_uses_one_physical_alias_across_both_memberships(self):
        document = _v4_document()
        partitions = [
            m
            for group in document["groups"]
            for m in group["source_codes"]
            if m["source_code"] == "654"
        ]
        assert len(partitions) == 2
        assert {m["source_display_name"] for m in partitions} == {
            "Enfermaria 3A Obstetrícia Clínica"
        }
        group_names = {g["display_name"] for g in document["groups"]}
        for membership in partitions:
            assert membership["source_display_name"] not in group_names

    def test_raw_name_preserved_and_distinct_from_alias(self):
        document = _v4_document()
        for group in document["groups"]:
            for membership in group["source_codes"]:
                assert membership["configured_source_name"].strip()
                assert membership["source_display_name"].strip()
                if membership["source_code"] in {
                    "2702",
                    "654",
                    "719",
                    "2156",
                }:
                    assert (
                        membership["source_display_name"]
                        != membership["configured_source_name"]
                    )

    def test_all_memberships_have_non_empty_clean_alias(self):
        document = _v4_document()
        memberships = [
            m for group in document["groups"] for m in group["source_codes"]
        ]
        assert len(memberships) == 48
        for membership in memberships:
            alias = membership["source_display_name"]
            assert isinstance(alias, str)
            assert alias == alias.strip()
            assert len(alias) <= 255

    def test_aliases_have_no_technical_location_patterns(self):
        document = _v4_document()
        for group in document["groups"]:
            for membership in group["source_codes"]:
                alias = membership["source_display_name"]
                assert not alias[:1].isdigit()
                for marker in (
                    "0 T",
                    "0 S",
                    "0 L",
                    "0 N",
                    "0 0",
                    " - HGRS",
                    "sistema legado",
                ):
                    assert marker not in alias, f"'{alias}' contém '{marker}'"
                assert not re.search(r"[1-4] [6-8] -", alias)


class TestV4DryRunAndPersistence:
    """MOQA-S2 R4: dry-run sem escrita; publicação atômica com aliases."""

    @pytest.mark.django_db
    def test_dry_run_reports_v4_totals_and_full_alias_coverage(self):
        before = (
            CapacityCatalogVersion.objects.count(),
            CapacityGroupDefinition.objects.count(),
            CapacitySectorMembership.objects.count(),
        )
        assert before == (0, 0, 0)

        result = activate_sector_capacity_catalog(
            V4_CATALOG, _future_date(30), dry_run=True
        )
        assert result.algorithm_version == "occupancy-v4"
        assert result.created is False
        assert result.group_count == 43
        assert result.member_count == 48
        assert result.code_count == 47
        assert result.standard_group_count == 39
        assert result.unrated_group_count == 4
        assert result.known_capacity == 666
        assert result.calculable_capacity == 666
        assert result.aliased_membership_count == 48
        assert result.aliased_membership_count == result.member_count

        after = (
            CapacityCatalogVersion.objects.count(),
            CapacityGroupDefinition.objects.count(),
            CapacitySectorMembership.objects.count(),
        )
        assert after == before == (0, 0, 0)

    @pytest.mark.django_db
    def test_future_activation_persists_aliases_atomically(self):
        effective = _future_date(30)
        result = activate_sector_capacity_catalog(V4_CATALOG, effective)
        assert result.created is True
        assert result.aliased_membership_count == 48
        version = CapacityCatalogVersion.objects.get()
        assert version.schema_version == "3.0"
        assert version.algorithm_version == "occupancy-v4"
        assert version.groups.count() == 43
        assert version.memberships.count() == 48

        rows = {m.source_code: m for m in version.memberships.all()}
        assert rows["2702"].source_display_name == "Enfermaria Gastroenterologia"
        assert (
            rows["2702"].configured_source_name
            == "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS"
        )
        assert rows["654"].source_display_name == (
            "Enfermaria 3A Obstetrícia Clínica"
        )
        assert rows["719"].source_display_name == "Cardioclínica"
        assert rows["2156"].source_display_name == "Enfermaria 2B Cardio"

    @pytest.mark.django_db
    def test_v4_activation_is_idempotent_for_same_document_and_date(self):
        effective = _future_date(30)
        first = activate_sector_capacity_catalog(V4_CATALOG, effective)
        second = activate_sector_capacity_catalog(V4_CATALOG, effective)
        assert first.created is True
        assert second.created is False
        assert first.document_sha256 == second.document_sha256
        assert second.aliased_membership_count == 48
        assert CapacityCatalogVersion.objects.count() == 1
        assert CapacityGroupDefinition.objects.count() == 43
        assert CapacitySectorMembership.objects.count() == 48

    @pytest.mark.django_db
    def test_historical_activation_keeps_alias_null(self):
        effective = _future_date(30)
        activate_sector_capacity_catalog(V3_CATALOG, effective)
        rows = list(
            CapacitySectorMembership.objects.filter(source_code="2702")
        )
        assert len(rows) == 1
        assert rows[0].source_display_name is None
        assert (
            rows[0].configured_source_name
            == "0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS"
        )


class TestV4BytePreservation:
    """MOQA-S2 R7: artefatos históricos permanecem byte a byte idênticos."""

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_historical_json_hashes_unchanged(self):
        assert (
            self._sha256(INITIAL_CATALOG)
            == HISTORICAL_JSON_SHA256["initial"]
        )
        assert (
            self._sha256(CORRECTED_CATALOG)
            == HISTORICAL_JSON_SHA256["corrected"]
        )
        assert self._sha256(V3_CATALOG) == HISTORICAL_JSON_SHA256["v3"]

    def test_historical_documents_keep_parsing_results(self):
        for document, schema, memberships in (
            (_initial_document(), "1.0", 47),
            (_corrected_document(), "1.1", 48),
            (_v3_document(), "2.0", 48),
        ):
            catalog = validate_catalog_document(document)
            assert catalog.schema_version == schema
            assert catalog.membership_count == memberships
            assert catalog.aliased_membership_count == 0
