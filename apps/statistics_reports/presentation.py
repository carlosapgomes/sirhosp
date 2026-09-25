"""Read-only projection of one daily statistics revision (DSRS-S6).

One materialized revision is read once and turned into the wording both
authorized surfaces use, so the HTML page and the later XLSX workbook of the
same slice family can never disagree:

- an official grouping is rendered as one ``ReportGroup`` whose header badges
  copy the persisted metrics of the exact closing measurement -- capacity,
  occupancy, balance and excess are never recalculated here;
- the closing nominal rows are grouped by their persisted official grouping;
- every detected event is rendered in the list of the sector it belongs to:
  an entry in its destination's list, an exit in its origin's list, and an
  event whose origin or destination could not be identified in the descriptive
  list of the endpoint that is known, using the explicit labels the event
  derivation already owns;
- an event whose origin and destination are both unknown belongs to no official
  grouping: it is shown once in the report-level ``Setor não identificado``
  section instead of being omitted or arbitrarily attributed, and a closing
  row without an official grouping stays there too.

Every list keeps its title, its count badge and an explicit empty state, the
shared natural bed ordering orders both events and patients, and the read-only
contract is complete: nothing here writes, and a page can never rebuild a
revision.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.census.models import OccupancyCalculationStatus
from apps.statistics_reports.events import (
    entry_event_label,
    exit_event_label,
    natural_bed_order_key,
)
from apps.statistics_reports.models import (
    DailyStatisticsEvent,
    DailyStatisticsEventKind,
    DailyStatisticsPatient,
    DailyStatisticsReport,
    DailyStatisticsReportStatus,
    DailyStatisticsSector,
)
from apps.statistics_reports.origin_policy import OriginNature
from apps.statistics_reports.selection import BAHIA_TZ

UNKNOWN_SECTION_KEY = "unknown"
"""DOM-safe key of the conditional report-level section without an official key."""

UNKNOWN_SECTION_TITLE = "Setor não identificado"
"""Report-level section of the events no official grouping could be attributed to."""

ENTRY_LIST_KEY = "entries"
EXIT_LIST_KEY = "exits"
UNIDENTIFIED_LIST_KEY = "unidentified"
PATIENT_LIST_KEY = "patients"

ENTRY_LIST_TITLE = "Entradas"
EXIT_LIST_TITLE = "Saídas"
UNIDENTIFIED_LIST_TITLE = "Eventos com origem ou destino não identificado"
PATIENT_LIST_TITLE = "Pacientes do fechamento"

ENTRY_LIST_EMPTY = "Nenhuma entrada detectada neste setor."
EXIT_LIST_EMPTY = "Nenhuma saída detectada neste setor."
UNIDENTIFIED_LIST_EMPTY = (
    "Nenhum evento com origem ou destino não identificado neste setor."
)
PATIENT_LIST_EMPTY = "Nenhum paciente do fechamento neste setor."

UNKNOWN_EVENT_LIST_TITLE = "Eventos sem setor identificado"
UNKNOWN_EVENT_LIST_EMPTY = "Nenhum evento sem setor identificado."
UNKNOWN_PATIENT_LIST_TITLE = "Pacientes sem setor identificado"
UNKNOWN_PATIENT_LIST_EMPTY = "Nenhum paciente sem setor identificado."

ORIGIN_EXTERNAL_LABEL = "Origem externa ao hospital"
"""Origin wording of an entry whose classified nature is external to the hospital."""

ORIGIN_UNIDENTIFIED_LABEL = "Origem não identificada"
"""Origin wording of an event whose origin sector could not be identified."""

DESTINATION_UNIDENTIFIED_LABEL = "Destino não identificado"
"""Destination wording of an event whose destination could not be identified."""

DESTINATION_NOT_APPLICABLE_LABEL = "Sem destino setorial"
"""Destination wording of a clinical exit that has no destination sector by nature."""

CLINICAL_MOMENT_UNAVAILABLE_LABEL = "Momento clínico não informado"
"""Wording of a transition only observed between two census photographs."""

CALCULATION_STATE_LABELS: dict[str, str] = {
    OccupancyCalculationStatus.LINKED_SLOTS_PENDING: "cálculo pendente",
    OccupancyCalculationStatus.UNRATED: "fora da taxa oficial",
    OccupancyCalculationStatus.UNMAPPED: "sem mapeamento no catálogo",
}
"""Explicit state of an official grouping whose capacity is not calculable."""

_ENTRY_KINDS: frozenset[str] = frozenset(
    {
        DailyStatisticsEventKind.HOSPITAL_ADMISSION,
        DailyStatisticsEventKind.INTERNAL_TRANSFER,
        DailyStatisticsEventKind.UNCLASSIFIED_ENTRY,
    }
)
"""Event kinds read as an arrival at a sector."""

_EXIT_KINDS: frozenset[str] = frozenset(
    {
        DailyStatisticsEventKind.DEATH,
        DailyStatisticsEventKind.HOSPITAL_DISCHARGE,
        DailyStatisticsEventKind.INTERNAL_TRANSFER,
        DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE,
    }
)
"""Event kinds read as a departure from a sector."""

_CONFIRMED_SINGLE_ENDPOINT_KINDS: frozenset[str] = frozenset(
    {
        DailyStatisticsEventKind.HOSPITAL_ADMISSION,
        DailyStatisticsEventKind.DEATH,
        DailyStatisticsEventKind.HOSPITAL_DISCHARGE,
    }
)
"""Event kinds whose nature is confirmed even with one sector endpoint only."""

_BUCKET_ADMISSIONS = "admissions"
_BUCKET_TRANSFER_ENTRIES = "transfer_entries"
_BUCKET_DEATHS = "deaths"
_BUCKET_TRANSFER_EXITS = "transfer_exits"
_BUCKET_DISCHARGES = "discharges"
_BUCKET_UNIDENTIFIED = "unidentified"


@dataclass(frozen=True)
class HeaderBadge:
    """One already formatted header badge of a rendered group."""

    label: str
    css: str


@dataclass(frozen=True)
class EventRow:
    """One detected event with the wording the authorized surfaces render."""

    event: DailyStatisticsEvent
    label: str
    origin_display: str
    destination_display: str
    clinical_display: str
    detection_display: str


@dataclass(frozen=True)
class SectorList:
    """One counted list of a rendered group, empty state included."""

    key: str
    title: str
    empty_label: str
    events: tuple[EventRow, ...] = ()
    patients: tuple[DailyStatisticsPatient, ...] = ()

    @property
    def badge_count(self) -> int:
        """Count shown beside the list title, zero when the list is empty."""
        return len(self.events) + len(self.patients)


@dataclass(frozen=True)
class ReportGroup:
    """One rendered group: an official grouping or the conditional unknown one.

    The fine-grained sections match the fixed XLSX sections of the export
    slice, while ``lists`` is what the page collapses, so both surfaces read
    the same rows in the same order.
    """

    key: str
    stable_key: str
    title: str
    is_unknown_section: bool
    header_badges: tuple[HeaderBadge, ...]
    admissions: tuple[EventRow, ...] = ()
    transfer_entries: tuple[EventRow, ...] = ()
    deaths: tuple[EventRow, ...] = ()
    transfer_exits: tuple[EventRow, ...] = ()
    discharges: tuple[EventRow, ...] = ()
    unidentified: tuple[EventRow, ...] = ()
    patients: tuple[DailyStatisticsPatient, ...] = ()

    @property
    def entries(self) -> tuple[EventRow, ...]:
        """Arrivals of this group: hospital admissions and transfer arrivals."""
        return self.admissions + self.transfer_entries

    @property
    def exits(self) -> tuple[EventRow, ...]:
        """Departures of this group: deaths, transfers and hospital discharges."""
        return self.deaths + self.transfer_exits + self.discharges

    @property
    def lists(self) -> tuple[SectorList, ...]:
        """Collapsible lists of this group, always all of them, empty or not."""
        if self.is_unknown_section:
            return (
                SectorList(
                    key=UNIDENTIFIED_LIST_KEY,
                    title=UNKNOWN_EVENT_LIST_TITLE,
                    empty_label=UNKNOWN_EVENT_LIST_EMPTY,
                    events=self.unidentified,
                ),
                SectorList(
                    key=PATIENT_LIST_KEY,
                    title=UNKNOWN_PATIENT_LIST_TITLE,
                    empty_label=UNKNOWN_PATIENT_LIST_EMPTY,
                    patients=self.patients,
                ),
            )
        return (
            SectorList(
                key=ENTRY_LIST_KEY,
                title=ENTRY_LIST_TITLE,
                empty_label=ENTRY_LIST_EMPTY,
                events=self.entries,
            ),
            SectorList(
                key=EXIT_LIST_KEY,
                title=EXIT_LIST_TITLE,
                empty_label=EXIT_LIST_EMPTY,
                events=self.exits,
            ),
            SectorList(
                key=UNIDENTIFIED_LIST_KEY,
                title=UNIDENTIFIED_LIST_TITLE,
                empty_label=UNIDENTIFIED_LIST_EMPTY,
                events=self.unidentified,
            ),
            SectorList(
                key=PATIENT_LIST_KEY,
                title=PATIENT_LIST_TITLE,
                empty_label=PATIENT_LIST_EMPTY,
                patients=self.patients,
            ),
        )


@dataclass(frozen=True)
class DailyReportProjection:
    """The whole rendered answer of one materialized revision."""

    report: DailyStatisticsReport
    groups: tuple[ReportGroup, ...]

    @property
    def quality_warnings(self) -> tuple[str, ...]:
        """Aggregate quality codes of the selected window, in stored order."""
        return tuple(self.report.quality_warnings_json)

    @property
    def unknown_section(self) -> ReportGroup | None:
        """The conditional report-level section, when it exists."""
        for group in self.groups:
            if group.is_unknown_section:
                return group
        return None


def default_report_date() -> date | None:
    """Date the page opens without an explicit request, or ``None``.

    Yesterday when it is ready and otherwise the latest ready date: any ready
    date strictly before the current ``America/Bahia`` date is exactly those
    two cases, and a day still being observed is therefore never selected.
    """
    return (
        DailyStatisticsReport.objects.filter(
            status=DailyStatisticsReportStatus.READY,
            local_date__lt=_bahia_today(),
        )
        .order_by("-local_date")
        .values_list("local_date", flat=True)
        .first()
    )


def daily_report_projection(local_date: date) -> DailyReportProjection | None:
    """Projection of the ready revision of one date, or ``None`` when absent.

    A date without a ready revision is an explicit, expected state: nothing is
    materialized on demand and no earlier revision is reused as current.
    """
    report = (
        DailyStatisticsReport.objects.filter(
            local_date=local_date,
            status=DailyStatisticsReportStatus.READY,
        )
        .select_related("opening_run", "closing_run", "measurement", "catalog")
        .first()
    )
    if report is None:
        return None
    return build_daily_report_projection(report)


def build_daily_report_projection(
    report: DailyStatisticsReport,
) -> DailyReportProjection:
    """Render one materialized revision with a bounded number of queries.

    The revision is read as four bulk queries -- sectors, events, patients and
    the report itself -- and grouped in memory, so the cost never grows with
    the number of sectors, patients or detected events.
    """
    sectors = tuple(DailyStatisticsSector.objects.filter(report=report))
    rows = tuple(
        sorted(
            (
                _event_row(event)
                for event in DailyStatisticsEvent.objects.filter(
                    report=report
                ).select_related(
                    "origin_sector", "destination_sector", "census_snapshot"
                )
            ),
            key=_row_sort_key,
        )
    )
    buckets, unknown_events = _place_rows(rows)
    patients = _patients_by_sector(report=report)

    groups = [
        _sector_group(
            sector=sector,
            buckets=buckets,
            patients=patients.get(sector.pk, ()),
        )
        for sector in sectors
    ]
    unknown_section = _unknown_section_group(
        events=unknown_events,
        patients=patients.get(None, ()),
    )
    if unknown_section is not None:
        groups.insert(0, unknown_section)
    return DailyReportProjection(report=report, groups=tuple(groups))


def event_has_unidentified_endpoint(event: DailyStatisticsEvent) -> bool:
    """Whether one event needs the descriptive wording of a missing endpoint.

    A hospital admission keeps its classified external nature and a clinical
    exit keeps its own confirmed nature, both with a single sector endpoint;
    only an entry whose origin could not be classified, a departure whose
    destination could not be determined and a confirmed internal transfer
    missing one endpoint carry an unidentified endpoint. An event with both
    endpoints null has no attributing sector at all, so its confirmed kind can
    never keep it out of the report-level section.
    """
    if event.origin_sector_id is None and event.destination_sector_id is None:
        return True
    if event.kind in _CONFIRMED_SINGLE_ENDPOINT_KINDS:
        return False
    if event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER:
        return (
            event.origin_sector_id is None
            or event.destination_sector_id is None
        )
    return True


def _bahia_today() -> date:
    """Current ``America/Bahia`` local date, independent of the UTC date."""
    return timezone.now().astimezone(BAHIA_TZ).date()


def _patients_by_sector(
    *, report: DailyStatisticsReport
) -> dict[int | None, tuple[DailyStatisticsPatient, ...]]:
    """Closing nominal rows grouped by grouping and naturally ordered."""
    grouped: dict[int | None, list[DailyStatisticsPatient]] = defaultdict(list)
    for patient in DailyStatisticsPatient.objects.filter(report=report):
        grouped[patient.sector_id].append(patient)
    return {
        sector_id: tuple(
            sorted(rows, key=_patient_sort_key)
        )
        for sector_id, rows in grouped.items()
    }


def _sector_group(
    *,
    sector: DailyStatisticsSector,
    buckets: dict[tuple[int, str], list[EventRow]],
    patients: Sequence[DailyStatisticsPatient],
) -> ReportGroup:
    """One official grouping with its copied metrics and its lists."""
    def rows(bucket: str) -> tuple[EventRow, ...]:
        return tuple(buckets.get((sector.pk, bucket), ()))

    return ReportGroup(
        key=str(sector.pk),
        stable_key=sector.stable_key,
        title=sector.display_name,
        is_unknown_section=False,
        header_badges=_sector_badges(sector=sector, patient_count=len(patients)),
        admissions=rows(_BUCKET_ADMISSIONS),
        transfer_entries=rows(_BUCKET_TRANSFER_ENTRIES),
        deaths=rows(_BUCKET_DEATHS),
        transfer_exits=rows(_BUCKET_TRANSFER_EXITS),
        discharges=rows(_BUCKET_DISCHARGES),
        unidentified=rows(_BUCKET_UNIDENTIFIED),
        patients=tuple(patients),
    )


def _unknown_section_group(
    *,
    events: Sequence[EventRow],
    patients: Sequence[DailyStatisticsPatient],
) -> ReportGroup | None:
    """The conditional report-level section, only when it carries rows."""
    if not events and not patients:
        return None
    return ReportGroup(
        key=UNKNOWN_SECTION_KEY,
        stable_key="",
        title=UNKNOWN_SECTION_TITLE,
        is_unknown_section=True,
        header_badges=(
            HeaderBadge(label=f"Eventos: {len(events)}", css="bg-secondary"),
            HeaderBadge(label=f"Pacientes: {len(patients)}", css="bg-primary"),
        ),
        unidentified=tuple(events),
        patients=tuple(patients),
    )


def _sector_badges(
    *, sector: DailyStatisticsSector, patient_count: int
) -> tuple[HeaderBadge, ...]:
    """Header badges of one official grouping, copied from its own row.

    The patient count is the persisted occupied count of the exact closing
    measurement; the nominal rows of the grouping count as patients only for a
    grouping the measurement itself could not count.
    """
    occupied = (
        sector.occupied_count
        if sector.occupied_count is not None
        else patient_count
    )
    badges = [
        HeaderBadge(label=sector.stable_key, css="bg-light text-dark border"),
        HeaderBadge(label=f"Pacientes: {occupied}", css="bg-primary"),
    ]
    if sector.official_capacity is not None:
        badges.append(
            HeaderBadge(
                label=f"Capacidade: {sector.official_capacity}",
                css="bg-light text-dark border",
            )
        )
    if sector.occupancy_percentage is not None:
        badges.append(
            HeaderBadge(
                label=(
                    "Lotação: "
                    f"{_percentage_label(sector.occupancy_percentage)}%"
                ),
                css="bg-dark",
            )
        )
    if sector.exceeded_by:
        badges.append(
            HeaderBadge(
                label=f"Excedente: {sector.exceeded_by}", css="bg-danger"
            )
        )
    elif sector.official_availability is not None:
        badges.append(
            HeaderBadge(
                label=f"Saldo: {sector.official_availability}",
                css="bg-info text-dark",
            )
        )
    state_label = CALCULATION_STATE_LABELS.get(sector.calculation_status, "")
    if state_label:
        badges.append(HeaderBadge(label=state_label, css="bg-warning text-dark"))
    return tuple(badges)


def _percentage_label(value: Decimal) -> str:
    """One persisted occupancy percentage in the report's decimal spelling."""
    return f"{value:.2f}".replace(".", ",")


