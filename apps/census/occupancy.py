"""Immutable occupancy-v1 materialization for one explicit census run."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
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
    CapacitySectorMembership,
    CensusSnapshot,
    DailyGroupOccupancySummary,
    DailyOccupancySummary,
    OccupancyCalculationStatus,
    OccupancyGroupMeasurement,
    OccupancyMeasurement,
)
from apps.ingestion.models import IngestionRun

ALGORITHM_VERSION = "occupancy-v1"
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
    code: str
    name: str
    status: str


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

        group_values, totals = _calculate(catalog, observed_rows)
        measurement = OccupancyMeasurement.objects.create(
            census_run=run,
            catalog=catalog,
            captured_at=captured_at,
            local_date=local_date,
            algorithm_version=ALGORITHM_VERSION,
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
    """Aggregate hospital-level daily statistics from day measurements."""
    reference = measurements[0]
    occupied = [measurement.occupied_for_rate for measurement in measurements]
    exact_percentages = [
        _exact_percentage(
            measurement.occupied_for_rate, measurement.calculable_capacity
        )
        for measurement in measurements
        if measurement.calculable_capacity > 0
    ]
    return {
        "catalog": reference.catalog,
        "algorithm_version": reference.algorithm_version,
        "measurement_count": len(measurements),
        "first_captured_at": measurements[0].captured_at,
        "last_captured_at": measurements[-1].captured_at,
        "known_capacity": reference.known_capacity,
        "calculable_capacity": reference.calculable_capacity,
        "mean_occupied": _rounded_mean(occupied),
        "min_occupied": min(occupied),
        "max_occupied": max(occupied),
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
        "max_exceeded_by": max(
            measurement.exceeded_by for measurement in measurements
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


def _daily_group_values(
    measurements: list[OccupancyMeasurement],
) -> list[dict[str, object]]:
    """Aggregate per-group daily statistics from day measurements."""
    by_key: dict[str, list[tuple[datetime, OccupancyGroupMeasurement]]] = (
        defaultdict(list)
    )
    for measurement in measurements:
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
        .values_list("captured_at", "setor_codigo", "setor", "bed_status")
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
            ),
        )
        for captured_at, code, name, status in snapshots
    ]


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
) -> tuple[list[_GroupValues], dict[str, int | Decimal | None]]:
    by_code, blank_by_name = _aggregate_observations(rows)
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
        group_values = _calculate_catalog_group(group, by_code)
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
    totals: dict[str, int | Decimal | None] = {
        "observed_sector_count": len(observed_identities),
        "capacity_covered_sector_count": capacity_covered,
        "calculable_sector_count": calculable,
        "known_capacity": known_capacity,
        "calculable_capacity": calculable_capacity,
        "occupied_for_rate": occupied_for_rate,
        "occupancy_percentage": percentage,
        "exceeded_by": max(occupied_for_rate - calculable_capacity, 0),
    }
    return sorted(values, key=lambda value: value.stable_key), totals


def _aggregate_observations(
    rows: Iterable[_ObservedRow],
) -> tuple[
    dict[str, dict[str, Counter[str]]],
    dict[str, Counter[str]],
]:
    by_code: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    blank_by_name: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.code:
            by_code[row.code][row.name][row.status] += 1
        else:
            blank_by_name[row.name][row.status] += 1
    return by_code, blank_by_name


def _calculate_catalog_group(
    group: CapacityGroupDefinition,
    by_code: dict[str, dict[str, Counter[str]]],
) -> _GroupValues:
    total_counts = Counter[str]()
    components: list[dict[str, object]] = []
    for membership in group.memberships.all():
        observations = by_code.get(membership.source_code, {})
        if not observations:
            components.append(
                _component(
                    configured_code=membership.source_code,
                    configured_name=membership.configured_source_name,
                    observed_code=membership.source_code,
                    observed_name=None,
                    counts=Counter(),
                    mismatch=False,
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
) -> dict[str, object]:
    return {
        "configured_code": configured_code,
        "configured_name": configured_name,
        "observed_code": observed_code,
        "observed_name": observed_name,
        "status_counts": _status_counts(counts),
        "source_name_mismatch": mismatch,
    }


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
    raw beds of the same census. Beds are matched to the official group whose
    component carries their observed code (or observed name when the code is
    blank); a shared group therefore appears once with combined counts while
    every contributing source sector and bed stays inside its expansion. No
    rate, coverage or adjusted occupancy value is computed here.
    """
    groups = list(measurement.groups.all())
    code_to_group: dict[str, OccupancyGroupMeasurement] = {}
    blank_name_to_group: dict[str, OccupancyGroupMeasurement] = {}
    for group in groups:
        for component in group.components_json:
            observed_code = str(component.get("observed_code") or "").strip()
            if observed_code:
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
        )
        for group in groups
    }
    source_sector_sets: dict[str, set[str]] = defaultdict(set)
    for bed in snapshots:
        code = (bed.setor_codigo or "").strip()
        if code:
            matched_group = code_to_group.get(code)
        else:
            matched_group = blank_name_to_group.get(
                (bed.setor or "").strip()
            )
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
    return result


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
