"""SCOH-S1: versioned sector capacity catalog domain.

Cohesive parsing, whole-document validation and controlled activation of a
complete capacity catalog published for a strictly future local date in
``America/Bahia``. Persistence is atomic and immutable: a version can never be
edited or deleted, and the same date accepts only the same document hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.census.models import (
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
)


class CatalogError(Exception):
    """Base error for catalog validation and activation."""


class CatalogValidationError(CatalogError):
    """Document failed whole-catalog validation."""


class CatalogConflictError(CatalogError):
    """An immutable version already exists for the requested date."""


@dataclass(frozen=True)
class MembershipSpec:
    source_code: str
    configured_source_name: str


@dataclass(frozen=True)
class GroupSpec:
    stable_key: str
    display_name: str
    official_capacity: int | None
    calculation_policy: str
    memberships: tuple[MembershipSpec, ...]


@dataclass(frozen=True)
class ValidatedCatalog:
    schema_version: str
    source_reference: str
    groups: tuple[GroupSpec, ...]

    @property
    def group_count(self) -> int:
        return len(self.groups)

    @property
    def code_count(self) -> int:
        return len({m.source_code for g in self.groups for m in g.memberships})

    @property
    def capacity_group_count(self) -> int:
        return sum(1 for g in self.groups if g.official_capacity is not None)

    @property
    def capacity_covered_code_count(self) -> int:
        return len(
            {
                m.source_code
                for g in self.groups
                if g.official_capacity is not None
                for m in g.memberships
            }
        )

    @property
    def calculable_code_count(self) -> int:
        return len(
            {
                m.source_code
                for g in self.groups
                if g.calculation_policy == CalculationPolicy.STANDARD
                for m in g.memberships
            }
        )

    @property
    def known_capacity(self) -> int:
        return sum(g.official_capacity or 0 for g in self.groups)

    @property
    def calculable_capacity(self) -> int:
        return sum(
            g.official_capacity or 0
            for g in self.groups
            if g.calculation_policy == CalculationPolicy.STANDARD
        )


@dataclass(frozen=True)
class ActivationResult:
    effective_from: date
    document_sha256: str
    created: bool
    group_count: int
    member_count: int
    known_capacity: int | None
    calculable_capacity: int | None


_ALLOWED_POLICIES = frozenset(
    {
        CalculationPolicy.STANDARD,
        CalculationPolicy.LINKED_SLOTS_PENDING,
        CalculationPolicy.UNRATED,
    }
)


def load_catalog_document(input_path: str | Path) -> dict[str, Any]:
    """Read and parse the JSON catalog document."""
    path = Path(input_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CatalogValidationError(
            f"Não foi possível ler '{path.name}'."
        ) from exc
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogValidationError(
            f"JSON inválido em '{path.name}'."
        ) from exc
    if not isinstance(document, dict):
        raise CatalogValidationError("Documento JSON deve ser um objeto.")
    return document


def validate_catalog_document(document: dict[str, Any]) -> ValidatedCatalog:
    """Validate the whole document before any persistence.

    Rejects duplicate stable keys, duplicate source codes, cross-catalog
    ambiguity, invalid policy/capacity combinations and missing required
    names/codes. Raises :class:`CatalogValidationError` on the first problem.
    """
    schema_version = document.get("schema_version")
    source_reference = document.get("source_reference")
    raw_groups = document.get("groups")

    if not isinstance(schema_version, str) or not schema_version.strip():
        raise CatalogValidationError(
            "Campo 'schema_version' ausente ou vazio."
        )
    if not isinstance(source_reference, str) or not source_reference.strip():
        raise CatalogValidationError(
            "Campo 'source_reference' ausente ou vazio."
        )
    if not isinstance(raw_groups, list) or not raw_groups:
        raise CatalogValidationError("Campo 'groups' ausente ou vazio.")

    groups: list[GroupSpec] = []
    seen_stable_keys: set[str] = set()
    seen_source_codes: set[str] = set()

    for index, raw_group in enumerate(raw_groups):
        group = _validate_group(raw_group, index)
        if group.stable_key in seen_stable_keys:
            raise CatalogValidationError(
                f"Chave estável duplicada: '{group.stable_key}'."
            )
        seen_stable_keys.add(group.stable_key)
        for membership in group.memberships:
            if membership.source_code in seen_source_codes:
                raise CatalogValidationError(
                    f"Código fonte duplicado: '{membership.source_code}'."
                )
            seen_source_codes.add(membership.source_code)
        groups.append(group)

    return ValidatedCatalog(
        schema_version=schema_version.strip(),
        source_reference=source_reference.strip(),
        groups=tuple(groups),
    )


def activate_sector_capacity_catalog(
    input_path: str | Path,
    effective_from: str | date,
    dry_run: bool = False,
) -> ActivationResult:
    """Validate and publish a complete catalog for a future local date.

    CLI adapter contract (see management command):
    ``activate_sector_capacity_catalog --input <arquivo-json>
    --effective-from YYYY-MM-DD [--dry-run]``.

    - the date must be strictly after ``timezone.localdate()``;
    - the document is fully validated and hashed before any write;
    - persistence happens in one atomic transaction;
    - the same date/hash is an idempotent no-op;
    - the same date/different hash raises :class:`CatalogConflictError`;
    - ``--dry-run`` never persists.
    """
    path = Path(input_path)
    document = load_catalog_document(path)
    document_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    validated = validate_catalog_document(document)
    effective_date = _parse_future_date(effective_from)

    base_result = ActivationResult(
        effective_from=effective_date,
        document_sha256=document_sha256,
        created=False,
        group_count=validated.group_count,
        member_count=validated.code_count,
        known_capacity=validated.known_capacity,
        calculable_capacity=validated.calculable_capacity,
    )

    if dry_run:
        return base_result

    try:
        with transaction.atomic():
            existing = (
                CapacityCatalogVersion.objects.select_for_update()
                .filter(effective_from=effective_date)
                .first()
            )
            if existing is not None:
                if existing.source_sha256 == document_sha256:
                    return base_result
                raise CatalogConflictError(
                    f"Data {effective_date} já possui catálogo "
                    "com hash diferente."
                )
            _persist_catalog(validated, effective_date, document_sha256)
            return replace(base_result, created=True)
    except IntegrityError as exc:
        raise CatalogConflictError(
            f"Data {effective_date} já possui catálogo publicado."
        ) from exc


def _parse_future_date(value: str | date) -> date:
    if not isinstance(value, date):
        try:
            effective_date = date.fromisoformat(value)
        except ValueError as exc:
            raise CatalogValidationError(
                f"Data efetiva inválida: '{value}' (esperado YYYY-MM-DD)."
            ) from exc
    else:
        effective_date = value
    today = timezone.localdate()
    if effective_date <= today:
        raise CatalogValidationError(
            f"Data efetiva {effective_date} deve ser estritamente "
            f"posterior a hoje ({today})."
        )
    return effective_date


def _validate_group(raw_group: Any, index: int) -> GroupSpec:
    if not isinstance(raw_group, dict):
        raise CatalogValidationError(f"Grupo {index}: deve ser um objeto.")
    stable_key = raw_group.get("stable_key")
    display_name = raw_group.get("display_name")
    policy = raw_group.get("calculation_policy")
    capacity = raw_group.get("official_capacity")
    raw_codes = raw_group.get("source_codes")

    if not isinstance(stable_key, str) or not stable_key.strip():
        raise CatalogValidationError(
            f"Grupo {index}: 'stable_key' ausente ou vazio."
        )
    if not isinstance(display_name, str) or not display_name.strip():
        raise CatalogValidationError(
            f"Grupo {index}: 'display_name' ausente ou vazio."
        )
    if policy not in _ALLOWED_POLICIES:
        raise CatalogValidationError(
            f"Grupo {index}: política '{policy}' não permitida."
        )
    if not isinstance(raw_codes, list) or not raw_codes:
        raise CatalogValidationError(
            f"Grupo {index}: 'source_codes' ausente ou vazio."
        )

    capacity_value = None
    if capacity is not None:
        capacity_value = _validate_capacity(capacity, index)
    _validate_policy_capacity(policy, capacity_value, index)

    memberships = tuple(
        _validate_membership(raw_code, index) for raw_code in raw_codes
    )
    return GroupSpec(
        stable_key=stable_key.strip(),
        display_name=display_name.strip(),
        official_capacity=capacity_value,
        calculation_policy=policy,
        memberships=memberships,
    )


def _validate_capacity(capacity: Any, index: int) -> int:
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        raise CatalogValidationError(
            f"Grupo {index}: 'official_capacity' deve ser um inteiro."
        )
    if capacity <= 0:
        raise CatalogValidationError(
            f"Grupo {index}: 'official_capacity' deve ser positivo."
        )
    return capacity


def _validate_policy_capacity(
    policy: str, capacity: int | None, index: int
) -> None:
    if policy == CalculationPolicy.UNRATED:
        if capacity is not None:
            raise CatalogValidationError(
                f"Grupo {index}: política 'unrated' não pode declarar "
                "capacidade."
            )
        return
    if capacity is None:
        raise CatalogValidationError(
            f"Grupo {index}: política '{policy}' exige capacidade positiva."
        )


def _validate_membership(raw_code: Any, group_index: int) -> MembershipSpec:
    if not isinstance(raw_code, dict):
        raise CatalogValidationError(
            f"Grupo {group_index}: membro deve ser um objeto."
        )
    source_code = raw_code.get("source_code")
    configured_name = raw_code.get("configured_source_name")
    if not isinstance(source_code, str) or not source_code.strip():
        raise CatalogValidationError(
            f"Grupo {group_index}: 'source_code' ausente ou vazio."
        )
    if not isinstance(configured_name, str) or not configured_name.strip():
        raise CatalogValidationError(
            f"Grupo {group_index}: 'configured_source_name' ausente ou vazio."
        )
    return MembershipSpec(
        source_code=source_code.strip(),
        configured_source_name=configured_name.strip(),
    )


def _persist_catalog(
    validated: ValidatedCatalog,
    effective_date: date,
    document_sha256: str,
) -> None:
    """Create the version, groups and memberships. Caller owns the transaction."""
    version = CapacityCatalogVersion.objects.create(
        effective_from=effective_date,
        source_reference=validated.source_reference,
        source_sha256=document_sha256,
        schema_version=validated.schema_version,
    )
    definitions: dict[str, CapacityGroupDefinition] = {}
    for group in validated.groups:
        definitions[group.stable_key] = CapacityGroupDefinition.objects.create(
            catalog=version,
            stable_key=group.stable_key,
            display_name=group.display_name,
            official_capacity=group.official_capacity,
            calculation_policy=group.calculation_policy,
        )
    for group in validated.groups:
        definition = definitions[group.stable_key]
        CapacitySectorMembership.objects.bulk_create(
            [
                CapacitySectorMembership(
                    catalog=version,
                    group=definition,
                    source_code=membership.source_code,
                    configured_source_name=membership.configured_source_name,
                )
                for membership in group.memberships
            ]
        )