def _place_rows(
    rows: Sequence[EventRow],
) -> tuple[dict[tuple[int, str], list[EventRow]], list[EventRow]]:
    """Place every event row in the lists its endpoints allow.

    A confirmed internal transfer is placed once as the destination's arrival
    and once as the origin's departure: it is one fact read from both sides,
    never two facts. An event with one unidentified endpoint is placed only in
    that endpoint's descriptive list, and an event with both endpoints
    unidentified is returned separately for the report-level section.
    """
    buckets: dict[tuple[int, str], list[EventRow]] = defaultdict(list)
    unknown: list[EventRow] = []
    for row in rows:
        event = row.event
        if event_has_unidentified_endpoint(event):
            if event.origin_sector_id is None and event.destination_sector_id is None:
                unknown.append(row)
                continue
            for sector_id in (event.origin_sector_id, event.destination_sector_id):
                if sector_id is not None:
                    buckets[(sector_id, _BUCKET_UNIDENTIFIED)].append(row)
            continue
        if event.destination_sector_id is not None:
            arrivals = (
                _BUCKET_ADMISSIONS
                if event.kind == DailyStatisticsEventKind.HOSPITAL_ADMISSION
                else _BUCKET_TRANSFER_ENTRIES
            )
            buckets[(event.destination_sector_id, arrivals)].append(row)
        if event.origin_sector_id is not None:
            departures = (
                _BUCKET_TRANSFER_EXITS
                if event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
                else _BUCKET_DISCHARGES
                if event.kind == DailyStatisticsEventKind.HOSPITAL_DISCHARGE
                else _BUCKET_DEATHS
            )
            buckets[(event.origin_sector_id, departures)].append(row)
    return buckets, unknown


