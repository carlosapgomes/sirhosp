"""SCOH-S1: versioned sector capacity catalog domain.

Cohesive parsing, whole-document validation and controlled activation of a
complete capacity catalog published for a strictly future local date in
``America/Bahia``. Persistence is atomic and immutable: a version can never be
edited or deleted, and the same date accepts only the same document hash.

The input payload is read exactly once; parsing, validation and the SHA-256
derive from the same immutable byte buffer. After a lost concurrent insert the
winner is re-read by effective date and compared by hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.census import occupancy
from apps.census.models import (
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacityMembershipSelector,
    CapacitySectorMembership,
)

_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _field_max_length(model: type[models.Model], field_name: str) -> int:
    field = model._meta.get_field(field_name)
    assert isinstance(field, models.Field), field_name
    limit = field.max_length
    assert limit is not None, f"{field_name} precisa de max_length"
    return limit


# Limites persistíveis derivados dos campos Django (DRY: sem duplicar números).
MAX_SCHEMA_VERSION = _field_max_length(CapacityCatalogVersion, "schema_version")
MAX_SOURCE_REFERENCE = _field_max_length(
    CapacityCatalogVersion, "source_reference"
)
MAX_STABLE_KEY = _field_max_length(CapacityGroupDefinition, "stable_key")
MAX_DISPLAY_NAME = _field_max_length(CapacityGroupDefinition, "display_name")
MAX_SOURCE_CODE = _field_max_length(CapacitySectorMembership, "source_code")
MAX_CONFIGURED_SOURCE_NAME = _field_max_length(
    CapacitySectorMembership, "configured_source_name"
)
MAX_ALGORITHM_VERSION = _field_max_length(
    CapacityCatalogVersion, "algorithm_version"
)

# Schemas históricos publicados antes do contexto explícito de algoritmo;
# permanecem válidos somente sem o campo (despacho estrutural v1/v2).
LEGACY_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
# Primeira versão de schema que exige algoritmo declarado.
SCHEMA_VERSION_WITH_ALGORITHM = "2.0"
# Allowlist única: exatamente os algoritmos implementados em occupancy.py.
ALLOWED_ALGORITHM_VERSIONS = frozenset(
    {
        occupancy.ALGORITHM_VERSION,
        occupancy.ALGORITHM_VERSION_V2,
        occupancy.ALGORITHM_VERSION_V3,
    }
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
    age_selector: str = CapacityMembershipSelector.ALL


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
    algorithm_version: str | None = None

    @property
    def group_count(self) -> int:
        return len(self.groups)

    @property
    def membership_count(self) -> int:
        return sum(len(group.memberships) for group in self.groups)

    @property
    def code_count(self) -> int:
        return len({m.source_code for g in self.groups for m in g.memberships})

    @property
    def capacity_group_count(self) -> int:
        return sum(1 for g in self.groups if g.official_capacity is not None)

    @property
    def standard_group_count(self) -> int:
        return sum(
            1
            for g in self.groups
            if g.calculation_policy == CalculationPolicy.STANDARD
        )

    @property
    def unrated_group_count(self) -> int:
        return sum(
            1
            for g in self.groups
            if g.calculation_policy == CalculationPolicy.UNRATED
        )

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
    code_count: int
    capacity_group_count: int
    standard_group_count: int
    unrated_group_count: int
    known_capacity: int
    calculable_capacity: int
    algorithm_version: str | None = None


_ALLOWED_POLICIES = frozenset(
    {
        CalculationPolicy.STANDARD,
        CalculationPolicy.LINKED_SLOTS_PENDING,
        CalculationPolicy.UNRATED,
    }
)

_ALLOWED_SELECTORS = frozenset(CapacityMembershipSelector.values)


def parse_catalog_document(raw_document: bytes) -> dict[str, Any]:
    """Decode and parse the JSON catalog document from a single buffer."""
    try:
        document = json.loads(raw_document.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogValidationError("JSON inválido.") from exc
    if not isinstance(document, dict):
        raise CatalogValidationError("Documento JSON deve ser um objeto.")
    return document


def validate_catalog_document(document: dict[str, Any]) -> ValidatedCatalog:
    """Validate the whole document before any persistence.

    Rejects duplicate stable keys, ambiguous source-code combinations
    (duplicate ``all``, ``all`` mixed with an age partition, incomplete,
    duplicated or single-group age partitions), invalid
    policy/capacity combinations, unsupported membership selectors,
    missing required names/codes and fields that exceed the persisted
    ``max_length``. Raises :class:`CatalogValidationError` on the first
    problem.
    """
    schema_version = document.get("schema_version")
    source_reference = document.get("source_reference")
    raw_groups = document.get("groups")

    if not isinstance(schema_version, str) or not schema_version.strip():
        raise CatalogValidationError(
            "Campo 'schema_version' ausente ou vazio."
        )
    _reject_overlong(
        schema_version, "schema_version", MAX_SCHEMA_VERSION
    )
    algorithm_version = _validate_algorithm_context(
        schema_version.strip(),
        document.get("occupancy_algorithm_version"),
    )
    if not isinstance(source_reference, str) or not source_reference.strip():
        raise CatalogValidationError(
            "Campo 'source_reference' ausente ou vazio."
        )
    _reject_overlong(
        source_reference, "source_reference", MAX_SOURCE_REFERENCE
    )
    if not isinstance(raw_groups, list) or not raw_groups:
        raise CatalogValidationError("Campo 'groups' ausente ou vazio.")

    groups: list[GroupSpec] = []
    seen_stable_keys: set[str] = set()
    memberships_by_code: dict[str, list[tuple[str, str]]] = {}

    for index, raw_group in enumerate(raw_groups):
        group = _validate_group(raw_group, index)
        if group.stable_key in seen_stable_keys:
            raise CatalogValidationError(
                f"Chave estável duplicada: '{group.stable_key}'."
            )
        seen_stable_keys.add(group.stable_key)
        for membership in group.memberships:
            memberships_by_code.setdefault(membership.source_code, []).append(
                (group.stable_key, membership.age_selector)
            )
        groups.append(group)

    _validate_code_combinations(memberships_by_code)

    return ValidatedCatalog(
        schema_version=schema_version.strip(),
        algorithm_version=algorithm_version,
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

    - the payload is read once; parse, validation and hash share the buffer;
    - the date must be strictly after ``timezone.localdate()`` and formatted
      exactly ``YYYY-MM-DD``;
    - the document is fully validated and hashed before any write;
    - persistence happens in one atomic transaction;
    - the same date/hash is an idempotent no-op, even after a lost race;
    - the same date/different hash raises :class:`CatalogConflictError`;
    - ``--dry-run`` never persists.
    """
    path = Path(input_path)
    try:
        raw_document = path.read_bytes()
    except OSError as exc:
        raise CatalogValidationError(
            f"Não foi possível ler '{path.name}'."
        ) from exc
    document = parse_catalog_document(raw_document)
    document_sha256 = hashlib.sha256(raw_document).hexdigest()
    validated = validate_catalog_document(document)
    effective_date = _parse_future_date(effective_from)

    base_result = ActivationResult(
        effective_from=effective_date,
        document_sha256=document_sha256,
        created=False,
        group_count=validated.group_count,
        member_count=validated.membership_count,
        code_count=validated.code_count,
        capacity_group_count=validated.capacity_group_count,
        standard_group_count=validated.standard_group_count,
        unrated_group_count=validated.unrated_group_count,
        known_capacity=validated.known_capacity,
        calculable_capacity=validated.calculable_capacity,
        algorithm_version=validated.algorithm_version,
    )

    if dry_run:
        return base_result

    try:
        with transaction.atomic():
            existing = _find_locked_version(effective_date)
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
        return _recover_from_lost_race(
            effective_date, document_sha256, base_result, exc
        )


