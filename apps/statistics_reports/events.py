"""Detected entries and internal transfers (DSRS-S3).

The statistical day is a sequence of accepted census *photographs*. The window
selector (DSRS-S1) owns the boundary selection and DSRS-S2 materializes the
closing photograph; this module compares the anchor photograph with the opening
and every accepted photograph up to the closing, and derives the movements a
photograph can prove:

- a patient absent from a photograph and present in the next one entered a
  sector: a classified external origin produces ``hospital_admission``, a
  classified hospital origin produces ``internal_transfer``, and an unknown
  origin keeps ``unclassified_entry`` instead of being silently turned into an
  admission;
- a patient present in one official grouping and then in another produces one
  ``internal_transfer`` carrying both legs, never two independent facts;
- a bed-only change inside one official grouping produces no sector event;
- absent or conflicting patient identity and an unresolvable official
  grouping fail closed: no fact is invented for them and the report keeps the
  gap as an explicit quality code. Both ambiguities are chain-wide: a record
  whose identity conflicted, or whose position never resolved to an official
  grouping, is never used by a later photograph to invent a movement.

A transition that only the census photographs can prove keeps the detection
interval (``detected_not_before`` .. ``detected_at``) and stores no clinical
instant, so no hour is ever synthesized. The anchor photograph is a comparison
base only: it belongs to no revision and yields no event of its own. The
accepted photographs strictly between the selected boundaries are enumerated
with the same public completeness and provenance predicates the selector uses.

This module is read-only: it derives values, it never writes and never changes
source records.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from apps.census.models import BedStatus, CensusSnapshot, OccupancyMeasurement
from apps.census.occupancy import (
    assign_official_group_keys,
    resolve_exact_measurement,
)
from apps.census.services import (
    resolve_single_census_run,
    validate_snapshot_completeness,
)
from apps.ingestion.models import IngestionRun
from apps.statistics_reports.models import DailyStatisticsEventKind
from apps.statistics_reports.origin_policy import (
    DEFAULT_ORIGIN_POLICY,
    OriginNature,
    OriginPolicy,
    normalize_origin_value,
)
from apps.statistics_reports.selection import (
    CENSUS_RUN_INTENT,
    AcceptedCensus,
    DailyStatisticsWindow,
)

ENTRY_LABEL_UNIDENTIFIED_ORIGIN = "Entrada no setor — origem não identificada"
"""Public label of an entry whose origin cannot be classified."""

TRANSFER_LABEL_UNIDENTIFIED_ORIGIN = "Transferência interna — origem não identificada"
"""Public label of a confirmed internal transfer without an origin sector."""

QUALITY_AMBIGUOUS_PATIENT_IDENTITY = "ambiguous_patient_identity"
"""Quality code: a photograph observed an identity it could not resolve.