def _row_sort_key(row: EventRow) -> tuple[object, ...]:
    """Shared natural ordering of one event row plus a deterministic tie-break."""
    event = row.event
    return natural_bed_order_key(
        bed=event.bed, name=event.name, record=event.record
    ) + (event.detected_at, event.fingerprint)


def _patient_sort_key(patient: DailyStatisticsPatient) -> tuple[object, ...]:
    """Shared natural ordering of one closing nominal row."""
    return natural_bed_order_key(
        bed=patient.bed, name=patient.name, record=patient.record
    )


def _event_row(event: DailyStatisticsEvent) -> EventRow:
    """One detected event with every wording the authorized surfaces render."""
    return EventRow(
        event=event,
        label=_event_label(event),
        origin_display=_origin_display(event),
        destination_display=_destination_display(event),
        clinical_display=_clinical_display(event),
        detection_display=_detection_display(event),
    )


def _event_label(event: DailyStatisticsEvent) -> str:
    """Public label of one event, explaining the endpoint it cannot identify."""
    labels = []
    if event.kind in _ENTRY_KINDS:
        labels.append(
            entry_event_label(
                kind=event.kind, origin_sector_id=event.origin_sector_id
            )
        )
    if event.kind in _EXIT_KINDS:
        labels.append(
            exit_event_label(
                kind=event.kind,
                destination_sector_id=event.destination_sector_id,
            )
        )
    for label in labels:
        if label:
            return label
    return event.get_kind_display()