def _find_locked_version(
    effective_date: date,
) -> CapacityCatalogVersion | None:
    """Select the existing version for update inside the transaction."""
    return (
        CapacityCatalogVersion.objects.select_for_update()
        .filter(effective_from=effective_date)
        .first()
    )


def _recover_from_lost_race(
    effective_date: date,
    document_sha256: str,
    base_result: ActivationResult,
    cause: IntegrityError,
) -> ActivationResult:
    """Re-read the winner after an IntegrityError and resolve by hash."""
    winner = CapacityCatalogVersion.objects.filter(
        effective_from=effective_date
    ).first()
    if winner is None:
        raise CatalogConflictError(
            f"Não foi possível publicar o catálogo para {effective_date} "
            "em corrida concorrente."
        ) from cause
    if winner.source_sha256 == document_sha256:
        return base_result
    raise CatalogConflictError(
        f"Data {effective_date} já possui catálogo com hash diferente."
    ) from cause


def _parse_future_date(value: str | date) -> date:
    if not isinstance(value, date):
        if _ISO_DATE_PATTERN.fullmatch(value) is None:
            raise CatalogValidationError(
                f"Data efetiva inválida: '{value}' "
                "(esperado YYYY-MM-DD)."
            )
        try:
            effective_date = date.fromisoformat(value)
        except ValueError as exc:
            raise CatalogValidationError(
                f"Data efetiva inválida: '{value}' "
                "(esperado YYYY-MM-DD)."
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


def _reject_overlong(
    value: str,
    field_name: str,
    max_length: int,
    context: str = "",
) -> None:
    if len(value) > max_length:
        prefix = f"{context}: " if context else ""
        raise CatalogValidationError(
            f"{prefix}'{field_name}' excede {max_length} caracteres."
        )


def _validate_algorithm_context(
    schema_version: str, raw_algorithm: Any
) -> str | None:
    """Resolve o contexto explícito de algoritmo a partir do schema.

    Schemas históricos permanecem válidos sem algoritmo (despacho
    estrutural v1/v2 preservado) e rejeitam o campo. O schema atual exige
    um algoritmo da allowlist, declarado textualmente no documento: nunca
    inferido por nome de arquivo, hash, data ou estrutura de grupos.
    """
    if schema_version == SCHEMA_VERSION_WITH_ALGORITHM:
        if not isinstance(raw_algorithm, str) or not raw_algorithm.strip():
            raise CatalogValidationError(
                "Schema '2.0' exige 'occupancy_algorithm_version' não vazio."
            )
        algorithm = raw_algorithm.strip()
        _reject_overlong(
            algorithm, "occupancy_algorithm_version", MAX_ALGORITHM_VERSION
        )
        if algorithm not in ALLOWED_ALGORITHM_VERSIONS:
            raise CatalogValidationError(
                f"Algoritmo de ocupação '{algorithm}' não suportado."
            )
        return algorithm
    if schema_version in LEGACY_SCHEMA_VERSIONS:
        if raw_algorithm is not None:
            raise CatalogValidationError(
                "Campo 'occupancy_algorithm_version' exige schema_version "
                "'2.0'."
            )
        return None
    raise CatalogValidationError(
        f"Versão de schema não suportada: '{schema_version}'."
    )


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
    _reject_overlong(
        stable_key, "stable_key", MAX_STABLE_KEY, f"Grupo {index}"
    )
    if not isinstance(display_name, str) or not display_name.strip():
        raise CatalogValidationError(
            f"Grupo {index}: 'display_name' ausente ou vazio."
        )
    _reject_overlong(
        display_name, "display_name", MAX_DISPLAY_NAME, f"Grupo {index}"
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


def _validate_code_combinations(
    memberships_by_code: dict[str, list[tuple[str, str]]],
) -> None:
    """Reject ambiguous memberships for any source code.

    A code maps either to exactly one ``all`` membership or to exactly
    two memberships, one ``under_12`` and one ``age_12_or_over``, in two
    different official groups. Any other combination is ambiguous and
    rejected before persistence.
    """
    for code, entries in memberships_by_code.items():
        selectors = [selector for _, selector in entries]
        if CapacityMembershipSelector.ALL in selectors:
            if len(entries) != 1:
                raise CatalogValidationError(
                    f"Código fonte '{code}' não pode combinar 'all' com "
                    "outra associação."
                )
            continue
        expected_partition = sorted(
            [
                CapacityMembershipSelector.UNDER_12,
                CapacityMembershipSelector.AGE_12_OR_OVER,
            ]
        )
        if len(entries) != 2 or sorted(selectors) != expected_partition:
            raise CatalogValidationError(
                f"Código fonte '{code}' exige exatamente uma associação "
                "'all' ou o par completo 'under_12' + 'age_12_or_over'."
            )
        group_keys = {group_key for group_key, _ in entries}
        if len(group_keys) != 2:
            raise CatalogValidationError(
                f"Código fonte '{code}' particionado deve pertencer a "
                "grupos oficiais distintos."
            )


def _validate_membership(raw_code: Any, group_index: int) -> MembershipSpec:
    if not isinstance(raw_code, dict):
        raise CatalogValidationError(
            f"Grupo {group_index}: membro deve ser um objeto."
        )
    source_code = raw_code.get("source_code")
    configured_name = raw_code.get("configured_source_name")
    age_selector = raw_code.get("age_selector")
    if age_selector is None:
        age_selector = CapacityMembershipSelector.ALL
    elif age_selector not in _ALLOWED_SELECTORS:
        raise CatalogValidationError(
            f"Grupo {group_index}: seletor '{age_selector}' não suportado."
        )
    if not isinstance(source_code, str) or not source_code.strip():
        raise CatalogValidationError(
            f"Grupo {group_index}: 'source_code' ausente ou vazio."
        )
    _reject_overlong(
        source_code,
        "source_code",
        MAX_SOURCE_CODE,
        f"Grupo {group_index}",
    )
    if not isinstance(configured_name, str) or not configured_name.strip():
        raise CatalogValidationError(
            f"Grupo {group_index}: 'configured_source_name' ausente ou vazio."
        )
    _reject_overlong(
        configured_name,
        "configured_source_name",
        MAX_CONFIGURED_SOURCE_NAME,
        f"Grupo {group_index}",
    )
    return MembershipSpec(
        source_code=source_code.strip(),
        configured_source_name=configured_name.strip(),
        age_selector=age_selector,
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
        algorithm_version=validated.algorithm_version,
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
                    age_selector=membership.age_selector,
                )
                for membership in group.memberships
            ]
        )
