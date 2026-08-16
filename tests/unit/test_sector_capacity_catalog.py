"""Tests for SCOH-S1: versioned sector capacity catalog publication."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

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
        assert "grupos: 2" in out
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
        assert result.known_capacity == 15
        assert result.calculable_capacity == 15

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
        assert "grupos: 42" in out
        assert "membros (códigos): 47" in out
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
