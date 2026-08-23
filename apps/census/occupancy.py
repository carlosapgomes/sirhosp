"""Immutable occupancy materialization for one explicit census run.

Four deterministic algorithm versions are dispatched from the persisted
catalog context: ``occupancy-v1`` for legacy catalogs without age partitions,
``occupancy-v2`` for corrected age-partitioned catalogs, ``occupancy-v3`` for
catalogs that explicitly declare the physical-position normalization and
``occupancy-v4`` for future catalogs that declare typed conflict
classification with actionable quality. Measurements are immutable and never
recalculated.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacityMembershipSelector,
    CapacitySectorMembership,
    CensusSnapshot,
    DailyGroupOccupancySummary,
    DailyOccupancySummary,
    OccupancyAgeBand,
    OccupancyCalculationStatus,
    OccupancyGroupMeasurement,
    OccupancyMeasurement,
)
from apps.ingestion.models import IngestionRun

ALGORITHM_VERSION = "occupancy-v1"
ALGORITHM_VERSION_V2 = "occupancy-v2"
ALGORITHM_VERSION_V3 = "occupancy-v3"
ALGORITHM_VERSION_V4 = "occupancy-v4"
_CENSUS_INTENT = "census_extraction"
_PERCENT_QUANTUM = Decimal("0.01")
_STATUS_KEYS = tuple(BedStatus.values)


class OccupancyMaterializationError(Exception):
    """The selected run cannot safely produce an occupancy measurement."""


@dataclass(frozen=True)
class MaterializationResult:
    status: str
    measurement: OccupancyMeasurement | None
    created: bool


@dataclass(frozen=True)
class _ObservedRow:
    """Ephemeral in-memory census row used only during materialization.

    ``bed``, ``record`` and ``patient_name`` are needed only to normalize
    physical positions and build equivalent signatures in memory; they are
    never copied into persisted measurement or group history.
    """

    code: str
    name: str
    status: str
    age_band: str = OccupancyAgeBand.NOT_APPLICABLE
    bed: str = ""
    record: str = ""
    patient_name: str = ""


@dataclass(frozen=True)
class _PhysicalPosition:
    """One unambiguous physical position after normalization.

    Holds only the values needed to aggregate the position into the existing
    official group pipeline; no key, signature or patient identity survives.
    """

    code: str
    name: str
    status: str
    age_band: str


@dataclass
class _PositionDiagnostics:
    """Aggregate integer diagnostics of one physical normalization pass."""

    positions_by_status: dict[str, int]
    duplicate_extra_rows: int
    duplicate_occupied_rows: int
    conflict_positions: int
    conflict_occupied_rows: int
    unidentified_rows: int
    unidentified_occupied_rows: int


@dataclass(frozen=True)
class _KeyOutcome:
    """Classification of one normalized (source, bed) key.

    The ``primary`` row is the presentation representative of the position:
    the first equivalent row for an unambiguous position, or the first row of
    a conflicting key (used only for the bed label, never for a patient).
    """

    position: _PhysicalPosition | None
    primary: _ObservedRow
    duplicate_extra_rows: int
    duplicate_occupied_rows: int
    conflict_positions: int
    conflict_occupied_rows: int


@dataclass(frozen=True)
class _GroupValues:
    stable_key: str
    display_name: str
    calculation_policy: str
    calculation_status: str
    official_capacity: int | None
    occupied_count: int | None
    occupancy_percentage: Decimal | None
    exceeded_by: int | None
    status_counts: dict[str, int]
    components: list[dict[str, object]]
    official_availability: int | None = None


def materialize_occupancy_measurement(*, run_id: int) -> MaterializationResult:
    """Create or reuse one immutable measurement for a census extraction run.

    The run row is locked so concurrent requests serialize on the one-to-one
    idempotency key. Snapshot selection is strictly scoped to that run and only
    aggregate sector/status values are loaded into memory.
    """
    with transaction.atomic():
        run = _get_locked_census_run(run_id)
        existing = OccupancyMeasurement.objects.filter(census_run=run).first()
        if existing is not None:
            return MaterializationResult("existing", existing, False)

        rows = _load_observed_rows(run)
        captured_at = min(row[0] for row in rows)
        observed_rows = tuple(row[1] for row in rows)
        local_date = timezone.localtime(captured_at).date()
        catalog = _applicable_catalog(local_date)
        if catalog is None:
            return MaterializationResult("pre_activation", None, False)

        algorithm_version = _select_algorithm_version(catalog)
        group_values, totals = _calculate(
            catalog, observed_rows, algorithm_version
        )
        measurement = OccupancyMeasurement.objects.create(
            census_run=run,
            catalog=catalog,
            captured_at=captured_at,
            local_date=local_date,
            algorithm_version=algorithm_version,
            **totals,
        )
        OccupancyGroupMeasurement.objects.bulk_create(
            [
                OccupancyGroupMeasurement(
                    measurement=measurement,
                    stable_key=values.stable_key,
                    display_name=values.display_name,
                    calculation_policy=values.calculation_policy,
                    calculation_status=values.calculation_status,
                    official_capacity=values.official_capacity,
                    occupied_count=values.occupied_count,
                    occupancy_percentage=values.occupancy_percentage,
                    exceeded_by=values.exceeded_by,
                    official_availability=values.official_availability,
                    status_counts_json=values.status_counts,
                    components_json=values.components,
                )
                for values in group_values
            ]
        )
        refresh_daily_occupancy_summary(local_date=local_date)
        return MaterializationResult("created", measurement, True)


def refresh_daily_occupancy_summary(*, local_date: date) -> None:
    """Rebuild the deterministic daily summary for one local date.

    Derives the parent and the complete group-child set from every immutable
    measurement of that local date. Each census contributes one equal
    observation; means are computed from exact numerators/capacities and only
    the final stored decimal is rounded with ``ROUND_HALF_UP``. No time
    weighting, interpolation or projection is applied. Must be called inside
    the measurement creation transaction.

    A local date without measurements produces no row.
    """
    measurements = list(
        OccupancyMeasurement.objects.filter(local_date=local_date)
        .order_by("captured_at", "pk")
        .prefetch_related(
            Prefetch(
                "groups",
                queryset=OccupancyGroupMeasurement.objects.order_by(
                    "stable_key", "pk"
                ),
            )
        )
    )
    if not measurements:
        return

    parent, _ = DailyOccupancySummary.objects.update_or_create(
        local_date=local_date,
        defaults=_daily_parent_values(measurements),
    )
    for values in _daily_group_values(measurements):
        DailyGroupOccupancySummary.objects.update_or_create(
            daily_summary=parent,
            stable_key=values["stable_key"],
            defaults=values,
        )


def _daily_parent_values(
    measurements: list[OccupancyMeasurement],
) -> dict[str, object]:
    """Aggregate hospital-level daily statistics from day measurements.

    Every day measurement is kept for audit (``measurement_count``) but only
    daily-eligible measurements feed the official statistics. An
    ``occupancy-v1`` measurement is always eligible; an ``occupancy-v2``
    measurement with an unknown occupied age in a partitioned sector is
    excluded entirely from mean, minimum, maximum and exceeded-by. When no
    measurement is eligible the official fields stay null - no zero or
    previous value is fabricated.
    """
    eligible = [m for m in measurements if _is_daily_eligible(m)]
    reference = eligible[0] if eligible else measurements[0]
    occupied = [measurement.occupied_for_rate for measurement in eligible]
    exact_percentages = [
        _exact_percentage(
            measurement.occupied_for_rate, measurement.calculable_capacity
        )
        for measurement in eligible
        if measurement.calculable_capacity > 0
    ]
    return {
        "catalog": reference.catalog,
        "algorithm_version": reference.algorithm_version,
        "measurement_count": len(measurements),
        "eligible_measurement_count": len(eligible),
        "age_excluded_measurement_count": sum(
            1 for measurement in measurements if measurement.age_partial
        ),
        "position_excluded_measurement_count": sum(
            1 for measurement in measurements if measurement.position_partial
        ),
        "quality_warning_measurement_count": sum(
            1 for measurement in measurements if measurement.quality_warning
        ),
        "first_captured_at": measurements[0].captured_at,
        "last_captured_at": measurements[-1].captured_at,
        "known_capacity": reference.known_capacity,
        "calculable_capacity": reference.calculable_capacity,
        "official_sector_count": reference.official_sector_count,
        "official_calculable_sector_count": (
            reference.official_calculable_sector_count
        ),
        "mean_occupied": _rounded_mean(occupied) if eligible else None,
        "min_occupied": min(occupied) if eligible else None,
        "max_occupied": max(occupied) if eligible else None,
        "mean_percentage": (
            _rounded_mean(exact_percentages) if exact_percentages else None
        ),
        "min_percentage": (
            _rounded_decimal(min(exact_percentages))
            if exact_percentages
            else None
        ),
        "max_percentage": (
            _rounded_decimal(max(exact_percentages))
            if exact_percentages
            else None
        ),
        "max_exceeded_by": (
            max(measurement.exceeded_by for measurement in eligible)
            if eligible
            else None
        ),
        "min_observed_sector_count": min(
            measurement.observed_sector_count for measurement in measurements
        ),
        "max_observed_sector_count": max(
            measurement.observed_sector_count for measurement in measurements
        ),
        "min_capacity_covered_sector_count": min(
            measurement.capacity_covered_sector_count
            for measurement in measurements
        ),
        "max_capacity_covered_sector_count": max(
            measurement.capacity_covered_sector_count
            for measurement in measurements
        ),
        "min_calculable_sector_count": min(
            measurement.calculable_sector_count for measurement in measurements
        ),
        "max_calculable_sector_count": max(
            measurement.calculable_sector_count for measurement in measurements
        ),
    }


def _is_daily_eligible(measurement: OccupancyMeasurement) -> bool:
    """Decide whether one measurement feeds official daily statistics.

    ``occupancy-v1`` measurements are always complete. An ``occupancy-v2``
    measurement whose point rate is partial (unknown occupied age in an
    age-partitioned sector) is excluded entirely from official averages. An
    ``occupancy-v3`` measurement is additionally excluded when its physical
    positions are partial (conflict or occupied rows without bed identity).
    Every successfully materialized ``occupancy-v4`` measurement is eligible;
    quality warnings are tracked by a separate daily counter and never reuse
    the historical v2/v3 exclusion counters.
    """
    if measurement.algorithm_version == ALGORITHM_VERSION_V4:
        return True
    if measurement.position_partial is True:
        return False
    if measurement.algorithm_version in (
        ALGORITHM_VERSION_V2,
        ALGORITHM_VERSION_V3,
    ):
        return not measurement.age_partial
    return True


def _daily_group_values(
    measurements: list[OccupancyMeasurement],
) -> list[dict[str, object]]:
    """Aggregate per-group daily statistics from eligible day measurements."""
    by_key: dict[str, list[tuple[datetime, OccupancyGroupMeasurement]]] = (
        defaultdict(list)
    )
    for measurement in measurements:
        if not _is_daily_eligible(measurement):
            continue
        captured_at = measurement.captured_at
        for child in measurement.groups.all():
            by_key[child.stable_key].append((captured_at, child))

    values: list[dict[str, object]] = []
    for stable_key in sorted(by_key):
        entries = sorted(
            by_key[stable_key], key=lambda entry: (entry[0], entry[1].pk)
        )
        reference = entries[0][1]
        occupied = [
            child.occupied_count
            if child.occupied_count is not None
            else child.status_counts_json.get("occupied", 0)
            for _, child in entries
        ]
        exact_percentages = [
            _exact_percentage(child.occupied_count, child.official_capacity)
            for _, child in entries
            if child.official_capacity is not None
            and child.occupied_count is not None
        ]
        exceeded = [
            child.exceeded_by for _, child in entries if child.exceeded_by is not None
        ]
        values.append(
            {
                "stable_key": stable_key,
                "display_name": reference.display_name,
                "calculation_policy": reference.calculation_policy,
                "calculation_status": reference.calculation_status,
                "official_capacity": reference.official_capacity,
                "measurement_count": len(entries),
                "first_captured_at": entries[0][0],
                "last_captured_at": entries[-1][0],
                "mean_occupied": (
                    _rounded_mean(occupied) if occupied else None
                ),
                "min_occupied": min(occupied) if occupied else None,
                "max_occupied": max(occupied) if occupied else None,
                "mean_percentage": (
                    _rounded_mean(exact_percentages)
                    if exact_percentages
                    else None
                ),
                "min_percentage": (
                    _rounded_decimal(min(exact_percentages))
                    if exact_percentages
                    else None
                ),
                "max_percentage": (
                    _rounded_decimal(max(exact_percentages))
                    if exact_percentages
                    else None
                ),
                "max_exceeded_by": max(exceeded) if exceeded else None,
            }
        )
    return values


def _exact_percentage(occupied: int, capacity: int) -> Decimal:
    """Exact unrounded occupancy percentage for exact-value aggregation."""
    return Decimal(occupied) * Decimal(100) / Decimal(capacity)


def _rounded_mean(values: Iterable[int | Decimal]) -> Decimal:
    """Equal-weight mean rounded once with ``ROUND_HALF_UP``."""
    decimals = [Decimal(value) for value in values]
    return (
        sum(decimals, Decimal("0")) / Decimal(len(decimals))
    ).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def _rounded_decimal(value: Decimal) -> Decimal:
    """Round a single exact decimal once with ``ROUND_HALF_UP``."""
    return value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def _get_locked_census_run(run_id: int) -> IngestionRun:
    try:
        run = IngestionRun.objects.select_for_update().get(pk=run_id)
    except IngestionRun.DoesNotExist as exc:
        raise OccupancyMaterializationError(
            f"Census extraction run {run_id} does not exist."
        ) from exc
    if run.intent != _CENSUS_INTENT or run.status != "succeeded":
        raise OccupancyMaterializationError(
            f"Run {run_id} is not a completed census extraction."
        )
    return run


def _load_observed_rows(
    run: IngestionRun,
) -> list[tuple[datetime, _ObservedRow]]:
    snapshots = list(
        CensusSnapshot.objects.filter(ingestion_run=run)
        .order_by("captured_at", "pk")
        .values_list(
            "captured_at",
            "setor_codigo",
            "setor",
            "bed_status",
            "age_band",
            "leito",
            "prontuario",
            "nome",
        )
    )
    if not snapshots:
        raise OccupancyMaterializationError(
            f"Census extraction run {run.pk} has no snapshots."
        )
    return [
        (
            captured_at,
            _ObservedRow(
                code=(code or "").strip(),
                name=(name or "").strip(),
                status=status,
                age_band=age_band,
                bed=(bed or "").strip(),
                record=(record or "").strip(),
                patient_name=(patient_name or "").strip(),
            ),
        )
        for captured_at, code, name, status, age_band, bed, record, patient_name in snapshots
    ]


def _select_algorithm_version(
    catalog: CapacityCatalogVersion,
) -> str:
    """Dispatch the immutable algorithm from the persisted catalog context.

    A catalog that explicitly declares an algorithm version uses that exact
    value (``occupancy-v3`` for new publications). Legacy catalogs without
    the explicit field keep the deterministic structural dispatch: a catalog
    that partitions at least one source code by age band uses
    ``occupancy-v2``; a legacy catalog without partitions keeps
    ``occupancy-v1`` and its exact prior semantics. The choice depends only
    on the catalog that was already applicable on the capture local date,
    never on the current date or on any hardcoded date.
    """
    if catalog.algorithm_version:
        return catalog.algorithm_version
    for group in catalog.groups.all():
        for membership in group.memberships.all():
            if membership.age_selector != CapacityMembershipSelector.ALL:
                return ALGORITHM_VERSION_V2
    return ALGORITHM_VERSION


def _applicable_catalog(local_date: date) -> CapacityCatalogVersion | None:
    memberships = CapacitySectorMembership.objects.order_by("source_code", "pk")
    groups = CapacityGroupDefinition.objects.order_by("stable_key", "pk").prefetch_related(
        Prefetch("memberships", queryset=memberships)
    )
    return (
        CapacityCatalogVersion.objects.filter(effective_from__lte=local_date)
        .order_by("-effective_from", "-pk")
        .prefetch_related(Prefetch("groups", queryset=groups))
        .first()
    )


def _calculate(
    catalog: CapacityCatalogVersion,
    rows: tuple[_ObservedRow, ...],
    algorithm_version: str,
) -> tuple[list[_GroupValues], dict[str, object]]:
    """Dispatch the exact-run calculation for the selected algorithm.

    ``occupancy-v3`` and ``occupancy-v4`` normalize physical positions first;
    legacy v1/v2 keep their historical row-counting pipeline untouched. V4
    additionally types conflicts by their real impact and records an
    actionable quality flag.
    """
    if algorithm_version == ALGORITHM_VERSION_V3:
        return _calculate_v3(catalog, rows)
    if algorithm_version == ALGORITHM_VERSION_V4:
        return _calculate_v4(catalog, rows)
    return _calculate_legacy(catalog, rows, algorithm_version)


def _calculate_legacy(
    catalog: CapacityCatalogVersion,
    rows: tuple[_ObservedRow, ...],
    algorithm_version: str,
) -> tuple[list[_GroupValues], dict[str, object]]:
    by_code, by_band, blank_by_name = _aggregate_observations(rows)
    definitions = list(catalog.groups.all())
    membership_to_group = {
        membership.source_code: group
        for group in definitions
        for membership in group.memberships.all()
    }
    observed_identities = {
        ("code", row.code) if row.code else ("name", row.name) for row in rows
    }
    capacity_covered = sum(
        1
        for kind, identity in observed_identities
        if kind == "code"
        and identity in membership_to_group
        and membership_to_group[identity].official_capacity is not None
    )
    calculable = sum(
        1
        for kind, identity in observed_identities
        if kind == "code"
        and identity in membership_to_group
        and membership_to_group[identity].calculation_policy
        == CalculationPolicy.STANDARD
    )

    values: list[_GroupValues] = []
    configured_codes: set[str] = set()
    record_selector = algorithm_version == ALGORITHM_VERSION_V2
    for group in definitions:
        group_values = _calculate_catalog_group(
            group, by_code, by_band, record_selector=record_selector
        )
        values.append(group_values)
        configured_codes.update(
            membership.source_code for membership in group.memberships.all()
        )

    used_keys = {value.stable_key for value in values}
    for code in sorted(set(by_code) - configured_codes):
        values.append(
            _unmapped_group(
                identity_kind="code",
                identity=code,
                observations=by_code[code],
                used_keys=used_keys,
            )
        )
    for name in sorted(blank_by_name):
        values.append(
            _unmapped_group(
                identity_kind="blank",
                identity=name,
                observations={name: blank_by_name[name]},
                used_keys=used_keys,
            )
        )

    known_capacity = sum(
        group.official_capacity or 0 for group in definitions
    )
    calculable_capacity = sum(
        group.official_capacity or 0
        for group in definitions
        if group.calculation_policy == CalculationPolicy.STANDARD
    )
    occupied_for_rate = sum(
        value.occupied_count or 0
        for value in values
        if value.calculation_status == OccupancyCalculationStatus.CALCULATED
    )
    percentage = _percentage(occupied_for_rate, calculable_capacity)
    totals: dict[str, object] = {
        "observed_sector_count": len(observed_identities),
        "capacity_covered_sector_count": capacity_covered,
        "calculable_sector_count": calculable,
        "known_capacity": known_capacity,
        "calculable_capacity": calculable_capacity,
        "occupied_for_rate": occupied_for_rate,
        "occupancy_percentage": percentage,
        "exceeded_by": max(occupied_for_rate - calculable_capacity, 0),
    }
    if algorithm_version == ALGORITHM_VERSION_V2:
        partitioned_codes = {
            membership.source_code
            for group in definitions
            for membership in group.memberships.all()
            if membership.age_selector != CapacityMembershipSelector.ALL
        }
        unknown_age_count = sum(
            1
            for row in rows
            if row.code in partitioned_codes
            and row.age_band == OccupancyAgeBand.UNKNOWN
            and row.status == BedStatus.OCCUPIED
        )
        totals.update(
            {
                "official_sector_count": len(definitions),
                "official_capacity_sector_count": sum(
                    1
                    for group in definitions
                    if group.official_capacity is not None
                ),
                "official_calculable_sector_count": sum(
                    1
                    for group in definitions
                    if group.calculation_policy
                    == CalculationPolicy.STANDARD
                ),
                "unknown_age_count": unknown_age_count,
                "age_partial": unknown_age_count > 0,
            }
        )
    return sorted(values, key=lambda value: value.stable_key), totals


def _calculate_v3(
    catalog: CapacityCatalogVersion,
    rows: tuple[_ObservedRow, ...],
) -> tuple[list[_GroupValues], dict[str, object]]:
    """Materialize ``occupancy-v3`` from normalized physical positions.

    Raw rows are collapsed into unambiguous physical positions keyed by
    normalized source identity plus normalized bed. Exact duplicates count
    once; conflicting positions and occupied rows without a bed never enter
    official numerators. The resulting positions feed the same official
    group pipeline as v2 (age selectors included), and the measurement
    persists a closed aggregate reconciliation and non-compensated
    availability.
    """
    positions, diagnostics = _normalize_positions(rows)
    by_code, by_band, blank_by_name = _aggregate_observations(
        _position_rows(positions)
    )
    definitions = list(catalog.groups.all())
    membership_to_group = {
        membership.source_code: group
        for group in definitions
        for membership in group.memberships.all()
    }
    observed_identities = {
        ("code", row.code) if row.code else ("name", row.name) for row in rows
    }
    capacity_covered = sum(
        1
        for kind, identity in observed_identities
        if kind == "code"
        and identity in membership_to_group
        and membership_to_group[identity].official_capacity is not None
    )
    calculable = sum(
        1
        for kind, identity in observed_identities
        if kind == "code"
        and identity in membership_to_group
        and membership_to_group[identity].calculation_policy
        == CalculationPolicy.STANDARD
    )

    values: list[_GroupValues] = []
    configured_codes: set[str] = set()
    for group in definitions:
        values.append(
            _calculate_catalog_group(
                group, by_code, by_band, record_selector=True
            )
        )
        configured_codes.update(
            membership.source_code for membership in group.memberships.all()
        )

    used_keys = {value.stable_key for value in values}
    for code in sorted(set(by_code) - configured_codes):
        values.append(
            _unmapped_group(
                identity_kind="code",
                identity=code,
                observations=by_code[code],
                used_keys=used_keys,
            )
        )
    for name in sorted(blank_by_name):
        values.append(
            _unmapped_group(
                identity_kind="blank",
                identity=name,
                observations={name: blank_by_name[name]},
                used_keys=used_keys,
            )
        )

    partitioned_codes = {
        membership.source_code
        for group in definitions
        for membership in group.memberships.all()
        if membership.age_selector != CapacityMembershipSelector.ALL
    }
    known_capacity = sum(group.official_capacity or 0 for group in definitions)
    calculable_capacity = sum(
        group.official_capacity or 0
        for group in definitions
        if group.calculation_policy == CalculationPolicy.STANDARD
    )
    occupied_for_rate = sum(
        value.occupied_count or 0
        for value in values
        if value.calculation_status == OccupancyCalculationStatus.CALCULATED
    )
    percentage = _percentage(occupied_for_rate, calculable_capacity)

    unknown_age_3a_rows, outside_calculable, official_numerator = (
        _classify_occupied_positions(
            positions=positions,
            partitioned_codes=partitioned_codes,
            membership_to_group=membership_to_group,
        )
    )

    values_with_availability: list[_GroupValues] = []
    group_availability_sum = 0
    group_exceeded_sum = 0
    for value in values:
        if value.calculation_status == OccupancyCalculationStatus.CALCULATED:
            assert value.official_capacity is not None
            assert value.occupied_count is not None
            availability = max(value.official_capacity - value.occupied_count, 0)
            value = replace(value, official_availability=availability)
            group_availability_sum += availability
            assert value.exceeded_by is not None
            group_exceeded_sum += value.exceeded_by
        values_with_availability.append(value)
    values = values_with_availability

    reconciliation = _reconciliation_json(
        rows=rows,
        diagnostics=diagnostics,
        unknown_age_3a_rows=unknown_age_3a_rows,
        outside_calculable=outside_calculable,
        official_numerator=official_numerator,
    )
    totals: dict[str, object] = {
        "observed_sector_count": len(observed_identities),
        "capacity_covered_sector_count": capacity_covered,
        "calculable_sector_count": calculable,
        "known_capacity": known_capacity,
        "calculable_capacity": calculable_capacity,
        "occupied_for_rate": occupied_for_rate,
        "occupancy_percentage": percentage,
        "exceeded_by": group_exceeded_sum,
        "official_sector_count": len(definitions),
        "official_capacity_sector_count": sum(
            1 for group in definitions if group.official_capacity is not None
        ),
        "official_calculable_sector_count": sum(
            1
            for group in definitions
            if group.calculation_policy == CalculationPolicy.STANDARD
        ),
        "unknown_age_count": unknown_age_3a_rows,
        "age_partial": unknown_age_3a_rows > 0,
        "position_partial": (
            diagnostics.conflict_positions > 0
            or diagnostics.unidentified_occupied_rows > 0
        ),
        "official_availability": group_availability_sum,
        "physical_reconciliation_json": reconciliation,
    }
    return sorted(values, key=lambda value: value.stable_key), totals


def _calculate_v4(
    catalog: CapacityCatalogVersion,
    rows: tuple[_ObservedRow, ...],
) -> tuple[list[_GroupValues], dict[str, object]]:
    """Materialize ``occupancy-v4`` from typed physical positions.

    Raw rows are collapsed by normalized source identity plus bed; exact
    duplicates are consolidated before conflict classification. Unique
    signatures are typed by precedence into occupant, status and age
    conflicts. An occupant-only conflict counts one occupied position without
    choosing a patient; status and age ambiguity never feed official
    numerators; non-partitioned age metadata drift keeps the occupation.
    Every successfully materialized measurement is daily-eligible and records
    an actionable quality flag with a closed schema 2 reconciliation.
    """
    definitions = list(catalog.groups.all())
    group_by_code: dict[str, CapacityGroupDefinition] = {}
    group_by_band: dict[tuple[str, str], CapacityGroupDefinition] = {}
    partitioned_codes: set[str] = set()
    for group in definitions:
        for membership in group.memberships.all():
            # ``group_by_code`` mirrors the legacy last-wins code lookup so
            # coverage semantics stay identical to v2/v3; the per-band map is
            # used only for counting partitioned positions.
            group_by_code[membership.source_code] = group
            if membership.age_selector == CapacityMembershipSelector.ALL:
                continue
            group_by_band[
                (membership.source_code, membership.age_selector)
            ] = group
            partitioned_codes.add(membership.source_code)

    positions, diagnostics = _normalize_positions_v4(
        rows, partitioned_codes
    )
    by_code, by_band, blank_by_name = _aggregate_observations(
        _position_rows(positions)
    )
    observed_identities = {
        ("code", row.code) if row.code else ("name", row.name) for row in rows
    }
    capacity_covered = sum(
        1
        for kind, identity in observed_identities
        if kind == "code"
        and identity in group_by_code
        and group_by_code[identity].official_capacity is not None
    )
    calculable = sum(
        1
        for kind, identity in observed_identities
        if kind == "code"
        and identity in group_by_code
        and group_by_code[identity].calculation_policy
        == CalculationPolicy.STANDARD
    )

    values: list[_GroupValues] = []
    configured_codes: set[str] = set()
    for group in definitions:
        values.append(
            _calculate_catalog_group(
                group, by_code, by_band, record_selector=True
            )
        )
        configured_codes.update(
            membership.source_code for membership in group.memberships.all()
        )

    used_keys = {value.stable_key for value in values}
    for code in sorted(set(by_code) - configured_codes):
        values.append(
            _unmapped_group(
                identity_kind="code",
                identity=code,
                observations=by_code[code],
                used_keys=used_keys,
            )
        )
    for name in sorted(blank_by_name):
        values.append(
            _unmapped_group(
                identity_kind="blank",
                identity=name,
                observations={name: blank_by_name[name]},
                used_keys=used_keys,
            )
        )

    known_capacity = sum(group.official_capacity or 0 for group in definitions)
    calculable_capacity = sum(
        group.official_capacity or 0
        for group in definitions
        if group.calculation_policy == CalculationPolicy.STANDARD
    )
    occupied_for_rate = sum(
        value.occupied_count or 0
        for value in values
        if value.calculation_status == OccupancyCalculationStatus.CALCULATED
    )
    percentage = _percentage(occupied_for_rate, calculable_capacity)

    values_with_availability: list[_GroupValues] = []
    group_availability_sum = 0
    group_exceeded_sum = 0
    for value in values:
        if value.calculation_status == OccupancyCalculationStatus.CALCULATED:
            assert value.official_capacity is not None
            assert value.occupied_count is not None
            availability = max(value.official_capacity - value.occupied_count, 0)
            value = replace(value, official_availability=availability)
            group_availability_sum += availability
            assert value.exceeded_by is not None
            group_exceeded_sum += value.exceeded_by
        values_with_availability.append(value)
    values = values_with_availability

    official_numerator, unrated, unmapped, linked_pending = (
        _classify_v4_counted_positions(
            positions=positions,
            partitioned_codes=partitioned_codes,
            group_by_code=group_by_code,
            group_by_band=group_by_band,
        )
    )
    reconciliation = _reconciliation_v4_json(
        rows=rows,
        diagnostics=diagnostics,
        official_numerator=official_numerator,
        unrated=unrated,
        unmapped=unmapped,
        linked_pending=linked_pending,
    )
    totals: dict[str, object] = {
        "observed_sector_count": len(observed_identities),
        "capacity_covered_sector_count": capacity_covered,
        "calculable_sector_count": calculable,
        "known_capacity": known_capacity,
        "calculable_capacity": calculable_capacity,
        "occupied_for_rate": occupied_for_rate,
        "occupancy_percentage": percentage,
        "exceeded_by": group_exceeded_sum,
        "official_sector_count": len(definitions),
        "official_capacity_sector_count": sum(
            1 for group in definitions if group.official_capacity is not None
        ),
        "official_calculable_sector_count": sum(
            1
            for group in definitions
            if group.calculation_policy == CalculationPolicy.STANDARD
        ),
        "unknown_age_count": 0,
        "age_partial": False,
        "position_partial": None,
        "official_availability": group_availability_sum,
        "physical_reconciliation_json": reconciliation,
        "quality_warning": reconciliation["quality_warning"],
    }
    return sorted(values, key=lambda value: value.stable_key), totals


def _normalize_identity(value: str) -> str:
    """Deterministic small normalization for source and bed identities.

    Strips surrounding whitespace, uppercases and collapses inner runs of
    whitespace. Deliberately conservative: no new library, no Unicode
    folding and no leading-zero semantics.
    """
    return " ".join(value.strip().upper().split())


def _row_signature(row: _ObservedRow) -> tuple[object, ...]:
    """Equivalent-observation signature for one raw row.

    An occupied signature covers status, normalized record number, normalized
    patient name and age band; a non-occupied signature covers only status.
    The signature exists only in memory and is never persisted.
    """
    if row.status == BedStatus.OCCUPIED:
        return (
            BedStatus.OCCUPIED,
            _normalize_identity(row.record),
            _normalize_identity(row.patient_name),
            row.age_band,
        )
    return (row.status,)


def _normalize_positions(
    rows: tuple[_ObservedRow, ...],
) -> tuple[list[_PhysicalPosition], _PositionDiagnostics]:
    """Collapse raw rows into unambiguous physical positions.

    The physical key is normalized source identity (code, or sector name as
    fallback) plus normalized bed. A row without a usable bed stays an
    unidentified raw row. Repeated equivalent signatures become one position
    plus duplicate extra rows; divergent signatures on the same key become
    one conflicting position that never feeds an official numerator.
    """
    positions_by_status = {status: 0 for status in _STATUS_KEYS}
    duplicate_extra = 0
    duplicate_occupied = 0
    conflict_positions = 0
    conflict_occupied = 0
    unidentified_rows = 0
    unidentified_occupied = 0

    by_key: dict[tuple[str, str], list[_ObservedRow]] = defaultdict(list)
    for row in rows:
        bed = _normalize_identity(row.bed)
        if not bed:
            unidentified_rows += 1
            if row.status == BedStatus.OCCUPIED:
                unidentified_occupied += 1
            continue
        source = (
            _normalize_identity(row.code)
            if row.code
            else _normalize_identity(row.name)
        )
        by_key[(source, bed)].append(row)

    positions: list[_PhysicalPosition] = []
    for key_rows in by_key.values():
        outcome = _classify_key_rows(key_rows)
        if outcome.position is not None:
            positions.append(outcome.position)
            positions_by_status[outcome.position.status] += 1
        duplicate_extra += outcome.duplicate_extra_rows
        duplicate_occupied += outcome.duplicate_occupied_rows
        conflict_positions += outcome.conflict_positions
        conflict_occupied += outcome.conflict_occupied_rows

    diagnostics = _PositionDiagnostics(
        positions_by_status=positions_by_status,
        duplicate_extra_rows=duplicate_extra,
        duplicate_occupied_rows=duplicate_occupied,
        conflict_positions=conflict_positions,
        conflict_occupied_rows=conflict_occupied,
        unidentified_rows=unidentified_rows,
        unidentified_occupied_rows=unidentified_occupied,
    )
    return positions, diagnostics


def _classify_key_rows(key_rows: list[_ObservedRow]) -> _KeyOutcome:
    """Classify one normalized (source, bed) key into position or conflict.

    Equivalent signatures collapse into one unambiguous physical position
    (the first row is the presentation primary); divergent signatures on the
    same key become one conflicting position that never feeds an official
    numerator and never chooses a winning row. Shared by materialization and
    by the physical presentation so both realities use the same contract.
    """
    signature_rows: dict[tuple[object, ...], list[_ObservedRow]] = (
        defaultdict(list)
    )
    for row in key_rows:
        signature_rows[_row_signature(row)].append(row)
    if len(signature_rows) > 1:
        return _KeyOutcome(
            position=None,
            primary=key_rows[0],
            duplicate_extra_rows=0,
            duplicate_occupied_rows=0,
            conflict_positions=1,
            conflict_occupied_rows=sum(
                1 for row in key_rows if row.status == BedStatus.OCCUPIED
            ),
        )
    (_, same_rows), = signature_rows.items()
    primary = same_rows[0]
    return _KeyOutcome(
        position=_PhysicalPosition(
            code=primary.code,
            name=primary.name,
            status=primary.status,
            age_band=primary.age_band,
        ),
        primary=primary,
        duplicate_extra_rows=len(same_rows) - 1,
        duplicate_occupied_rows=(
            len(same_rows) - 1 if primary.status == BedStatus.OCCUPIED else 0
        ),
        conflict_positions=0,
        conflict_occupied_rows=0,
    )


def _position_rows(
    positions: Iterable[_PhysicalPosition],
) -> tuple[_ObservedRow, ...]:
    """Project unambiguous positions into the shared observation pipeline."""
    return tuple(
        _ObservedRow(
            code=position.code,
            name=position.name,
            status=position.status,
            age_band=position.age_band,
        )
        for position in positions
    )


def _classify_occupied_positions(
    *,
    positions: Iterable[_PhysicalPosition],
    partitioned_codes: set[str],
    membership_to_group: dict[str, CapacityGroupDefinition],
) -> tuple[int, int, int]:
    """Classify every unambiguous occupied position for the bridge.

    Returns ``(unknown_age_3a_rows, outside_calculable, official_numerator)``.
    Positions in partitioned sectors with unknown band are excluded for age;
    positions whose group is unrated, linked-pending or unmapped are excluded
    as non-calculable; the remainder feeds the official numerator.
    """
    unknown_age_3a_rows = 0
    outside_calculable = 0
    official_numerator = 0
    for position in positions:
        if position.status != BedStatus.OCCUPIED:
            continue
        if position.code in partitioned_codes:
            if position.age_band == OccupancyAgeBand.UNKNOWN:
                unknown_age_3a_rows += 1
                continue
        group = membership_to_group.get(position.code)
        if (
            group is not None
            and group.calculation_policy == CalculationPolicy.STANDARD
        ):
            official_numerator += 1
        else:
            outside_calculable += 1
    return unknown_age_3a_rows, outside_calculable, official_numerator


@dataclass(frozen=True)
class _V4KeyOutcome:
    """Classification of one normalized (source, bed) key under v4.

    ``position`` is the representative physical position only when the key is
    counted (unambiguous or occupant-conflict); status/age conflicts keep it
    None so they never feed an official numerator. ``conflict`` is one of
    ``""``, ``"status"``, ``"age"`` or ``"occupant"``. Duplicate extras are
    always separated from the unique signatures used for classification.
    """

    position: _PhysicalPosition | None
    conflict: str
    unknown_partition: bool
    age_metadata_drift: bool
    duplicate_extra_rows: int
    duplicate_occupied_extra_rows: int
    extra_occupied_rows: int
    status_conflict_occupied_rows: int
    age_conflict_occupied_rows: int


@dataclass
class _V4Diagnostics:
    """Aggregate integer diagnostics of one v4 normalization pass."""

    positions_by_status: dict[str, int]
    duplicate_extra_rows: int
    duplicate_occupied_extra_rows: int
    occupant_conflict_positions: int
    occupant_conflict_extra_occupied_rows: int
    status_conflict_positions: int
    status_conflict_occupied_rows: int
    age_conflict_positions: int
    age_conflict_occupied_rows: int
    age_metadata_drift_positions: int
    unidentified_rows: int
    unidentified_occupied_rows: int
    unknown_age_partition_positions: int


def _classify_key_rows_v4(
    key_rows: list[_ObservedRow], *, partitioned: bool
) -> _V4KeyOutcome:
    """Classify one v4 key after collapsing exact duplicates.

    Precedence, in tested order: (1) divergent statuses become a status
    conflict with no winning state; (2) all-occupied partitioned keys with
    divergent or unknown selectors become an age conflict with no winning age
    group; (3) all-occupied keys with one effective selector and divergent
    occupant evidence become an occupant conflict counting one position;
    (4) otherwise the key is an unambiguous position. In non-partitioned
    codes, age metadata drift alone never suppresses an unambiguous
    occupation.
    """
    signature_rows: dict[tuple[object, ...], list[_ObservedRow]] = (
        defaultdict(list)
    )
    for row in key_rows:
        signature_rows[_row_signature(row)].append(row)

    duplicate_extra = 0
    duplicate_occupied_extra = 0
    occupied_groups: list[list[_ObservedRow]] = []
    for same_rows in signature_rows.values():
        extras = len(same_rows) - 1
        duplicate_extra += extras
        if same_rows[0].status == BedStatus.OCCUPIED:
            duplicate_occupied_extra += extras
            occupied_groups.append(same_rows)

    if len(occupied_groups) != len(signature_rows):
        # At least one non-occupied unique signature: status divergence.
        return _V4KeyOutcome(
            position=None,
            conflict="status",
            unknown_partition=False,
            age_metadata_drift=False,
            duplicate_extra_rows=duplicate_extra,
            duplicate_occupied_extra_rows=duplicate_occupied_extra,
            extra_occupied_rows=0,
            status_conflict_occupied_rows=len(occupied_groups),
            age_conflict_occupied_rows=0,
        )

    if len(occupied_groups) == 1:
        (same_rows,) = occupied_groups
        row = same_rows[0]
        position = _PhysicalPosition(
            code=row.code,
            name=row.name,
            status=row.status,
            age_band=row.age_band,
        )
        if partitioned and row.age_band == OccupancyAgeBand.UNKNOWN:
            return _V4KeyOutcome(
                position=position,
                conflict="",
                unknown_partition=True,
                age_metadata_drift=False,
                duplicate_extra_rows=duplicate_extra,
                duplicate_occupied_extra_rows=duplicate_occupied_extra,
                extra_occupied_rows=0,
                status_conflict_occupied_rows=0,
                age_conflict_occupied_rows=0,
            )
        return _V4KeyOutcome(
            position=position,
            conflict="",
            unknown_partition=False,
            age_metadata_drift=False,
            duplicate_extra_rows=duplicate_extra,
            duplicate_occupied_extra_rows=duplicate_occupied_extra,
            extra_occupied_rows=0,
            status_conflict_occupied_rows=0,
            age_conflict_occupied_rows=0,
        )

    bands = [rows[0].age_band for rows in occupied_groups]
    if partitioned:
        known_bands = {
            band for band in bands if band != OccupancyAgeBand.UNKNOWN
        }
        if len(known_bands) == 1 and len(known_bands) == len(set(bands)):
            # All alternatives share the same known effective selector.
            row = occupied_groups[0][0]
            return _V4KeyOutcome(
                position=_PhysicalPosition(
                    code=row.code,
                    name=row.name,
                    status=row.status,
                    age_band=row.age_band,
                ),
                conflict="occupant",
                unknown_partition=False,
                age_metadata_drift=False,
                duplicate_extra_rows=duplicate_extra,
                duplicate_occupied_extra_rows=duplicate_occupied_extra,
                extra_occupied_rows=len(occupied_groups) - 1,
                status_conflict_occupied_rows=0,
                age_conflict_occupied_rows=0,
            )
        return _V4KeyOutcome(
            position=None,
            conflict="age",
            unknown_partition=False,
            age_metadata_drift=False,
            duplicate_extra_rows=duplicate_extra,
            duplicate_occupied_extra_rows=duplicate_occupied_extra,
            extra_occupied_rows=0,
            status_conflict_occupied_rows=0,
            age_conflict_occupied_rows=len(occupied_groups),
        )

    occupants = {
        (rows[0].record, rows[0].patient_name) for rows in occupied_groups
    }
    if len(occupants) == 1:
        # Non-partitioned age metadata drift: the physical occupation is
        # unambiguous, so all rows collapse into one counted position and the
        # extra rows are consolidated like duplicates; the metadata drift is
        # recorded as an actionable warning, never as an omitted occupation.
        row = occupied_groups[0][0]
        return _V4KeyOutcome(
            position=_PhysicalPosition(
                code=row.code,
                name=row.name,
                status=row.status,
                age_band=row.age_band,
            ),
            conflict="",
            unknown_partition=False,
            age_metadata_drift=len(bands) > 1,
            duplicate_extra_rows=len(key_rows) - 1,
            duplicate_occupied_extra_rows=len(key_rows) - 1,
            extra_occupied_rows=0,
            status_conflict_occupied_rows=0,
            age_conflict_occupied_rows=0,
        )
    row = occupied_groups[0][0]
    return _V4KeyOutcome(
        position=_PhysicalPosition(
            code=row.code,
            name=row.name,
            status=row.status,
            age_band=row.age_band,
        ),
        conflict="occupant",
        unknown_partition=False,
        age_metadata_drift=False,
        duplicate_extra_rows=duplicate_extra,
        duplicate_occupied_extra_rows=duplicate_occupied_extra,
        extra_occupied_rows=len(occupied_groups) - 1,
        status_conflict_occupied_rows=0,
        age_conflict_occupied_rows=0,
    )


def _normalize_positions_v4(
    rows: tuple[_ObservedRow, ...],
    partitioned_codes: set[str],
) -> tuple[list[_PhysicalPosition], _V4Diagnostics]:
    """Collapse raw rows into v4 typed positions.

    The physical key is normalized source identity (code, or sector name as
    fallback) plus normalized bed. A row without a usable bed stays an
    unidentified raw row. Exact duplicates collapse first; unique signatures
    are then classified by precedence. Occupant-conflict keys contribute one
    representative position; status/age conflicts and unknown-partition
    positions never feed an official numerator.
    """
    positions_by_status = {status: 0 for status in _STATUS_KEYS}
    duplicate_extra = 0
    duplicate_occupied_extra = 0
    occupant_conflict_positions = 0
    occupant_conflict_extra_occupied_rows = 0
    status_conflict_positions = 0
    status_conflict_occupied_rows = 0
    age_conflict_positions = 0
    age_conflict_occupied_rows = 0
    age_metadata_drift_positions = 0
    unidentified_rows = 0
    unidentified_occupied_rows = 0
    unknown_age_partition_positions = 0

    by_key: dict[tuple[str, str], list[_ObservedRow]] = defaultdict(list)
    for row in rows:
        bed = _normalize_identity(row.bed)
        if not bed:
            unidentified_rows += 1
            if row.status == BedStatus.OCCUPIED:
                unidentified_occupied_rows += 1
            continue
        source = (
            _normalize_identity(row.code)
            if row.code
            else _normalize_identity(row.name)
        )
        by_key[(source, bed)].append(row)

    positions: list[_PhysicalPosition] = []
    for key_rows in by_key.values():
        partitioned = key_rows[0].code in partitioned_codes
        outcome = _classify_key_rows_v4(key_rows, partitioned=partitioned)
        if outcome.position is not None:
            positions.append(outcome.position)
            positions_by_status[outcome.position.status] += 1
        if outcome.conflict == "occupant":
            occupant_conflict_positions += 1
            occupant_conflict_extra_occupied_rows += (
                outcome.extra_occupied_rows
            )
        elif outcome.conflict == "status":
            status_conflict_positions += 1
            status_conflict_occupied_rows += (
                outcome.status_conflict_occupied_rows
            )
        elif outcome.conflict == "age":
            age_conflict_positions += 1
            age_conflict_occupied_rows += outcome.age_conflict_occupied_rows
        if outcome.unknown_partition:
            unknown_age_partition_positions += 1
        if outcome.age_metadata_drift:
            age_metadata_drift_positions += 1
        duplicate_extra += outcome.duplicate_extra_rows
        duplicate_occupied_extra += outcome.duplicate_occupied_extra_rows

    diagnostics = _V4Diagnostics(
        positions_by_status=positions_by_status,
        duplicate_extra_rows=duplicate_extra,
        duplicate_occupied_extra_rows=duplicate_occupied_extra,
        occupant_conflict_positions=occupant_conflict_positions,
        occupant_conflict_extra_occupied_rows=(
            occupant_conflict_extra_occupied_rows
        ),
        status_conflict_positions=status_conflict_positions,
        status_conflict_occupied_rows=status_conflict_occupied_rows,
        age_conflict_positions=age_conflict_positions,
        age_conflict_occupied_rows=age_conflict_occupied_rows,
        age_metadata_drift_positions=age_metadata_drift_positions,
        unidentified_rows=unidentified_rows,
        unidentified_occupied_rows=unidentified_occupied_rows,
        unknown_age_partition_positions=unknown_age_partition_positions,
    )
    return positions, diagnostics


def _classify_v4_counted_positions(
    *,
    positions: Iterable[_PhysicalPosition],
    partitioned_codes: set[str],
    group_by_code: dict[str, CapacityGroupDefinition],
    group_by_band: dict[tuple[str, str], CapacityGroupDefinition],
) -> tuple[int, int, int, int]:
    """Classify counted occupied positions into the second bridge.

    Returns ``(official_numerator, unrated, unmapped, linked_pending)``.
    Positions of partitioned codes are resolved by ``(code, age_band)``;
    unknown-band positions in partitioned codes are not counted at all (they
    belong to the first bridge as unknown partition positions).
    """
    official_numerator = 0
    unrated = 0
    unmapped = 0
    linked_pending = 0
    for position in positions:
        if position.status != BedStatus.OCCUPIED:
            continue
        if position.code in partitioned_codes:
            if position.age_band not in (
                OccupancyAgeBand.UNDER_12,
                OccupancyAgeBand.AGE_12_OR_OVER,
            ):
                continue
            group = group_by_band.get((position.code, position.age_band))
        else:
            group = group_by_code.get(position.code)
        if group is None:
            unmapped += 1
        elif group.calculation_policy == CalculationPolicy.STANDARD:
            official_numerator += 1
        elif group.calculation_policy == CalculationPolicy.UNRATED:
            unrated += 1
        else:
            linked_pending += 1
    return official_numerator, unrated, unmapped, linked_pending


# Allowlisted keys of the persisted v4 aggregate reconciliation. Only
# nonnegative integers, one boolean quality flag and the positions-by-status
# dict of integers are allowed; no row-level identity ever reaches this JSON.
_V4_RECONCILIATION_ALLOWLIST = frozenset(
    {
        "schema_version",
        "quality_warning",
        "raw_occupied_rows",
        "positions_by_status",
        "duplicate_extra_rows",
        "duplicate_occupied_extra_rows",
        "occupant_conflict_positions",
        "occupant_conflict_extra_occupied_rows",
        "status_conflict_positions",
        "status_conflict_occupied_rows",
        "age_conflict_positions",
        "age_conflict_occupied_rows",
        "age_metadata_drift_positions",
        "unidentified_rows",
        "unidentified_occupied_rows",
        "unknown_age_partition_positions",
        "counted_occupied_positions",
        "official_numerator",
        "occupied_unrated_positions",
        "occupied_unmapped_positions",
        "occupied_linked_pending_positions",
    }
)


def _reconciliation_v4_json(
    *,
    rows: tuple[_ObservedRow, ...],
    diagnostics: _V4Diagnostics,
    official_numerator: int,
    unrated: int,
    unmapped: int,
    linked_pending: int,
) -> dict[str, object]:
    """Build the closed schema 2 reconciliation for one v4 measurement.

    Two bridges hold by construction and are asserted here and re-checked by
    synthetic tests: the raw occupied-row bridge separates duplicate extras,
    conflict rows, unidentified rows, unknown partition positions and counted
    positions; the counted-position bridge separates the official numerator
    from the non-calculable policy states (unrated, unmapped, pending).
    """
    raw_occupied_rows = sum(
        1 for row in rows if row.status == BedStatus.OCCUPIED
    )
    counted_occupied_positions = (
        official_numerator + unrated + unmapped + linked_pending
    )
    bridge = (
        diagnostics.duplicate_occupied_extra_rows
        + diagnostics.occupant_conflict_extra_occupied_rows
        + diagnostics.status_conflict_occupied_rows
        + diagnostics.age_conflict_occupied_rows
        + diagnostics.unidentified_occupied_rows
        + diagnostics.unknown_age_partition_positions
        + counted_occupied_positions
    )
    assert bridge == raw_occupied_rows
    quality_warning = _v4_quality_warning(diagnostics, unmapped=unmapped)
    reconciliation: dict[str, object] = {
        "schema_version": 2,
        "quality_warning": quality_warning,
        "raw_occupied_rows": raw_occupied_rows,
        "positions_by_status": dict(diagnostics.positions_by_status),
        "duplicate_extra_rows": diagnostics.duplicate_extra_rows,
        "duplicate_occupied_extra_rows": (
            diagnostics.duplicate_occupied_extra_rows
        ),
        "occupant_conflict_positions": (
            diagnostics.occupant_conflict_positions
        ),
        "occupant_conflict_extra_occupied_rows": (
            diagnostics.occupant_conflict_extra_occupied_rows
        ),
        "status_conflict_positions": diagnostics.status_conflict_positions,
        "status_conflict_occupied_rows": (
            diagnostics.status_conflict_occupied_rows
        ),
        "age_conflict_positions": diagnostics.age_conflict_positions,
        "age_conflict_occupied_rows": diagnostics.age_conflict_occupied_rows,
        "age_metadata_drift_positions": (
            diagnostics.age_metadata_drift_positions
        ),
        "unidentified_rows": diagnostics.unidentified_rows,
        "unidentified_occupied_rows": (
            diagnostics.unidentified_occupied_rows
        ),
        "unknown_age_partition_positions": (
            diagnostics.unknown_age_partition_positions
        ),
        "counted_occupied_positions": counted_occupied_positions,
        "official_numerator": official_numerator,
        "occupied_unrated_positions": unrated,
        "occupied_unmapped_positions": unmapped,
        "occupied_linked_pending_positions": linked_pending,
    }
    assert set(reconciliation) == _V4_RECONCILIATION_ALLOWLIST
    return reconciliation


def _v4_quality_warning(
    diagnostics: _V4Diagnostics, *, unmapped: int
) -> bool:
    """Decide whether a v4 measurement carries actionable quality warnings.

    Conflicts of any type, occupied rows without position, unknown partition
    positions, non-partitioned age metadata drift and occupied unmapped
    positions are warnings. Intentional ``unrated`` policy and known-capacity
    ``linked_pending`` evidence are not quality failures.
    """
    return bool(
        diagnostics.occupant_conflict_positions
        or diagnostics.status_conflict_positions
        or diagnostics.age_conflict_positions
        or diagnostics.age_metadata_drift_positions
        or diagnostics.unidentified_occupied_rows
        or diagnostics.unknown_age_partition_positions
        or unmapped
    )


# Allowlisted keys of the persisted aggregate reconciliation. Only nonnegative
# integers are allowed; no row-level identity ever reaches this JSON.
_RECONCILIATION_ALLOWLIST = frozenset(
    {
        "schema_version",
        "raw_occupied_rows",
        "positions_by_status",
        "duplicate_extra_rows",
        "duplicate_occupied_rows",
        "conflict_positions",
        "conflict_occupied_rows",
        "unidentified_rows",
        "unidentified_occupied_rows",
        "unknown_age_3a_rows",
        "unambiguous_occupied_outside_calculable",
        "official_numerator",
    }
)


def _reconciliation_json(
    *,
    rows: tuple[_ObservedRow, ...],
    diagnostics: _PositionDiagnostics,
    unknown_age_3a_rows: int,
    outside_calculable: int,
    official_numerator: int,
) -> dict[str, int | dict[str, int]]:
    """Build the closed aggregate reconciliation for one v3 measurement.

    The bridge ``raw_occupied_rows == duplicate_occupied_rows +
    conflict_occupied_rows + unidentified_occupied_rows + unknown_age_3a_rows
    + unambiguous_occupied_outside_calculable + official_numerator`` holds by
    construction; an assertion documents the invariant and a test re-checks
    it synthetically.
    """
    raw_occupied_rows = sum(
        1 for row in rows if row.status == BedStatus.OCCUPIED
    )
    bridge = (
        diagnostics.duplicate_occupied_rows
        + diagnostics.conflict_occupied_rows
        + diagnostics.unidentified_occupied_rows
        + unknown_age_3a_rows
        + outside_calculable
        + official_numerator
    )
    assert bridge == raw_occupied_rows
    reconciliation: dict[str, int | dict[str, int]] = {
        "schema_version": 1,
        "raw_occupied_rows": raw_occupied_rows,
        "positions_by_status": dict(diagnostics.positions_by_status),
        "duplicate_extra_rows": diagnostics.duplicate_extra_rows,
        "duplicate_occupied_rows": diagnostics.duplicate_occupied_rows,
        "conflict_positions": diagnostics.conflict_positions,
        "conflict_occupied_rows": diagnostics.conflict_occupied_rows,
        "unidentified_rows": diagnostics.unidentified_rows,
        "unidentified_occupied_rows": diagnostics.unidentified_occupied_rows,
        "unknown_age_3a_rows": unknown_age_3a_rows,
        "unambiguous_occupied_outside_calculable": outside_calculable,
        "official_numerator": official_numerator,
    }
    assert set(reconciliation) == _RECONCILIATION_ALLOWLIST
    return reconciliation


def _aggregate_observations(
    rows: Iterable[_ObservedRow],
) -> tuple[
    dict[str, dict[str, Counter[str]]],
    dict[tuple[str, str], dict[str, Counter[str]]],
    dict[str, Counter[str]],
]:
    by_code: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    by_band: dict[tuple[str, str], dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    blank_by_name: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.code:
            by_code[row.code][row.name][row.status] += 1
            by_band[(row.code, row.age_band)][row.name][row.status] += 1
        else:
            blank_by_name[row.name][row.status] += 1
    return by_code, by_band, blank_by_name


def _calculate_catalog_group(
    group: CapacityGroupDefinition,
    by_code: dict[str, dict[str, Counter[str]]],
    by_band: dict[tuple[str, str], dict[str, Counter[str]]],
    *,
    record_selector: bool,
) -> _GroupValues:
    total_counts = Counter[str]()
    components: list[dict[str, object]] = []
    for membership in group.memberships.all():
        selector = membership.age_selector
        if selector == CapacityMembershipSelector.ALL:
            observations = by_code.get(membership.source_code, {})
        else:
            observations = by_band.get(
                (membership.source_code, selector), {}
            )
        recorded_selector = selector if record_selector else None
        if not observations:
            components.append(
                _component(
                    configured_code=membership.source_code,
                    configured_name=membership.configured_source_name,
                    observed_code=membership.source_code,
                    observed_name=None,
                    counts=Counter(),
                    mismatch=False,
                    selector=recorded_selector,
                )
            )
            continue
        for observed_name in sorted(observations):
            counts = observations[observed_name]
            total_counts.update(counts)
            components.append(
                _component(
                    configured_code=membership.source_code,
                    configured_name=membership.configured_source_name,
                    observed_code=membership.source_code,
                    observed_name=observed_name,
                    counts=counts,
                    mismatch=observed_name != membership.configured_source_name,
                    selector=recorded_selector,
                )
            )

    status_counts = _status_counts(total_counts)
    if group.calculation_policy == CalculationPolicy.STANDARD:
        occupied_count = status_counts[BedStatus.OCCUPIED]
        capacity = group.official_capacity
        assert capacity is not None
        return _GroupValues(
            stable_key=group.stable_key,
            display_name=group.display_name,
            calculation_policy=group.calculation_policy,
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=capacity,
            occupied_count=occupied_count,
            occupancy_percentage=_percentage(occupied_count, capacity),
            exceeded_by=max(occupied_count - capacity, 0),
            status_counts=status_counts,
            components=components,
        )

    status = (
        OccupancyCalculationStatus.LINKED_SLOTS_PENDING
        if group.calculation_policy == CalculationPolicy.LINKED_SLOTS_PENDING
        else OccupancyCalculationStatus.UNRATED
    )
    return _GroupValues(
        stable_key=group.stable_key,
        display_name=group.display_name,
        calculation_policy=group.calculation_policy,
        calculation_status=status,
        official_capacity=group.official_capacity,
        occupied_count=None,
        occupancy_percentage=None,
        exceeded_by=None,
        status_counts=status_counts,
        components=components,
    )


def _unmapped_group(
    *,
    identity_kind: str,
    identity: str,
    observations: dict[str, Counter[str]],
    used_keys: set[str],
) -> _GroupValues:
    total_counts = Counter[str]()
    components: list[dict[str, object]] = []
    observed_code = identity if identity_kind == "code" else ""
    for observed_name in sorted(observations):
        counts = observations[observed_name]
        total_counts.update(counts)
        components.append(
            _component(
                configured_code=None,
                configured_name=None,
                observed_code=observed_code,
                observed_name=observed_name,
                counts=counts,
                mismatch=False,
            )
        )
    stable_key = _synthetic_key(identity_kind, identity, used_keys)
    display_name = next(iter(sorted(observations)), "") or (
        identity if identity_kind == "code" else "Setor sem código"
    )
    return _GroupValues(
        stable_key=stable_key,
        display_name=display_name,
        calculation_policy="",
        calculation_status=OccupancyCalculationStatus.UNMAPPED,
        official_capacity=None,
        occupied_count=None,
        occupancy_percentage=None,
        exceeded_by=None,
        status_counts=_status_counts(total_counts),
        components=components,
    )


def _synthetic_key(identity_kind: str, identity: str, used_keys: set[str]) -> str:
    digest = hashlib.sha256(
        f"{identity_kind}\0{identity}".encode("utf-8")
    ).hexdigest()[:20]
    base = f"UNMAPPED-{identity_kind.upper()}-{digest}"
    candidate = base
    suffix = 1
    while candidate in used_keys:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_keys.add(candidate)
    return candidate


def _component(
    *,
    configured_code: str | None,
    configured_name: str | None,
    observed_code: str,
    observed_name: str | None,
    counts: Counter[str],
    mismatch: bool,
    selector: str | None = None,
) -> dict[str, object]:
    component: dict[str, object] = {
        "configured_code": configured_code,
        "configured_name": configured_name,
        "observed_code": observed_code,
        "observed_name": observed_name,
        "status_counts": _status_counts(counts),
        "source_name_mismatch": mismatch,
    }
    if selector is not None:
        component["age_selector"] = selector
    return component


def _status_counts(counts: Counter[str]) -> dict[str, int]:
    return {status: counts.get(status, 0) for status in _STATUS_KEYS}


def _percentage(occupied: int, capacity: int) -> Decimal | None:
    if capacity == 0:
        return None
    return (
        Decimal(occupied) * Decimal(100) / Decimal(capacity)
    ).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# SCOH-S4: /beds presentation helpers.
#
# These helpers assemble template-ready rows for the authenticated ``/beds``
# page. They consume only persisted measurement values and the raw beds of
# the exact latest census; they never select a measurement independently,
# never reuse an older measurement and never recalculate rates, coverage or
# adjusted occupancy in the view or template.
# ---------------------------------------------------------------------------


def resolve_exact_measurement(
    snapshots: QuerySet[CensusSnapshot],
) -> OccupancyMeasurement | None:
    """Return the measurement owned by the exact run of a latest census.

    The latest census is selected exactly as before; official statistics are
    only available when every row of that set resolves to one non-null
    ``IngestionRun`` and that exact run owns a persisted measurement. A
    runless census, an ambiguous multi-run set and an older measurement never
    produce statistics here.
    """
    run_ids = set(snapshots.values_list("ingestion_run_id", flat=True))
    if len(run_ids) != 1 or None in run_ids:
        return None
    run_id = run_ids.pop()
    assert run_id is not None
    return (
        OccupancyMeasurement.objects.filter(census_run_id=run_id)
        .select_related("catalog")
        .prefetch_related("groups")
        .first()
    )


_AUXILIARY_3A_STABLE_KEY = "AUX-3A-UNCLASSIFIED"
_AUXILIARY_3A_DISPLAY_NAME = "3A – posições sem classificação etária"
_AUXILIARY_3A_CALCULATION_STATUS = "auxiliary"


@dataclass
class _PresentationGroupRow:
    """Template-ready official group row assembled from persisted values."""

    stable_key: str
    display_name: str
    calculation_status: str
    official_capacity: int | None
    occupied_count: int | None
    occupancy_percentage: Decimal | None
    exceeded_by: int | None
    status_counts: dict[str, int]
    source_sectors: list[str]
    beds: list[dict[str, object]]
    name_mismatch: bool
    official_availability: int | None = None

    @property
    def total(self) -> int:
        return sum(self.status_counts.values())

    @property
    def over_capacity(self) -> bool:
        return (
            self.occupancy_percentage is not None
            and self.occupancy_percentage > Decimal("100.00")
        )


def build_official_group_rows(
    *,
    measurement: OccupancyMeasurement,
    snapshots: Iterable[CensusSnapshot],
    patient_map: dict[str, int] | None = None,
) -> list[_PresentationGroupRow]:
    """Group the exact latest-census beds under the persisted group rows.

    Consumes only persisted measurement values (display names, capacities,
    status counts, percentages, exceeded-by and calculation states) and the
    raw beds of the same census. For ``occupancy-v2`` an age-partitioned code
    is matched by ``(code, age_band)`` so Adulto and Infantil never overwrite
    each other: each occupied row with a valid band lands in exactly one
    virtual sector, while non-occupied rows and occupied rows with unknown
    band land once in a presentation-only auxiliary grouping without
    capacity or percentage. Shared ``all`` groups still appear once with
    combined counts and every contributing source sector and bed stays inside
    its expansion. No rate, coverage or adjusted occupancy value is computed
    here.
    """
    groups = list(measurement.groups.all())
    # ``occupancy-v2`` and ``occupancy-v3`` both partition age-partitioned
    # source codes (e.g. 654 into Adulto/Infantil); the v3 physical
    # normalization still assigns each unambiguous position to exactly one
    # persisted group band.
    is_partitioned = measurement.algorithm_version in (
        ALGORITHM_VERSION_V2,
        ALGORITHM_VERSION_V3,
    )

    code_to_group: dict[str, OccupancyGroupMeasurement] = {}
    blank_name_to_group: dict[str, OccupancyGroupMeasurement] = {}
    band_to_group: dict[tuple[str, str], OccupancyGroupMeasurement] = {}
    partitioned_codes: set[str] = set()
    for group in groups:
        for component in group.components_json:
            observed_code = str(component.get("observed_code") or "").strip()
            if observed_code:
                selector = str(component.get("age_selector") or "").strip()
                if is_partitioned and selector in (
                    OccupancyAgeBand.UNDER_12,
                    OccupancyAgeBand.AGE_12_OR_OVER,
                ):
                    band_to_group[(observed_code, selector)] = group
                    partitioned_codes.add(observed_code)
                else:
                    code_to_group[observed_code] = group
            else:
                observed_name = str(
                    component.get("observed_name") or ""
                ).strip()
                blank_name_to_group[observed_name] = group

    rows: dict[str, _PresentationGroupRow] = {
        group.stable_key: _PresentationGroupRow(
            stable_key=group.stable_key,
            display_name=group.display_name,
            calculation_status=group.calculation_status,
            official_capacity=group.official_capacity,
            occupied_count=group.occupied_count,
            occupancy_percentage=group.occupancy_percentage,
            exceeded_by=group.exceeded_by,
            status_counts=dict(group.status_counts_json),
            source_sectors=[],
            beds=[],
            name_mismatch=any(
                bool(component.get("source_name_mismatch"))
                for component in group.components_json
            ),
            official_availability=group.official_availability,
        )
        for group in groups
    }
    source_sector_sets: dict[str, set[str]] = defaultdict(set)
    auxiliary_beds: list[dict[str, object]] = []
    auxiliary_sectors: set[str] = set()
    for bed in snapshots:
        code = (bed.setor_codigo or "").strip()
        if code and code in partitioned_codes:
            if (
                bed.bed_status == BedStatus.OCCUPIED
                and bed.age_band
                in (OccupancyAgeBand.UNDER_12, OccupancyAgeBand.AGE_12_OR_OVER)
            ):
                matched_group = band_to_group.get((code, bed.age_band))
                if matched_group is not None:
                    rows[matched_group.stable_key].beds.append(
                        _bed_presentation_row(bed, patient_map or {})
                    )
                    source_sector_sets[matched_group.stable_key].add(
                        bed.setor or ""
                    )
                    continue
            auxiliary_beds.append(
                _bed_presentation_row(bed, patient_map or {})
            )
            auxiliary_sectors.add(bed.setor or "")
            continue
        if code:
            matched_group = code_to_group.get(code)
        else:
            matched_group = blank_name_to_group.get((bed.setor or "").strip())
        if matched_group is None:
            continue
        rows[matched_group.stable_key].beds.append(
            _bed_presentation_row(bed, patient_map or {})
        )
        source_sector_sets[matched_group.stable_key].add(bed.setor or "")

    result: list[_PresentationGroupRow] = []
    for group in groups:
        row = rows[group.stable_key]
        row.source_sectors = sorted(
            name for name in source_sector_sets[group.stable_key] if name
        )
        result.append(row)
    if auxiliary_beds:
        result.append(
            _PresentationGroupRow(
                stable_key=_AUXILIARY_3A_STABLE_KEY,
                display_name=_AUXILIARY_3A_DISPLAY_NAME,
                calculation_status=_AUXILIARY_3A_CALCULATION_STATUS,
                official_capacity=None,
                occupied_count=None,
                occupancy_percentage=None,
                exceeded_by=None,
                status_counts=_auxiliary_status_counts(auxiliary_beds),
                source_sectors=sorted(
                    name for name in auxiliary_sectors if name
                ),
                beds=auxiliary_beds,
                name_mismatch=False,
            )
        )
    return result


def _auxiliary_status_counts(
    beds: list[dict[str, object]],
) -> dict[str, int]:
    """Aggregate status counts for the presentation-only 3A auxiliary row."""
    counts = {status: 0 for status in _STATUS_KEYS}
    for bed in beds:
        counts[str(bed["status"])] += 1
    return counts


def _bed_presentation_row(
    bed: CensusSnapshot, patient_map: dict[str, int]
) -> dict[str, object]:
    """Present one census bed exactly like the legacy raw table does."""
    return {
        "leito": bed.leito,
        "status": bed.bed_status,
        "status_label": BedStatus(bed.bed_status).label,
        "nome": bed.nome if bed.bed_status == BedStatus.OCCUPIED else "",
        "prontuario": bed.prontuario,
        "patient_id": patient_map.get(bed.prontuario),
    }


@dataclass
class _PhysicalPositionRow:
    """One physical position (or one conflict) ready for the authenticated detail."""

    leito: str
    status: str
    status_label: str
    nome: str
    prontuario: str
    patient_id: int | None
    conflict: bool = False


@dataclass
class _PhysicalSectorRow:
    """One physical source sector of the exact census.

    Positions are grouped by the census origin (source code, or sector name
    as fallback) so the 3A source appears physically once while the official
    section keeps its Adulto/Infantil partition. ``positions`` carries only
    unambiguous positions plus one entry per conflict; duplicate extra rows
    and unidentified rows are aggregates, never positions.
    """

    source_code: str
    source_name: str
    positions_by_status: dict[str, int]
    conflict_positions: int
    duplicate_extra_rows: int
    unidentified_rows: int
    positions: list[_PhysicalPositionRow]

    @property
    def identified_positions(self) -> int:
        return sum(self.positions_by_status.values())


@dataclass
class _PhysicalPresentation:
    """Aggregate physical snapshot of the exact latest census run."""

    positions_by_status: dict[str, int]
    conflict_positions: int
    duplicate_extra_rows: int
    duplicate_occupied_rows: int
    unidentified_rows: int
    unidentified_occupied_rows: int
    sectors: list[_PhysicalSectorRow]

    @property
    def identified_total(self) -> int:
        return sum(self.positions_by_status.values())


def _observed_row_from_snapshot(bed: CensusSnapshot) -> _ObservedRow:
    """Project one census snapshot into the ephemeral normalization row."""
    return _ObservedRow(
        code=(bed.setor_codigo or "").strip(),
        name=(bed.setor or "").strip(),
        status=bed.bed_status,
        age_band=bed.age_band,
        bed=(bed.leito or "").strip(),
        record=(bed.prontuario or "").strip(),
        patient_name=(bed.nome or "").strip(),
    )


def _physical_sector_rows(
    rows: tuple[_ObservedRow, ...],
    patient_map: dict[str, int],
) -> list[_PhysicalSectorRow]:
    """Group physical normalization results by the census origin sector."""
    keyed_by_source: dict[str, list[_ObservedRow]] = defaultdict(list)
    unidentified_by_source: dict[str, list[_ObservedRow]] = defaultdict(list)
    source_code: dict[str, str] = {}
    source_name: dict[str, str] = {}
    for row in rows:
        source = (
            _normalize_identity(row.code)
            if row.code
            else _normalize_identity(row.name)
        )
        source_code.setdefault(source, row.code or "")
        source_name.setdefault(source, row.name or "")
        if _normalize_identity(row.bed):
            keyed_by_source[source].append(row)
        else:
            unidentified_by_source[source].append(row)

    sector_rows: list[_PhysicalSectorRow] = []
    for source in sorted(set(keyed_by_source) | set(unidentified_by_source)):
        positions_by_status = {status: 0 for status in _STATUS_KEYS}
        conflict_positions = 0
        duplicate_extra_rows = 0
        position_rows: list[_PhysicalPositionRow] = []
        by_key: dict[tuple[str, str], list[_ObservedRow]] = defaultdict(list)
        for row in keyed_by_source[source]:
            by_key[(_normalize_identity(row.bed), source)].append(row)
        for key_rows in by_key.values():
            outcome = _classify_key_rows(key_rows)
            if outcome.position is not None:
                positions_by_status[outcome.position.status] += 1
                position_rows.append(
                    _physical_position_row(outcome.primary, patient_map)
                )
            else:
                conflict_positions += 1
                position_rows.append(
                    _physical_position_row(
                        outcome.primary, patient_map, conflict=True
                    )
                )
            duplicate_extra_rows += outcome.duplicate_extra_rows
        sector_rows.append(
            _PhysicalSectorRow(
                source_code=source_code[source],
                source_name=source_name[source],
                positions_by_status=positions_by_status,
                conflict_positions=conflict_positions,
                duplicate_extra_rows=duplicate_extra_rows,
                unidentified_rows=len(unidentified_by_source[source]),
                positions=position_rows,
            )
        )
    return sector_rows


def _physical_position_row(
    row: _ObservedRow,
    patient_map: dict[str, int],
    *,
    conflict: bool = False,
) -> _PhysicalPositionRow:
    """Present one physical position or one conflict without a chosen patient."""
    if conflict:
        return _PhysicalPositionRow(
            leito=row.bed,
            status="conflict",
            status_label="Conflito no legado",
            nome="",
            prontuario="",
            patient_id=None,
            conflict=True,
        )
    return _PhysicalPositionRow(
        leito=row.bed,
        status=row.status,
        status_label=BedStatus(row.status).label,
        nome=row.patient_name if row.status == BedStatus.OCCUPIED else "",
        prontuario=row.record if row.status == BedStatus.OCCUPIED else "",
        patient_id=(
            patient_map.get(row.record)
            if row.status == BedStatus.OCCUPIED
            else None
        ),
    )


# ---------------------------------------------------------------------------
# MOQA-S3: /beds unified presentation units.
#
# The page keeps two aggregate summaries and renders exactly one detailed
# list ``Setores e posições``. Each expandable unit is one connected
# component of the bipartite graph whose group nodes are the persisted
# official groups of the exact measurement and whose source nodes are the
# source codes bound by the memberships persisted in the exact catalog.
# Unmapped census sources form their own warning units. Every physical
# position is normalized once per source with the same v4 (or v3) key
# classification used by materialization; the raw ``beds`` of the official
# group rows are never rendered here because that would repeat duplicates
# and conflicts. Quality details are presentation-memory only: they are
# never persisted, logged or aggregated.
# ---------------------------------------------------------------------------

_AGE_BAND_LABELS: dict[str, str] = {
    OccupancyAgeBand.UNDER_12: "Menor de 12 anos",
    OccupancyAgeBand.AGE_12_OR_OVER: "12 anos ou mais",
    OccupancyAgeBand.UNKNOWN: "Desconhecida",
    OccupancyAgeBand.NOT_APPLICABLE: "Não se aplica",
}

_CONFLICT_REASONS = {
    "occupant": (
        "Ocupante divergente — posição computada uma vez, "
        "sem ocupante autoritativo"
    ),
    "status": (
        "Status divergente — posição e linhas não computadas "
        "por status ambíguo"
    ),
    "age": (
        "Faixa etária divergente — posição não atribuída a grupo etário"
    ),
    "legacy": "Conflito no sistema de origem — posição sem estado definido",
}


@dataclass
class _UnitOfficialRow:
    """Persisted official values of one group inside a presentation unit."""

    stable_key: str
    display_name: str
    calculation_status: str
    official_capacity: int | None
    occupied_count: int | None
    occupancy_percentage: Decimal | None
    exceeded_by: int | None
    official_availability: int | None
    status_counts: dict[str, int]
    name_mismatch: bool

    @property
    def over_capacity(self) -> bool:
        return (
            self.occupancy_percentage is not None
            and self.occupancy_percentage > Decimal("100.00")
        )


@dataclass
class _UnitAlternative:
    """One unique raw signature of a conflict, never authoritative."""

    status: str
    status_label: str
    nome: str
    prontuario: str
    patient_id: int | None
    age_label: str
    occurrence_count: int


@dataclass
class _UnitConflictCase:
    """One physical conflict case with its unique alternatives."""

    leito: str
    conflict_type: str
    reason: str
    counted: bool
    alternatives: list[_UnitAlternative]


@dataclass
class _UnitUnidentifiedCase:
    """One occupied raw row without usable bed identity."""

    status: str
    status_label: str
    nome: str
    prontuario: str
    patient_id: int | None


@dataclass
class _UnitPositionRow:
    """One unambiguous physical position rendered exactly once."""

    leito: str
    status: str
    status_label: str
    nome: str
    prontuario: str
    patient_id: int | None
    note: str | None = None


@dataclass
class _UnitSourceSummary:
    """One source-code block inside a presentation unit."""

    source_code: str
    alias: str
    raw_name: str | None
    observed_name: str | None
    observed_mismatch: bool
    positions_by_status: dict[str, int]
    positions: list[_UnitPositionRow]
    conflicts: list[_UnitConflictCase]
    duplicate_extra_rows: int
    unidentified_rows: int
    unidentified_occupied_rows: int
    unidentified_cases: list[_UnitUnidentifiedCase]

    @property
    def identified_positions(self) -> int:
        return sum(self.positions_by_status.values())

    @property
    def has_quality_cases(self) -> bool:
        return bool(self.conflicts or self.unidentified_occupied_rows)


@dataclass
class _UnitRow:
    """One connected-component unit of the unified sector list."""

    title: str
    official_rows: list[_UnitOfficialRow]
    sources: list[_UnitSourceSummary]
    is_unmapped: bool = False

    @property
    def over_capacity(self) -> bool:
        return any(row.over_capacity for row in self.official_rows)


@dataclass
class _UnitsPresentation:
    """Template-ready unit list plus the physical aggregate snapshot."""

    units: list[_UnitRow]
    physical: _PhysicalPresentation


def _unit_official_row(
    group: OccupancyGroupMeasurement,
) -> _UnitOfficialRow:
    """Project one persisted group measurement into a unit official row."""
    return _UnitOfficialRow(
        stable_key=group.stable_key,
        display_name=group.display_name,
        calculation_status=group.calculation_status,
        official_capacity=group.official_capacity,
        occupied_count=group.occupied_count,
        occupancy_percentage=group.occupancy_percentage,
        exceeded_by=group.exceeded_by,
        official_availability=group.official_availability,
        status_counts=dict(group.status_counts_json),
        name_mismatch=any(
            bool(component.get("source_name_mismatch"))
            for component in group.components_json
        ),
    )


def _source_alias(
    membership: CapacitySectorMembership,
) -> tuple[str, str | None]:
    """Return ``(primary label, raw provenance)`` for one exact membership.

    The curated v4 alias is the primary label; the configured raw source name
    is preserved only as subordinate provenance (``Nome no sistema de
    origem``). Historical catalogs without an alias use the configured name
    as the documented fallback, without consulting the current catalog and
    without regex normalization.
    """
    if membership.source_display_name:
        return membership.source_display_name, membership.configured_source_name
    return membership.configured_source_name, None


def _catalog_components(
    catalog: CapacityCatalogVersion,
) -> list[tuple[list[str], list[str]]]:
    """Connected components of the bipartite group<->code graph.

    Returns ``(group_keys, codes)`` tuples, each sorted deterministically.
    Codes connect to their group through the memberships persisted in the
    exact catalog; no stable key or source code is special-cased.
    """
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        root = key
        while parent[root] != root:
            root = parent[root]
        while parent[key] != root:
            parent[key], key = root, parent[key]
        return root

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for definition in catalog.groups.all():
        group_key = f"group:{definition.stable_key}"
        for membership in definition.memberships.all():
            union(group_key, f"code:{membership.source_code}")

    by_root: dict[str, set[str]] = defaultdict(set)
    for key in parent:
        by_root[find(key)].add(key)
    components: list[tuple[list[str], list[str]]] = []
    for members in by_root.values():
        group_keys = sorted(
            key.removeprefix("group:")
            for key in members
            if key.startswith("group:")
        )
        codes = sorted(
            key.removeprefix("code:")
            for key in members
            if key.startswith("code:")
        )
        components.append((group_keys, codes))
    return sorted(components, key=lambda item: (item[0][0] if item[0] else "", item[1]))


def _component_title(
    group_keys: list[str],
    codes: list[str],
    group_rows: dict[str, OccupancyGroupMeasurement],
    alias_by_code: dict[str, str],
) -> str:
    """Deterministic unit title.

    One group uses its official ``display_name``; several groups sharing one
    source use the clean source alias; every other component uses the sorted
    official names joined deterministically.
    """
    if len(group_keys) == 1:
        return group_rows[group_keys[0]].display_name
    if len(codes) == 1:
        return alias_by_code[codes[0]]
    return " + ".join(
        sorted(group_rows[key].display_name for key in group_keys)
    )


def _legacy_sector_summary(
    *,
    code: str,
    alias: str,
    raw_name: str | None,
    sector: _PhysicalSectorRow | None,
) -> _UnitSourceSummary:
    """Wrap one v3-normalized physical sector as a unit source summary."""
    observed_name = sector.source_name if sector is not None else None
    positions_by_status = (
        dict(sector.positions_by_status)
        if sector is not None
        else {status: 0 for status in _STATUS_KEYS}
    )
    positions: list[_UnitPositionRow] = []
    conflicts: list[_UnitConflictCase] = []
    if sector is not None:
        for row in sector.positions:
            if row.conflict:
                conflicts.append(
                    _UnitConflictCase(
                        leito=row.leito,
                        conflict_type="legacy",
                        reason=_CONFLICT_REASONS["legacy"],
                        counted=False,
                        alternatives=[],
                    )
                )
            else:
                positions.append(
                    _UnitPositionRow(
                        leito=row.leito,
                        status=row.status,
                        status_label=row.status_label,
                        nome=row.nome,
                        prontuario=row.prontuario,
                        patient_id=row.patient_id,
                    )
                )
    return _UnitSourceSummary(
        source_code=code,
        alias=alias,
        raw_name=raw_name,
        observed_name=observed_name,
        observed_mismatch=bool(
            observed_name
            and observed_name != alias
            and (raw_name is None or observed_name != raw_name)
        ),
        positions_by_status=positions_by_status,
        positions=positions,
        conflicts=conflicts,
        duplicate_extra_rows=sector.duplicate_extra_rows if sector is not None else 0,
        unidentified_rows=sector.unidentified_rows if sector is not None else 0,
        unidentified_occupied_rows=0,
        unidentified_cases=[],
    )


def _legacy_units(
    measurement: OccupancyMeasurement | None,
    rows: tuple[_ObservedRow, ...],
    patient_map: dict[str, int],
) -> list[_UnitRow]:
    """Build the unified units for v1/v2/v3 or for a runless census."""
    sectors = _physical_sector_rows(rows, patient_map)
    sector_by_source = {
        _normalize_identity(sector.source_code): sector for sector in sectors
    }

    if measurement is None:
        return [
            _UnitRow(
                title=sector.source_name,
                official_rows=[],
                sources=[
                    _legacy_sector_summary(
                        code=sector.source_code,
                        alias=sector.source_name,
                        raw_name=None,
                        sector=sector,
                    )
                ],
            )
            for sector in sectors
        ]

    group_rows = {
        group.stable_key: group for group in measurement.groups.all()
    }
    definitions = {
        group.stable_key: group
        for group in measurement.catalog.groups.all()
    }
    membership_by_code: dict[str, CapacitySectorMembership] = {}
    for definition in definitions.values():
        for membership in definition.memberships.all():
            membership_by_code[membership.source_code] = membership

    units: list[_UnitRow] = []
    alias_by_code = {
        code: _source_alias(membership)[0]
        for code, membership in membership_by_code.items()
    }
    for group_keys, codes in _catalog_components(measurement.catalog):
        units.append(
            _UnitRow(
                title=_component_title(
                    group_keys, codes, group_rows, alias_by_code
                ),
                official_rows=[
                    _unit_official_row(group_rows[key])
                    for key in group_keys
                    if key in group_rows
                ],
                sources=[
                    _legacy_sector_summary(
                        code=code,
                        alias=alias_by_code[code],
                        raw_name=(
                            membership_by_code[code].configured_source_name
                            if membership_by_code[code].source_display_name
                            else None
                        ),
                        sector=sector_by_source.get(
                            _normalize_identity(code)
                        ),
                    )
                    for code in codes
                ],
            )
        )

    membership_codes = {_normalize_identity(code) for code in membership_by_code}
    unmapped_units: list[_UnitRow] = []
    for sector in sorted(
        sectors, key=lambda sector: sector.source_name
    ):
        if (
            sector.source_code
            and _normalize_identity(sector.source_code) in membership_codes
        ):
            continue
        unmapped_units.append(
            _UnitRow(
                title=sector.source_name,
                official_rows=[],
                sources=[
                    _legacy_sector_summary(
                        code=sector.source_code,
                        alias=sector.source_name,
                        raw_name=None,
                        sector=sector,
                    )
                ],
                is_unmapped=True,
            )
        )
    units.extend(unmapped_units)
    return sorted(units, key=lambda unit: unit.title)


def _v4_partitioned_codes(catalog: CapacityCatalogVersion) -> set[str]:
    """Source codes partitioned by age band in the exact catalog."""
    return {
        membership.source_code
        for group in catalog.groups.all()
        for membership in group.memberships.all()
        if membership.age_selector != CapacityMembershipSelector.ALL
    }


def _conflict_alternatives(
    key_rows: list[_ObservedRow],
    patient_map: dict[str, int],
) -> list[_UnitAlternative]:
    """Unique signatures of one conflict, without any winning candidate."""
    signature_rows: dict[tuple[object, ...], list[_ObservedRow]] = (
        defaultdict(list)
    )
    for row in key_rows:
        signature_rows[_row_signature(row)].append(row)
    alternatives: list[_UnitAlternative] = []
    for same_rows in signature_rows.values():
        representative = same_rows[0]
        occupied = representative.status == BedStatus.OCCUPIED
        alternatives.append(
            _UnitAlternative(
                status=representative.status,
                status_label=BedStatus(representative.status).label,
                nome=representative.patient_name if occupied else "",
                prontuario=representative.record if occupied else "",
                patient_id=(
                    patient_map.get(representative.record)
                    if occupied
                    else None
                ),
                age_label=_AGE_BAND_LABELS.get(
                    representative.age_band, representative.age_band
                ),
                occurrence_count=len(same_rows),
            )
        )
    return sorted(
        alternatives, key=lambda alt: (alt.status, alt.prontuario, alt.nome)
    )


def _unit_position_row_v4(
    outcome: _V4KeyOutcome,
    key_rows: list[_ObservedRow],
    patient_map: dict[str, int],
) -> _UnitPositionRow:
    """One counted v4 physical position without an authoritative patient."""
    position = outcome.position
    assert position is not None
    if outcome.conflict == "occupant":
        return _UnitPositionRow(
            leito=key_rows[0].bed,
            status=position.status,
            status_label=BedStatus(position.status).label,
            nome="",
            prontuario="",
            patient_id=None,
            note="Ocupante não autoritativo — posição computada uma vez",
        )
    note: str | None = None
    if outcome.unknown_partition:
        note = "Faixa etária desconhecida — não atribuída a grupo etário oficial"
    elif outcome.age_metadata_drift:
        note = (
            "Divergência de faixa etária em código não particionado — "
            "ocupação mantida"
        )
    primary = key_rows[0]
    occupied = primary.status == BedStatus.OCCUPIED
    return _UnitPositionRow(
        leito=primary.bed,
        status=primary.status,
        status_label=BedStatus(primary.status).label,
        nome=primary.patient_name if occupied else "",
        prontuario=primary.record if occupied else "",
        patient_id=patient_map.get(primary.record) if occupied else None,
        note=note,
    )


def _unit_unidentified_case(
    row: _ObservedRow,
    patient_map: dict[str, int],
) -> _UnitUnidentifiedCase:
    """One occupied row without bed identity, kept in presentation memory."""
    return _UnitUnidentifiedCase(
        status=row.status,
        status_label=BedStatus(row.status).label,
        nome=row.patient_name if row.status == BedStatus.OCCUPIED else "",
        prontuario=row.record if row.status == BedStatus.OCCUPIED else "",
        patient_id=(
            patient_map.get(row.record)
            if row.status == BedStatus.OCCUPIED
            else None
        ),
    )


def _v4_source_summary(
    *,
    code: str,
    code_rows: list[_ObservedRow],
    partitioned: bool,
    membership: CapacitySectorMembership | None,
    patient_map: dict[str, int],
) -> _UnitSourceSummary:
    """Build one v4 source block with positions, conflicts and no-bed rows."""
    observed_names = sorted({row.name for row in code_rows if row.name})
    observed_name = observed_names[0] if observed_names else None
    if membership is not None:
        alias, raw_name = _source_alias(membership)
    else:
        alias = observed_name or code or "Setor sem código"
        raw_name = None

    positions_by_status = {status: 0 for status in _STATUS_KEYS}
    positions: list[_UnitPositionRow] = []
    conflicts: list[_UnitConflictCase] = []
    duplicate_extra_rows = 0
    unidentified_rows = 0
    unidentified_occupied_rows = 0
    unidentified_cases: list[_UnitUnidentifiedCase] = []

    by_bed: dict[str, list[_ObservedRow]] = defaultdict(list)
    for row in code_rows:
        bed = _normalize_identity(row.bed)
        if not bed:
            unidentified_rows += 1
            if row.status == BedStatus.OCCUPIED:
                unidentified_occupied_rows += 1
                unidentified_cases.append(_unit_unidentified_case(row, patient_map))
            continue
        by_bed[bed].append(row)

    for bed in sorted(by_bed):
        key_rows = by_bed[bed]
        outcome = _classify_key_rows_v4(key_rows, partitioned=partitioned)
        duplicate_extra_rows += outcome.duplicate_extra_rows
        if outcome.position is not None:
            positions_by_status[outcome.position.status] += 1
            positions.append(
                _unit_position_row_v4(outcome, key_rows, patient_map)
            )
        if outcome.conflict:
            conflicts.append(
                _UnitConflictCase(
                    leito=key_rows[0].bed,
                    conflict_type=outcome.conflict,
                    reason=_CONFLICT_REASONS[outcome.conflict],
                    counted=outcome.conflict == "occupant",
                    alternatives=_conflict_alternatives(key_rows, patient_map),
                )
            )

    return _UnitSourceSummary(
        source_code=code,
        alias=alias,
        raw_name=raw_name,
        observed_name=observed_name,
        observed_mismatch=bool(
            observed_name
            and observed_name != alias
            and (raw_name is None or observed_name != raw_name)
        ),
        positions_by_status=positions_by_status,
        positions=positions,
        conflicts=conflicts,
        duplicate_extra_rows=duplicate_extra_rows,
        unidentified_rows=unidentified_rows,
        unidentified_occupied_rows=unidentified_occupied_rows,
        unidentified_cases=unidentified_cases,
    )


def _v4_units(
    measurement: OccupancyMeasurement,
    rows: tuple[_ObservedRow, ...],
    patient_map: dict[str, int],
    partitioned_codes: set[str],
) -> list[_UnitRow]:
    """Build the unified units for an occupancy-v4 exact measurement."""
    group_rows = {
        group.stable_key: group for group in measurement.groups.all()
    }
    definitions = {
        group.stable_key: group
        for group in measurement.catalog.groups.all()
    }
    membership_by_code: dict[str, CapacitySectorMembership] = {}
    for definition in definitions.values():
        for membership in definition.memberships.all():
            membership_by_code[membership.source_code] = membership

    rows_by_code: dict[str, list[_ObservedRow]] = defaultdict(list)
    rows_by_name: dict[str, list[_ObservedRow]] = defaultdict(list)
    for row in rows:
        if row.code:
            rows_by_code[row.code].append(row)
        else:
            rows_by_name[_normalize_identity(row.name)].append(row)

    units: list[_UnitRow] = []
    alias_by_code = {
        code: _source_alias(membership)[0]
        for code, membership in membership_by_code.items()
    }
    for group_keys, codes in _catalog_components(measurement.catalog):
        units.append(
            _UnitRow(
                title=_component_title(
                    group_keys, codes, group_rows, alias_by_code
                ),
                official_rows=[
                    _unit_official_row(group_rows[key])
                    for key in group_keys
                    if key in group_rows
                ],
                sources=[
                    _v4_source_summary(
                        code=code,
                        code_rows=rows_by_code.get(code, []),
                        partitioned=code in partitioned_codes,
                        membership=membership_by_code[code],
                        patient_map=patient_map,
                    )
                    for code in codes
                ],
            )
        )

    membership_codes = set(membership_by_code)
    for code in sorted(set(rows_by_code) - membership_codes):
        units.append(
            _UnitRow(
                title=_v4_unmapped_title(rows_by_code[code], code),
                official_rows=[],
                sources=[
                    _v4_source_summary(
                        code=code,
                        code_rows=rows_by_code[code],
                        partitioned=False,
                        membership=None,
                        patient_map=patient_map,
                    )
                ],
                is_unmapped=True,
            )
        )
    for name in sorted(set(rows_by_name)):
        units.append(
            _UnitRow(
                title=name,
                official_rows=[],
                sources=[
                    _v4_source_summary(
                        code="",
                        code_rows=rows_by_name[name],
                        partitioned=False,
                        membership=None,
                        patient_map=patient_map,
                    )
                ],
                is_unmapped=True,
            )
        )
    return sorted(units, key=lambda unit: unit.title)


def _v4_unmapped_title(
    code_rows: list[_ObservedRow], fallback: str
) -> str:
    """Deterministic title for an unmapped source: first observed name."""
    observed_names = sorted({row.name for row in code_rows if row.name})
    return observed_names[0] if observed_names else fallback


def build_units_presentation(
    *,
    measurement: OccupancyMeasurement | None,
    snapshots: Iterable[CensusSnapshot],
    patient_map: dict[str, int] | None = None,
) -> _UnitsPresentation:
    """Build the unified ``Setores e posições`` list and physical snapshot.

    For ``occupancy-v4`` the per-source positions reuse the v4 key
    classification of S1 (``_classify_key_rows_v4``) so every physical
    position appears once and occupant conflicts count one occupied position
    without a winner; status/age conflicts stay cases without a counted
    position. For v1/v2/v3 and for a runless census the v3 normalization
    contract is preserved. The physical aggregate mirrors the same pass so
    the cards and the unit list never disagree.
    """
    rows = tuple(_observed_row_from_snapshot(bed) for bed in snapshots)
    patient_map = patient_map or {}
    if measurement is None or measurement.algorithm_version != ALGORITHM_VERSION_V4:
        _positions, diagnostics = _normalize_positions(rows)
        physical = _PhysicalPresentation(
            positions_by_status=dict(diagnostics.positions_by_status),
            conflict_positions=diagnostics.conflict_positions,
            duplicate_extra_rows=diagnostics.duplicate_extra_rows,
            duplicate_occupied_rows=diagnostics.duplicate_occupied_rows,
            unidentified_rows=diagnostics.unidentified_rows,
            unidentified_occupied_rows=diagnostics.unidentified_occupied_rows,
            sectors=_physical_sector_rows(rows, patient_map),
        )
        return _UnitsPresentation(
            units=_legacy_units(measurement, rows, patient_map),
            physical=physical,
        )

    partitioned_codes = _v4_partitioned_codes(measurement.catalog)
    v4_positions, v4_diagnostics = _normalize_positions_v4(rows, partitioned_codes)
    physical = _PhysicalPresentation(
        positions_by_status=dict(v4_diagnostics.positions_by_status),
        conflict_positions=(
            v4_diagnostics.occupant_conflict_positions
            + v4_diagnostics.status_conflict_positions
            + v4_diagnostics.age_conflict_positions
        ),
        duplicate_extra_rows=v4_diagnostics.duplicate_extra_rows,
        duplicate_occupied_rows=v4_diagnostics.duplicate_occupied_extra_rows,
        unidentified_rows=v4_diagnostics.unidentified_rows,
        unidentified_occupied_rows=v4_diagnostics.unidentified_occupied_rows,
        sectors=[],
    )
    return _UnitsPresentation(
        units=_v4_units(measurement, rows, patient_map, partitioned_codes),
        physical=physical,
    )
