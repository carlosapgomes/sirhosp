"""Atomic materialization of the daily statistics revision (DSRS-S2..S4).

One call materializes, for one ``America/Bahia`` local date, the reproducible
revision consumed by the page and the workbook of later slices:

- the accepted anchor/opening/closing census runs and the exact closing
  measurement come from the read-only window selection of DSRS-S1;
- sectors are the historical official groups of that exact measurement and
  only copy its persisted metrics;
- patients are the nominal rows of the closing census photograph, attributed
  to the official grouping by the shared occupancy assignment primitive;
- detected entries and internal transfers are derived from the consecutive
  accepted census photographs (DSRS-S3), and classified exits are derived from
  the same sequence together with the persisted death and effective discharge
  evidence (DSRS-S4); each logical fact is persisted once, with the versioned
  origin classification, the clinical instant or date a source provided, the
  attribution quality of its sector, the detection interval and the explicit
  quality of ambiguous identity or grouping;
- a deterministic SHA-256 source fingerprint makes a repeated build a no-op
  and publishes a superseding revision only when the sources changed.

Publication is atomic: the candidate revision is completed inside one
transaction and only then becomes the single ready revision of its date. A
failed build leaves the previous ready revision untouched and persists nothing.
Dates before the declared activation boundary are refused, so no historical
backfill can be triggered from here. Automatic revisions reuse the same
selected closing photograph: late clinical evidence changes the derived events,
never the census close it was read from, and no clinical source record is
ever written here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from django.db import models, transaction

from apps.census.models import CensusSnapshot, OccupancyMeasurement
from apps.census.occupancy import assign_official_group_keys
from apps.ingestion.models import IngestionRun
from apps.statistics_reports.events import (
    EventDerivation,
    derive_report_events,
)
from apps.statistics_reports.models import (
    DailyStatisticsEvent,
    DailyStatisticsPatient,
    DailyStatisticsReport,
    DailyStatisticsReportStatus,
    DailyStatisticsSector,
)
from apps.statistics_reports.origin_policy import (
    DEFAULT_ORIGIN_POLICY,
    OriginPolicy,
)
from apps.statistics_reports.selection import (
    AcceptedCensus,
    DailyStatisticsWindow,
    select_daily_statistics_window,
)


class DailyStatisticsMaterializationError(Exception):
    """The requested local date cannot produce a daily statistics revision."""


class DateBeforeActivationError(DailyStatisticsMaterializationError):
    """The requested date precedes the declared activation boundary."""


class IncompleteStatisticalDayError(DailyStatisticsMaterializationError):
    """The day has no accepted opening or closing census photograph."""


@dataclass(frozen=True)
class MaterializationOutcome:
    """Result of one materialization call.

    ``created`` is ``False`` when the current revision already carries the same
    source fingerprint and nothing was written.
    """

    report: DailyStatisticsReport
    created: bool


def materialize_daily_statistics(
    *,
    local_date: date,
    activation_date: date,
    origin_policy: OriginPolicy = DEFAULT_ORIGIN_POLICY,
) -> MaterializationOutcome:
    """Materialize or reuse the ready revision of one Bahia local date.

    Args:
        local_date: Local ``America/Bahia`` calendar date to materialize.
        activation_date: First eligible local date declared for the feature;
            an earlier ``local_date`` is refused instead of backfilled.
        origin_policy: Versioned origin classification in force for the
            detected entries of this revision; its version is part of the
            source fingerprint, so changing the mapping publishes a new
            revision.

    Returns:
        The ready revision of ``local_date`` and whether it was created now.

    Raises:
        DateBeforeActivationError: When ``local_date`` precedes
            ``activation_date``.
        IncompleteStatisticalDayError: When the day lacks accepted opening or
            closing census photographs.
    """
    if local_date < activation_date:
        raise DateBeforeActivationError(
            f"Local date {local_date.isoformat()} precedes the declared "
            f"activation date {activation_date.isoformat()}."
        )

    window = select_daily_statistics_window(local_date)
    if not window.complete or window.opening is None or window.closing is None:
        raise IncompleteStatisticalDayError(
            f"Local date {local_date.isoformat()} has no complete accepted "
            "census window: "
            f"{', '.join(window.incomplete_reasons) or 'unknown reason'}."
        )

    closing = window.closing
    with transaction.atomic():
        # Concurrent builds of the same date must not interleave: the accepted
        # closing photograph is the one shared row every builder locks first.
        _lock_run(closing.run)
        current = (
            DailyStatisticsReport.objects.select_for_update()
            .filter(
                local_date=local_date,
                status=DailyStatisticsReportStatus.READY,
            )
            .first()
        )
        photograph = _closing_photograph(closing)
        assignment = assign_official_group_keys(
            measurement=closing.measurement,
            snapshots=photograph,
        )
        derivation = derive_report_events(
            window=window,
            origin_policy=origin_policy,
        )
        quality_codes = _quality_codes(
            window=window,
            derivation=derivation,
        )
        fingerprint = _source_fingerprint(
            window=window,
            photograph=photograph,
            assignment=assignment,
            derivation=derivation,
            quality_codes=quality_codes,
        )
        if current is not None and current.source_fingerprint == fingerprint:
            # Same sources: the current ready revision is already the answer.
            return MaterializationOutcome(report=current, created=False)

        if current is not None:
            # The former revision is never mutated in content, only retired.
            current.status = DailyStatisticsReportStatus.SUPERSEDED
            current.save(update_fields=["status"])

        report = _create_report(
            window=window,
            activation_date=activation_date,
            fingerprint=fingerprint,
            revision=_next_revision(local_date),
            quality_codes=quality_codes,
        )
        sectors = _create_sectors(report=report, measurement=closing.measurement)
        _create_patients(
            report=report,
            photograph=photograph,
            assignment=assignment,
            sectors=sectors,
        )
        _create_events(report=report, derivation=derivation, sectors=sectors)
        return MaterializationOutcome(report=report, created=True)


def _lock_run(run: IngestionRun) -> None:
    """Lock the closing provenance row so same-date builds serialize."""
    IngestionRun.objects.select_for_update().get(pk=run.pk)


def _closing_photograph(closing: AcceptedCensus) -> list[CensusSnapshot]:
    """Rows of the exact closing photograph accepted by the selector.

    Selection accepts a census extraction run only when its rows share one
    single capture instant, so the run-scoped snapshot set *is* the accepted
    photograph. The measurement instant is deliberately not used as the
    filter: it is separate evidence of the same run and may carry another
    instant, which would silently empty the closing roster.
    """
    return list(
        CensusSnapshot.objects.filter(
            ingestion_run_id=closing.run.pk,
        ).order_by("pk")
    )


def _next_revision(local_date: date) -> int:
    """Next free 1-based revision of ``local_date``."""
    highest = DailyStatisticsReport.objects.filter(
        local_date=local_date
    ).aggregate(models.Max("revision"))["revision__max"]
    return int(highest or 0) + 1


def _quality_codes(
    *,
    window: DailyStatisticsWindow,
    derivation: EventDerivation,
) -> tuple[str, ...]:
    """Structured quality codes of the revision, without duplicates."""
    return tuple(
        dict.fromkeys((*window.quality_warnings, *derivation.quality_codes))
    )


def _source_fingerprint(
    *,
    window: DailyStatisticsWindow,
    photograph: Sequence[CensusSnapshot],
    assignment: Mapping[int, str | None],
    derivation: EventDerivation,
    quality_codes: Sequence[str],
) -> str:
    """Deterministic SHA-256 of every source value this revision copies.

    The payload covers the selected runs, the exact measurement and catalog
    context, the copied official sector metrics, the nominal closing rows with