Either one source record occupying more than one position at once or an
occupied row whose record or name is missing or unusable.
"""

QUALITY_AMBIGUOUS_SECTOR_MAPPING = "ambiguous_sector_mapping"
"""Quality code: an identified position has no official grouping to attribute."""

_BED_TOKEN_RE = re.compile(r"(\d+)")


class EntryDerivationError(Exception):
    """The selected window cannot produce detected entry events."""


def entry_event_label(*, kind: str, origin_sector_id: int | None) -> str | None:
    """Explicit label of one entry event whose nature hides information.

    Args:
        kind: Stable normalized event kind.
        origin_sector_id: Official grouping the patient left, when known.

    Returns:
        The descriptive label of an unclassified entry or of a confirmed
        internal transfer without an origin sector, or ``None`` when the event
        has both endpoints and keeps the confirmed kind's own label.
    """
    if kind == DailyStatisticsEventKind.UNCLASSIFIED_ENTRY:
        return ENTRY_LABEL_UNIDENTIFIED_ORIGIN
    if (
        kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        and origin_sector_id is None
    ):
        return TRANSFER_LABEL_UNIDENTIFIED_ORIGIN
    return None


def natural_bed_order_key(*, bed: str, name: str, record: str) -> tuple[object, ...]:
    """Natural ordering key of one report row that carries a bed.

    Bed labels sort by their alphanumeric segments, so ``2`` precedes ``10``
    and ``UTI02`` precedes ``UTI10``. Rows without a bed come after every row
    with a bed, and normalized name and record break the remaining ties.
    """
    cleaned = bed.strip()
    return (
        0 if cleaned else 1,
        _bed_tokens(cleaned),
        _normalized_text(name),
        record.strip(),
    )


def _bed_tokens(bed: str) -> tuple[tuple[int, object], ...]:
    """Numeric-aware tokens of one bed label; digits sort before letters."""
    tokens: list[tuple[int, object]] = []
    for part in _BED_TOKEN_RE.split(bed):
        if not part:
            continue
        tokens.append((0, int(part)) if part.isdigit() else (1, part.upper()))
    return tuple(tokens)


def _normalized_text(value: str) -> str:
    """Normalized comparison text: strip, uppercase, collapse inner spaces."""
    return " ".join(value.split()).upper()


@dataclass(frozen=True)
class PatientPosition:
    """Resolved position of one identified patient in one photograph.

    ``stable_key`` is the official historical grouping of the closing
    measurement; ``None`` keeps a grouping that cannot be resolved explicit.
    """

    stable_key: str | None
    row: CensusSnapshot


@dataclass(frozen=True)
class ChainPhotograph:
    """One accepted census photograph of the comparison chain.

    ``positions`` holds every identified patient with an unambiguous identity;
    ``ambiguous_records`` holds the records occupying more than one position at
    once and ``incomplete_identity_records`` the record of every occupied row
    whose identity is missing or unusable (``None`` when the row kept no usable
    record). Conflicting and incomplete identities are never used to invent a
    movement, and an unresolved grouping is never attributed to a sector.
    """

    run: IngestionRun
    captured_at: datetime
    positions: Mapping[str, PatientPosition]
    ambiguous_records: frozenset[str]
    incomplete_identity_records: frozenset[str | None]

    @property
    def has_unresolved_identity(self) -> bool:
        """Whether this photograph observed an identity it could not resolve."""
        return bool(self.ambiguous_records) or bool(
            self.incomplete_identity_records
        )

    @property
    def has_unresolved_grouping(self) -> bool:
        """Whether an identified position has no official grouping here."""
        return any(
            position.stable_key is None for position in self.positions.values()
        )

    @property
    def identity_tainted_records(self) -> frozenset[str]:
        """Records this photograph observed with an untrustworthy identity."""
        return self.ambiguous_records | frozenset(
            record
            for record in self.incomplete_identity_records
            if record is not None
        )

    @property
    def observed_records(self) -> frozenset[str]:
        """Every source record this photograph observed, ambiguous or not."""
        return frozenset(self.positions) | self.ambiguous_records


@dataclass(frozen=True)
class EntryEvent:
    """One detected entry or internal transfer of a revision."""

    kind: str
    record: str
    name: str
    bed: str
    origin_stable_key: str | None
    destination_stable_key: str | None
    origin_nature: str
    origin_value: str
    origin_policy_version: str
    detected_not_before: datetime
    detected_at: datetime
    census_snapshot: CensusSnapshot
    fingerprint: str


@dataclass(frozen=True)
class EntryDerivation:
    """Detected entry events and explicit quality of one statistical day.

    ``chain`` is the ordered comparison chain; its first photograph is only the
    comparison base and yields no event of its own.
    """

    events: tuple[EntryEvent, ...]
    quality_codes: tuple[str, ...]
    origin_policy_version: str
    chain: tuple[ChainPhotograph, ...]


def derive_entry_events(
    *,
    window: DailyStatisticsWindow,
    origin_policy: OriginPolicy = DEFAULT_ORIGIN_POLICY,
) -> EntryDerivation:
    """Derive the detected entries and internal transfers of one window.

    Args:
        window: Selected statistical day of DSRS-S1; it must carry an accepted
            opening and closing photograph.
        origin_policy: Versioned origin mapping in force; the declared policy
            classifies nothing until real source values are characterized.

    Returns:
        The detected entry events in deterministic order, the explicit quality
        codes of the compared photographs, the policy version used and the
        compared chain.

    Raises:
        EntryDerivationError: When the window has no accepted opening or
            closing photograph.
    """
    if window.opening is None or window.closing is None:
        raise EntryDerivationError(
            f"Local date {window.local_date.isoformat()} has no accepted "
            "opening and closing photograph to compare."
        )

    chain = _census_chain(window=window)
    events, quality_codes = _derive_transitions(
        chain=chain,
        origin_policy=origin_policy,
    )
    return EntryDerivation(
        events=tuple(events),
        quality_codes=tuple(sorted(quality_codes)),
        origin_policy_version=origin_policy.version,
        chain=chain,
    )


def _census_chain(*, window: DailyStatisticsWindow) -> tuple[ChainPhotograph, ...]:
    """Accepted photographs of the day in comparison order.

    The anchor, opening and closing come from the window selector; the accepted
    photographs strictly between the boundaries are enumerated here with the
    same acceptance contract. The closing measurement pins the historical
    catalog used to attribute every photograph.
    """
    assert window.opening is not None
    assert window.closing is not None
    measurement = window.closing.measurement
    opening = _photograph(census=window.opening, measurement=measurement)
    closing = _photograph(census=window.closing, measurement=measurement)

    selected_runs = {window.opening.run.pk, window.closing.run.pk}
    chain: list[ChainPhotograph] = []
    if window.anchor is not None:
        selected_runs.add(window.anchor.run.pk)
        chain.append(_photograph(census=window.anchor, measurement=measurement))
    chain.append(opening)
    chain.extend(
        _interior_photographs(
            measurement=measurement,
            after=opening.captured_at,
            before=closing.captured_at,
            excluded_run_ids=frozenset(selected_runs),
        )
    )
    chain.append(closing)
    return tuple(chain)


def _interior_photographs(
    *,
    measurement: OccupancyMeasurement,
    after: datetime,
    before: datetime,
    excluded_run_ids: frozenset[int],
) -> list[ChainPhotograph]:
    """Accepted photographs captured strictly between two boundaries."""
    run_ids = (
        CensusSnapshot.objects.filter(
            captured_at__gt=after,
            captured_at__lt=before,
        )
        .order_by()
        .values_list("ingestion_run_id", flat=True)
        .distinct()
    )
    photographs: list[ChainPhotograph] = []
    for run in (
        IngestionRun.objects.filter(
            pk__in=list(run_ids),
            intent=CENSUS_RUN_INTENT,
            status="succeeded",
            finished_at__isnull=False,
        )
        .exclude(pk__in=excluded_run_ids)
        .order_by("finished_at", "pk")
    ):
        accepted = _accepted_census(run)
        if accepted is not None:
            photographs.append(
                _photograph(census=accepted, measurement=measurement)
            )
    photographs.sort(key=lambda photograph: photograph.captured_at)
    return photographs


def _accepted_census(run: IngestionRun) -> AcceptedCensus | None:
    """Accept ``run`` as a census photograph, or return ``None``.

    The acceptance contract lives in the read-only window selector; this
    module restates only the combination of the same public predicates
    (complete single-instant snapshot coverage, unique provenance and the exact
    official measurement of that run) for the photographs strictly inside the
    selected boundaries.
    """
    captured_at = _unique_capture_instant(run)
    if captured_at is None:
        return None

    photograph = CensusSnapshot.objects.filter(captured_at=captured_at)
    if not validate_snapshot_completeness(photograph)["accepted"]:
        return None
    if resolve_single_census_run(photograph) != run.pk:
        return None

    measurement = resolve_exact_measurement(photograph)
    if measurement is None:
        return None
    return AcceptedCensus(run=run, measurement=measurement)


def _unique_capture_instant(run: IngestionRun) -> datetime | None:
    """Single snapshot instant of ``run``, or ``None`` when ambiguous."""
    instants = set(
        CensusSnapshot.objects.filter(ingestion_run_id=run.pk)
        .order_by()
        .values_list("captured_at", flat=True)
        .distinct()
    )
    if len(instants) != 1:
        return None
    return instants.pop()


def _photograph(
    *,
    census: AcceptedCensus,
    measurement: OccupancyMeasurement,
) -> ChainPhotograph:
    """One chain photograph with the positions of its identified patients.

    Acceptance guarantees that an accepted run owns one single snapshot
    capture instant, so the first row carries the photograph instant. The
    passed measurement pins the historical catalog used to attribute the
    official grouping of every row of this photograph.
    """
    rows = tuple(
        CensusSnapshot.objects.filter(ingestion_run_id=census.run.pk).order_by(
            "pk"
        )
    )
    assert rows, f"Accepted run {census.run.pk} has no census snapshot rows."
    assignment = assign_official_group_keys(
        measurement=measurement,
        snapshots=rows,
    )
    (
        positions,
        ambiguous_records,
        incomplete_identity_records,
    ) = _resolve_positions(
        rows=rows,
        assignment=assignment,
    )
    return ChainPhotograph(
        run=census.run,
        captured_at=rows[0].captured_at,
        positions=positions,
        ambiguous_records=ambiguous_records,
        incomplete_identity_records=incomplete_identity_records,
    )


def _resolve_positions(
    *,
    rows: Sequence[CensusSnapshot],
    assignment: Mapping[int, str | None],
) -> tuple[dict[str, PatientPosition], frozenset[str], frozenset[str | None]]:
    """Positions of the identified patients of one photograph.

    Rows absent from ``assignment`` are not identified patients under the
    shared identity contract (missing or unusable record, missing name,
    operational bed marker or non-occupied bed) and produce no position at all.
    A source record holding more than one position is conflicting identity:
    neither position is kept and the record is reported separately. Every row
    whose identity is incomplete is reported too, so the comparison never drops
    it silently; ``None`` marks the row of an incomplete identity without a
    usable record. An incomplete row that still carries a usable record makes
    that record unusable for the whole photograph: the resolved position under
    the same record is discarded and the record joins the ambiguous ones, so no
    movement is asserted from a record the photograph observed twice with one
    trustworthy and one incomplete identity.
    """
    positions: dict[str, PatientPosition] = {}
    ambiguous_records: set[str] = set()
    incomplete_identity_records: set[str | None] = set()
    for row in rows:
        if row.pk not in assignment:
            if _incomplete_identity(row):
                incomplete_identity_records.add(row.prontuario.strip() or None)
            continue
        record = row.prontuario.strip()
        if not record or record in ambiguous_records:
            continue
        if record in positions:
            del positions[record]
            ambiguous_records.add(record)
            continue
        positions[record] = PatientPosition(
            stable_key=assignment[row.pk],
            row=row,
        )
    for incomplete_record in incomplete_identity_records:
        if incomplete_record is None:
            continue
        if positions.pop(incomplete_record, None) is not None:
            ambiguous_records.add(incomplete_record)
    return positions, frozenset(ambiguous_records), frozenset(
        incomplete_identity_records
    )


def _incomplete_identity(row: CensusSnapshot) -> bool:
    """Whether one occupied row hides a patient identity from the contract.

    The shared identity contract of ``assign_official_group_keys`` identifies
    only occupied rows carrying a digits-only record and a non-marker,
    non-empty name. Of the rows it leaves out, another bed status is not a
    patient row at all and an operational state label (e.g. ``RESERVA
    INTERNA``) never was a patient, so neither is an identity ambiguity; a
    missing or non-numeric record and a missing name are.
    """
    if row.bed_status != BedStatus.OCCUPIED:
        return False
    record = row.prontuario.strip()
    return not (record.isdigit() and _normalized_text(row.nome))


def _derive_transitions(
    *,
    chain: Sequence[ChainPhotograph],
    origin_policy: OriginPolicy,
) -> tuple[list[EntryEvent], set[str]]:
    """Compare consecutive photographs and derive their detected movements.

    Identity and grouping ambiguity are chain-wide: a record whose identity
    conflicted or was incomplete, and a record whose position never resolved to
    an official grouping, keep that taint for every later photograph. A
    reappearance after a gap can therefore never be read as a movement derived
    from evidence the chain already distrusted.
    """
    events: list[EntryEvent] = []
    quality_codes: set[str] = set()
    observed_records: set[str] = set()
    identity_tainted: set[str] = set()
    mapping_tainted: set[str] = set()
    previous: ChainPhotograph | None = None
    for photograph in chain:
        if photograph.has_unresolved_identity:
            quality_codes.add(QUALITY_AMBIGUOUS_PATIENT_IDENTITY)
        if photograph.has_unresolved_grouping:
            quality_codes.add(QUALITY_AMBIGUOUS_SECTOR_MAPPING)
        if previous is not None:
            derived, codes = _derive_between(
                previous=previous,
                photograph=photograph,
                observed_records=frozenset(observed_records),
                identity_tainted=frozenset(identity_tainted),
                mapping_tainted=frozenset(mapping_tainted),
                origin_policy=origin_policy,
            )
            events.extend(derived)
            quality_codes.update(codes)
        observed_records.update(photograph.observed_records)
        identity_tainted.update(photograph.identity_tainted_records)
        mapping_tainted.update(
            record
            for record, position in photograph.positions.items()
            if position.stable_key is None
        )
        previous = photograph
    return events, quality_codes


def _derive_between(
    *,
    previous: ChainPhotograph,
    photograph: ChainPhotograph,
    observed_records: frozenset[str],
    identity_tainted: frozenset[str],
    mapping_tainted: frozenset[str],
    origin_policy: OriginPolicy,
) -> tuple[list[EntryEvent], set[str]]:
    """Derive the movements one consecutive photograph pair can prove.

    Departures, deaths and hospital discharges belong to DSRS-S4: a patient
    present in ``previous`` and missing from ``photograph`` produces nothing
    here.
    """
    events: list[EntryEvent] = []
    quality_codes: set[str] = set()
    for record, position in photograph.positions.items():
        if record in identity_tainted:
            # The chain already holds a contradictory or incomplete identity
            # for this record: no movement is asserted from an identity that
            # cannot be trusted, not even after it reappears.
            quality_codes.add(QUALITY_AMBIGUOUS_PATIENT_IDENTITY)
            continue

        previous_position = previous.positions.get(record)
        previous_key = (
            None if previous_position is None else previous_position.stable_key
        )
        if position.stable_key is None:
            # The detecting photograph has no official grouping to attribute:
            # fail closed instead of choosing a sector arbitrarily. An
            # unchanged ``None`` position is no exception.
            quality_codes.add(QUALITY_AMBIGUOUS_SECTOR_MAPPING)
            continue
        if previous_position is not None and position.stable_key == previous_key:
            # Same official grouping: a bed-only change is no sector event.
            continue

        if previous_position is None:
            if record in observed_records:
                if record in mapping_tainted:
                    # The earlier position never resolved to an official
                    # grouping, so no origin can be attributed and no transfer
                    # is invented from it.
                    quality_codes.add(QUALITY_AMBIGUOUS_SECTOR_MAPPING)
                    continue
                # The patient was already inside the hospital, so the arrival
                # is a transfer whose earlier position cannot be identified.
                events.append(
                    _build_event(
                        kind=DailyStatisticsEventKind.INTERNAL_TRANSFER,
                        record=record,
                        position=position,
                        origin_stable_key=None,
                        origin_nature=OriginNature.HOSPITAL_INTERNAL,
                        origin_value="",
                        origin_policy_version=origin_policy.version,
                        previous=previous,
                        photograph=photograph,
                    )
                )
                continue
            nature = (
                origin_policy.classify(position.row.origem)
                or OriginNature.UNKNOWN
            )
            events.append(
                _build_event(
                    kind=_entry_kind(nature=nature),
                    record=record,
                    position=position,
                    origin_stable_key=None,
                    origin_nature=nature,
                    origin_value=normalize_origin_value(position.row.origem),
                    origin_policy_version=origin_policy.version,
                    previous=previous,
                    photograph=photograph,
                )
            )
            continue

        if previous_key is None:
            # The grouping changed, but the previous position never resolved
            # to an official sector: the destination is confirmed and the
            # origin stays explicitly unidentified.
            quality_codes.add(QUALITY_AMBIGUOUS_SECTOR_MAPPING)
        events.append(
            _build_event(
                kind=DailyStatisticsEventKind.INTERNAL_TRANSFER,
                record=record,
                position=position,
                origin_stable_key=previous_key,
                origin_nature=OriginNature.HOSPITAL_INTERNAL,
                origin_value="",
                origin_policy_version=origin_policy.version,
                previous=previous,
                photograph=photograph,
            )
        )
    return events, quality_codes


def _entry_kind(*, nature: str) -> str:
    """Stable kind of an entry whose origin was classified from its source."""
    if nature == OriginNature.EXTERNAL:
        return DailyStatisticsEventKind.HOSPITAL_ADMISSION
    if nature == OriginNature.HOSPITAL_INTERNAL:
        return DailyStatisticsEventKind.INTERNAL_TRANSFER
    return DailyStatisticsEventKind.UNCLASSIFIED_ENTRY


def _build_event(
    *,
    kind: str,
    record: str,
    position: PatientPosition,
    origin_stable_key: str | None,
    origin_nature: str,
    origin_value: str,
    origin_policy_version: str,
    previous: ChainPhotograph,
    photograph: ChainPhotograph,
) -> EntryEvent:
    """One detected fact with its detection interval and identity."""
    row = position.row
    return EntryEvent(
        kind=kind,
        record=record,
        name=row.nome,
        bed=row.leito,
        origin_stable_key=origin_stable_key,
        destination_stable_key=position.stable_key,
        origin_nature=origin_nature,
        origin_value=origin_value,
        origin_policy_version=origin_policy_version,
        detected_not_before=previous.captured_at,
        detected_at=photograph.captured_at,
        census_snapshot=row,
        fingerprint=_event_fingerprint(
            kind=kind,
            record=record,
            name=row.nome,
            bed=row.leito,
            origin_stable_key=origin_stable_key,
            destination_stable_key=position.stable_key,
            origin_nature=origin_nature,
            origin_value=origin_value,
            origin_policy_version=origin_policy_version,
            detected_not_before=previous.captured_at,
            detected_at=photograph.captured_at,
            census_snapshot_pk=row.pk,
        ),
    )


def _event_fingerprint(
    *,
    kind: str,
    record: str,
    name: str,
    bed: str,
    origin_stable_key: str | None,
    destination_stable_key: str | None,
    origin_nature: str,
    origin_value: str,
    origin_policy_version: str,
    detected_not_before: datetime,
    detected_at: datetime,
    census_snapshot_pk: int,
) -> str:
    """Deterministic SHA-256 identity of one detected fact.

    The payload covers every value this event persists, including the nominal
    name of the detecting row, so a corrected source name publishes a new
    revision instead of leaving the former nominal data in place. It is scoped
    by the unique ``(report, fingerprint)`` constraint, so a repeated build of
    the same sources derives the same identity and a changed detection never
    collides with an existing fact.
    """
    payload: dict[str, object] = {
        "kind": kind,
        "record": record,
        "name": name,
        "bed": bed,
        "origin": origin_stable_key,
        "destination": destination_stable_key,
        "origin_nature": origin_nature,
        "origin_value": origin_value,
        "origin_policy_version": origin_policy_version,
        "detected_not_before": detected_not_before.isoformat(),
        "detected_at": detected_at.isoformat(),
        "census_snapshot": census_snapshot_pk,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