def _origin_display(event: DailyStatisticsEvent) -> str:
    """Wording of the origin side of one event, identified or not."""
    if event.origin_sector_id is not None:
        assert event.origin_sector is not None
        return event.origin_sector.display_name
    if event.origin_nature == OriginNature.EXTERNAL:
        return ORIGIN_EXTERNAL_LABEL
    return ORIGIN_UNIDENTIFIED_LABEL


def _destination_display(event: DailyStatisticsEvent) -> str:
    """Wording of the destination side of one event, identified or not."""
    if event.destination_sector_id is not None:
        assert event.destination_sector is not None
        return event.destination_sector.display_name
    if event.kind in _CONFIRMED_SINGLE_ENDPOINT_KINDS:
        return DESTINATION_NOT_APPLICABLE_LABEL
    return DESTINATION_UNIDENTIFIED_LABEL


def _clinical_display(event: DailyStatisticsEvent) -> str:
    """Clinical moment of one event, never synthesizing an hour or a date.

    An exact aware instant is shown in local time, a clinical date without an
    hour keeps its date and states the missing hour, and a transition only
    observed between two census photographs has no clinical moment at all.
    """
    if event.occurred_at is not None:
        return timezone.localtime(event.occurred_at).strftime("%d/%m/%Y %H:%M")
    if event.occurred_on is not None:
        return (
            f"{event.occurred_on.strftime('%d/%m/%Y')} — hora não informada"
        )
    return CLINICAL_MOMENT_UNAVAILABLE_LABEL


def _detection_display(event: DailyStatisticsEvent) -> str:
    """Detection interval of one event, always shown beside the clinical one."""
    start = timezone.localtime(event.detected_not_before).strftime("%d/%m/%Y %H:%M")
    end = timezone.localtime(event.detected_at).strftime("%d/%m/%Y %H:%M")
    return f"{start} a {end}"