their resolved grouping and the whole compared census chain with its derived
events, their clinical values and the chosen evidence rows, so an unchanged
source set is recognized as the same revision.
    """
    assert window.closing is not None
    measurement = window.closing.measurement
    payload: dict[str, object] = {
        "local_date": window.local_date.isoformat(),
        "anchor_run": _run_pk(window.anchor),
        "opening_run": _run_pk(window.opening),
        "closing_run": _run_pk(window.closing),
        "measurement": measurement.pk,
        "catalog": measurement.catalog_id,
        "algorithm_version": measurement.algorithm_version,
        "captured_at": measurement.captured_at.isoformat(),
        "origin_policy_version": derivation.origin_policy_version,
        "quality_warnings": list(quality_codes),
        "census_chain": [
            [photograph_entry.run.pk, photograph_entry.captured_at.isoformat()]
            for photograph_entry in derivation.chain
        ],
        "events": [event.fingerprint for event in derivation.events],
        "sectors": _sector_payload(measurement),
        "patients": [
            [
                bed.pk,
                assignment.get(bed.pk),
                bed.leito,
                bed.nome,
                bed.prontuario,
                bed.especialidade,
            ]
            for bed in photograph
            if bed.pk in assignment
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _run_pk(census: AcceptedCensus | None) -> int | None:
    """Primary key of the selected census run, or ``None``."""
    return None if census is None else census.run.pk


def _sector_payload(
    measurement: OccupancyMeasurement,
) -> list[dict[str, object]]:
    """Fingerprint fragment of the copied official sector metrics."""
    return [
        {
            "stable_key": group.stable_key,
            "display_name": group.display_name,
            "calculation_policy": group.calculation_policy,
            "calculation_status": group.calculation_status,
            "official_capacity": group.official_capacity,
            "occupied_count": group.occupied_count,
            "occupancy_percentage": (
                None
                if group.occupancy_percentage is None
                else str(group.occupancy_percentage)
            ),
            "exceeded_by": group.exceeded_by,
            "official_availability": group.official_availability,
        }
        for group in measurement.groups.all()
    ]


def _create_report(
    *,
    window: DailyStatisticsWindow,
    activation_date: date,
    fingerprint: str,
    revision: int,
    quality_codes: Sequence[str],
) -> DailyStatisticsReport:
    """Persist the ready revision header of one materialized day."""
    assert window.opening is not None
    assert window.closing is not None
    measurement = window.closing.measurement
    return DailyStatisticsReport.objects.create(
        local_date=window.local_date,
        revision=revision,
        status=DailyStatisticsReportStatus.READY,
        activation_date=activation_date,
        anchor_run_id=_run_pk(window.anchor),
        opening_run_id=window.opening.run.pk,
        closing_run_id=window.closing.run.pk,
        measurement=measurement,
        catalog=measurement.catalog,
        algorithm_version=measurement.algorithm_version,
        source_fingerprint=fingerprint,
        quality_warnings_json=list(quality_codes),
    )


def _create_sectors(
    *,
    report: DailyStatisticsReport,
    measurement: OccupancyMeasurement,
) -> dict[str, DailyStatisticsSector]:
    """Copy every official group of the exact measurement into the revision."""
    DailyStatisticsSector.objects.bulk_create(
        [
            DailyStatisticsSector(
                report=report,
                stable_key=group.stable_key,
                display_name=group.display_name,
                calculation_policy=group.calculation_policy,
                calculation_status=group.calculation_status,
                official_capacity=group.official_capacity,
                occupied_count=group.occupied_count,
                occupancy_percentage=group.occupancy_percentage,
                exceeded_by=group.exceeded_by,
                official_availability=group.official_availability,
            )
            for group in measurement.groups.all()
        ]
    )
    return {sector.stable_key: sector for sector in report.sectors.all()}


def _create_patients(
    *,
    report: DailyStatisticsReport,
    photograph: Sequence[CensusSnapshot],
    assignment: Mapping[int, str | None],
    sectors: Mapping[str, DailyStatisticsSector],
) -> None:
    """Persist the nominal closing rows attributed to their official group."""
    rows: list[DailyStatisticsPatient] = []
    for bed in photograph:
        if bed.pk not in assignment:
            continue
        stable_key = assignment[bed.pk]
        if stable_key is not None and stable_key not in sectors:
            # The assignment can only return groups of this exact measurement;
            # reaching this branch would mean a silently lost sector row.
            raise DailyStatisticsMaterializationError(
                f"Closing census row {bed.pk} resolved to the unknown official "
                f"group {stable_key!r} of measurement "
                f"{report.measurement_id}."
            )
        rows.append(
            DailyStatisticsPatient(
                report=report,
                sector=None if stable_key is None else sectors[stable_key],
                census_snapshot=bed,
                bed=bed.leito,
                name=bed.nome,
                record=bed.prontuario,
                specialty=bed.especialidade or "",
            )
        )
    if rows:
        DailyStatisticsPatient.objects.bulk_create(rows)


def _create_events(
    *,
    report: DailyStatisticsReport,
    derivation: EventDerivation,
    sectors: Mapping[str, DailyStatisticsSector],
) -> None:
    """Persist one durable row per detected entry, transfer or classified exit.

    A transition only observed between two census photographs carries no
    clinical instant: ``occurred_at`` and ``occurred_on`` stay null and the
    detection interval keeps the uncertainty, so no hour and no clinical date
    are synthesized. Only evidence-classified exits store the clinical value the
    source provided and the inspectable provenance of the chosen evidence row
    (``source_kind``/``source_pk``); every other event keeps both provenance
    fields null. Every event records how its sector was determined.
    """
    rows: list[DailyStatisticsEvent] = []
    for event in derivation.events:
        snapshot_pk = event.census_snapshot.pk
        rows.append(
            DailyStatisticsEvent(
                report=report,
                kind=event.kind,
                origin_nature=event.origin_nature,
                origin_value=event.origin_value,
                origin_policy_version=event.origin_policy_version,
                origin_sector=_attributed_sector(
                    sectors=sectors,
                    stable_key=event.origin_stable_key,
                    report=report,
                    snapshot_pk=snapshot_pk,
                ),
                destination_sector=_attributed_sector(
                    sectors=sectors,
                    stable_key=event.destination_stable_key,
                    report=report,
                    snapshot_pk=snapshot_pk,
                ),
                census_snapshot_id=snapshot_pk,
                record=event.record,
                name=event.name,
                bed=event.bed,
                occurred_at=event.occurred_at,
                occurred_on=event.occurred_on,
                source_kind=event.source_kind,
                source_pk=event.source_pk,
                sector_attribution=event.sector_attribution,
                detected_not_before=event.detected_not_before,
                detected_at=event.detected_at,
                fingerprint=event.fingerprint,
            )
        )
    if rows:
        DailyStatisticsEvent.objects.bulk_create(rows)


def _attributed_sector(
    *,
    sectors: Mapping[str, DailyStatisticsSector],
    stable_key: str | None,
    report: DailyStatisticsReport,
    snapshot_pk: int,
) -> DailyStatisticsSector | None:
    """Persisted sector row of one resolved stable key, or ``None``.

    ``None`` keeps an event endpoint that could not be identified explicit.
    """
    if stable_key is None:
        return None
    sector = sectors.get(stable_key)
    if sector is None:
        # A derived stable key can only come from the groups of this exact
        # measurement; reaching this branch would mean a silently lost sector.
        raise DailyStatisticsMaterializationError(
            f"Event census row {snapshot_pk} resolved to the unknown official "
            f"group {stable_key!r} of measurement {report.measurement_id}."
        )
    return sector
