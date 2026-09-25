"""DSRS-S4 integration tests: exits, precedence and automatic revisions.

Covers the vertical slice requirements:

- R1: the exit precedence death > effective discharge > internal transfer >
  unclassified departure is global to the episode, including a later
  reappearance, and never counts the same episode twice;
- R2: an exact death keeps its clinical instant while a date-only death keeps
  only ``occurred_on`` and never synthesizes an hour, always with detection
  kept separate;
- R3: an effective hospital exit uses ``saida_em``; an isolated ``alta_em``
  never closes the episode;
- R4: an exit whose evidence carries no sector uses only the last census
  position and records the inferred attribution, otherwise the sector stays
  unknown;
- R5: a confirmed transfer from exit -> gap -> reappearance without a resolved
  grouping keeps the origin sector and an unknown destination, a resolved
  reappearance stays the single DSRS-S3 fact, and an unexplained disappearance
  is ``Saída do setor — destino não identificado``, never a discharge;
- R6: the same sources and evidence are idempotent, while different late
  evidence publishes a new current revision and keeps the former as
  superseded;
- R7: a late-evidence revision keeps the same closing photograph and never
  mutates clinical sources.

Everything here uses synthetic runs, sectors, beds, patients and evidence rows;
no real extraction data, no production access and no backfill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.census.models import (
    BedStatus,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
    OccupancyAgeBand,
    OccupancyCalculationStatus,
    OccupancyGroupMeasurement,
    OccupancyMeasurement,
)
from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient
from apps.statistics_reports.events import (
    DEATH_EVIDENCE_KIND,
    DISCHARGE_EVIDENCE_KIND,
    EXIT_LABEL_UNIDENTIFIED_DESTINATION,
    QUALITY_AMBIGUOUS_PATIENT_IDENTITY,
    QUALITY_AMBIGUOUS_SECTOR_MAPPING,
    TRANSFER_LABEL_UNIDENTIFIED_DESTINATION,
    exit_event_label,
)
from apps.statistics_reports.materialization import (
    materialize_daily_statistics,
)
from apps.statistics_reports.models import (
    DailyStatisticsEvent,
    DailyStatisticsEventKind,
    DailyStatisticsReport,
    DailyStatisticsReportStatus,
    DailyStatisticsSectorAttribution,
)
from apps.statistics_reports.origin_policy import (
    DEFAULT_ORIGIN_POLICY,
    OriginPolicy,
)

BAHIA_TZ = ZoneInfo("America/Bahia")

DAY = date(2026, 9, 15)
PREVIOUS_DAY = DAY - timedelta(days=1)
ACTIVATION = date(2026, 9, 1)


def _bahia(day: date, hour: int, minute: int = 0) -> datetime:
    """Aware ``America/Bahia`` instant on ``day``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BAHIA_TZ)


# Photograph instants of the synthetic day: the opening completed after
# midnight (started on the previous civil day), the interior photograph sits
# between the boundaries and the closing completed before midnight.
ANCHOR_AT = _bahia(PREVIOUS_DAY, 21, 30)
OPENING_AT = _bahia(DAY, 0, 30)
INTERIOR_AT = _bahia(DAY, 12, 30)
CLOSING_AT = _bahia(DAY, 21, 30)

# 38 generic synthetic sectors plus the three observed official sectors keep
# every photograph above the official census coverage minimum.
GENERIC_CODES = tuple(str(code) for code in range(902, 940))
GERAL_CODE = "900"
GERAL_SECOND_CODE = "901"
EMERGENCY_CODE = "940"
UNRATED_CODE = "950"
EXTRA_CODE = "960"
OUTSIDE_CATALOG_CODE = "970"

EMERGENCY_SECTOR = "EMERGENCIA SINTETICA"
UNRATED_SECTOR = "SETOR NAO TARIFADO 950"
EXTRA_SECTOR = "SETOR SINTETICO EXTRA"
OUTSIDE_CATALOG_SECTOR = "SETOR FORA DO CATALOGO"

SECTOR_NAMES = {
    GERAL_CODE: f"SETOR SINTETICO {GERAL_CODE}",
    GERAL_SECOND_CODE: f"SETOR SINTETICO {GERAL_SECOND_CODE}",
    EMERGENCY_CODE: EMERGENCY_SECTOR,
    UNRATED_CODE: UNRATED_SECTOR,
    EXTRA_CODE: EXTRA_SECTOR,
    OUTSIDE_CATALOG_CODE: OUTSIDE_CATALOG_SECTOR,
}

EXTERNAL_ORIGIN = "AMBULATORIO EXTERNO SINTETICO"

PATIENT_RECORD = "7001"
PATIENT_NAME = "PACIENTE SINTETICO UM"


# ---------------------------------------------------------------------------
# Synthetic census helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CensusLine:
    """One synthetic census row of a photograph."""

    code: str
    bed: str
    record: str = ""
    name: str = ""
    specialty: str = "CLI"
    origem: str = ""
    sector: str = ""
    age_band: str = OccupancyAgeBand.NOT_APPLICABLE
    status: str = BedStatus.OCCUPIED

    @property
    def sector_name(self) -> str:
        """Source sector name of this row."""
        return self.sector or SECTOR_NAMES.get(
            self.code, f"SETOR SINTETICO {self.code}"
        )


def _occupied(
    *,
    code: str,
    bed: str,
    record: str,
    name: str,
    origem: str = "",
) -> _CensusLine:
    """One identified occupied row of a synthetic photograph."""
    return _CensusLine(
        code=code,
        bed=bed,
        record=record,
        name=name,
        origem=origem,
    )


def _base_lines() -> list[_CensusLine]:
    """One non-occupied row per synthetic sector of a photograph."""
    lines = [
        _CensusLine(code=code, bed=f"L{code}", status=BedStatus.EMPTY)
        for code in GENERIC_CODES
    ]
    lines.extend(
        _CensusLine(code=code, bed=f"{code}-VAGA", status=BedStatus.EMPTY)
        for code in (
            GERAL_CODE,
            GERAL_SECOND_CODE,
            EMERGENCY_CODE,
            UNRATED_CODE,
            EXTRA_CODE,
        )
    )
    return lines


def _group_spec(
    *,
    stable_key: str,
    display_name: str,
    calculation_status: str,
    official_capacity: int | None,
    occupied_count: int | None,
    occupancy_percentage: Decimal | None,
    exceeded_by: int | None,
    official_availability: int | None,
    calculation_policy: str,
    components: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "stable_key": stable_key,
        "display_name": display_name,
        "calculation_status": calculation_status,
        "official_capacity": official_capacity,
        "occupied_count": occupied_count,
        "occupancy_percentage": occupancy_percentage,
        "exceeded_by": exceeded_by,
        "official_availability": official_availability,
        "calculation_policy": calculation_policy,
        "components_json": components,
    }


def _group_specs() -> list[dict[str, object]]:
    """Persisted official groups of the synthetic closing measurement."""
    return [
        _group_spec(
            stable_key="GERAL",
            display_name="Gerais",
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=40,
            occupied_count=1,
            occupancy_percentage=Decimal("2.50"),
            exceeded_by=0,
            official_availability=39,
            calculation_policy="standard",
            components=[
                {
                    "observed_code": GERAL_CODE,
                    "observed_name": SECTOR_NAMES[GERAL_CODE],
                },
                {
                    "observed_code": GERAL_SECOND_CODE,
                    "observed_name": SECTOR_NAMES[GERAL_SECOND_CODE],
                },
            ],
        ),
        _group_spec(
            stable_key="EMERGENCIA",
            display_name="Emergencia",
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=8,
            occupied_count=0,
            occupancy_percentage=Decimal("0.00"),
            exceeded_by=0,
            official_availability=8,
            calculation_policy="standard",
            components=[
                {
                    "observed_code": EMERGENCY_CODE,
                    "observed_name": EMERGENCY_SECTOR,
                }
            ],
        ),
        _group_spec(
            stable_key="NAO-TARIFADO",
            display_name="Setor nao tarifado",
            calculation_status=OccupancyCalculationStatus.UNRATED,
            official_capacity=None,
            occupied_count=None,
            occupancy_percentage=None,
            exceeded_by=None,
            official_availability=None,
            calculation_policy="unrated",
            components=[
                {
                    "observed_code": UNRATED_CODE,
                    "observed_name": UNRATED_SECTOR,
                }
            ],
        ),
    ]


def _build_catalog() -> CapacityCatalogVersion:
    """Persist the synthetic catalog of the closing measurement."""
    version = CapacityCatalogVersion.objects.create(
        effective_from=date(2026, 1, 1),
        source_reference="synthetic DSRS-S4 catalog",
        source_sha256="f" * 64,
        schema_version="3.0",
        algorithm_version="occupancy-v5",
    )
    _catalog_group(
        version,
        stable_key="GERAL",
        display_name="Gerais",
        official_capacity=40,
        calculation_policy="standard",
        members=[(GERAL_CODE, SECTOR_NAMES[GERAL_CODE])],
    )
    _catalog_group(
        version,
        stable_key="EMERGENCIA",
        display_name="Emergencia",
        official_capacity=8,
        calculation_policy="standard",
        members=[(EMERGENCY_CODE, EMERGENCY_SECTOR)],
    )
    _catalog_group(
        version,
        stable_key="NAO-TARIFADO",
        display_name="Setor nao tarifado",
        official_capacity=None,
        calculation_policy="unrated",
        members=[(UNRATED_CODE, UNRATED_SECTOR)],
    )
    return version


def _catalog_group(
    catalog: CapacityCatalogVersion,
    *,
    stable_key: str,
    display_name: str,
    official_capacity: int | None,
    calculation_policy: str,
    members: list[tuple[str, str]],
) -> CapacityGroupDefinition:
    group = CapacityGroupDefinition.objects.create(
        catalog=catalog,
        stable_key=stable_key,
        display_name=display_name,
        official_capacity=official_capacity,
        calculation_policy=calculation_policy,
    )
    for code, configured_name in members:
        CapacitySectorMembership.objects.create(
            catalog=catalog,
            group=group,
            source_code=code,
            configured_source_name=configured_name,
            age_selector="all",
        )
    return group


def _make_run(*, started_at: datetime, finished_at: datetime) -> IngestionRun:
    """Create a succeeded census extraction run with explicit instants."""
    run = IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
    )
    IngestionRun.objects.filter(pk=run.pk).update(
        started_at=started_at,
        finished_at=finished_at,
    )
    run.refresh_from_db()
    return run


def _persist_photograph(
    *, run: IngestionRun, captured_at: datetime, lines: list[_CensusLine]
) -> None:
    CensusSnapshot.objects.bulk_create(
        [
            CensusSnapshot(
                captured_at=captured_at,
                ingestion_run=run,
                setor=line.sector_name,
                setor_codigo=line.code,
                leito=line.bed,
                prontuario=line.record,
                nome=line.name,
                especialidade=line.specialty,
                origem=line.origem,
                bed_status=line.status,
                age_band=line.age_band,
            )
            for line in lines
        ]
    )


def _measurement(
    *,
    run: IngestionRun,
    captured_at: datetime,
    catalog: CapacityCatalogVersion,
    groups: list[dict[str, object]] | None = None,
) -> OccupancyMeasurement:
    """Persist the exact official measurement evidence of ``run``."""
    measurement = OccupancyMeasurement.objects.create(
        census_run=run,
        catalog=catalog,
        captured_at=captured_at,
        local_date=DAY,
        algorithm_version="occupancy-v5",
        observed_sector_count=43,
        capacity_covered_sector_count=2,
        calculable_sector_count=2,
        known_capacity=48,
        calculable_capacity=48,
        occupied_for_rate=1,
        exceeded_by=0,
    )
    OccupancyGroupMeasurement.objects.bulk_create(
        [
            OccupancyGroupMeasurement(measurement=measurement, **spec)
            for spec in (groups if groups is not None else _group_specs())
        ]
    )
    return measurement


def _accepted_census(
    *,
    catalog: CapacityCatalogVersion,
    started_at: datetime,
    finished_at: datetime,
    lines: list[_CensusLine],
    groups: list[dict[str, object]] | None = None,
) -> IngestionRun:
    """Create one run satisfying every accepted-census rule."""
    run = _make_run(started_at=started_at, finished_at=finished_at)
    _persist_photograph(run=run, captured_at=finished_at, lines=lines)
    _measurement(run=run, captured_at=finished_at, catalog=catalog, groups=groups)
    return run


def _chain(
    catalog: CapacityCatalogVersion,
    *,
    anchor: list[_CensusLine] | None = None,
    opening: list[_CensusLine] | None = None,
    interior: list[_CensusLine] | None = None,
    closing: list[_CensusLine] | None = None,
) -> dict[str, IngestionRun]:
    """Create the accepted photographs ``DAY`` requested by one test.

    ``None`` omits a photograph entirely; an empty list creates it without
    occupied identified rows.
    """
    runs: dict[str, IngestionRun] = {}
    if anchor is not None:
        runs["anchor"] = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 21, 0),
            finished_at=ANCHOR_AT,
            lines=_base_lines() + anchor,
        )
    if opening is not None:
        runs["opening"] = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=OPENING_AT,
            lines=_base_lines() + opening,
        )
    if interior is not None:
        runs["interior"] = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 12, 0),
            finished_at=INTERIOR_AT,
            lines=_base_lines() + interior,
        )
    if closing is not None:
        runs["closing"] = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 21, 0),
            finished_at=CLOSING_AT,
            lines=_base_lines() + closing,
        )
    return runs


def _death(
    *,
    record: str = PATIENT_RECORD,
    name: str = PATIENT_NAME,
    obito_em: datetime | None = None,
    data_obito: str = "",
    reference_date: date = DAY,
) -> DeathRecord:
    """Persist one synthetic death evidence row.

    ``obito_em`` is the exact clinical instant the source provided; a row
    carrying only ``data_obito`` is date-only evidence, exactly like the
    extraction writes it.
    """
    return DeathRecord.objects.create(
        date=reference_date,
        prontuario=record,
        nome=name,
        data_obito=data_obito,
        obito_em=obito_em,
    )


def _discharge(
    *,
    record: str = PATIENT_RECORD,
    name: str = PATIENT_NAME,
    saida_em: datetime | None = None,
    alta_em: datetime | None = None,
    data_internacao: str = "01/09/2026",
) -> DischargeRecord:
    """Persist one synthetic discharge evidence row."""
    return DischargeRecord.objects.create(
        prontuario=record,
        nome=name,
        saida_em=saida_em,
        alta_em=alta_em,
        data_internacao=data_internacao,
    )


def _materialize(
    *,
    policy: OriginPolicy = DEFAULT_ORIGIN_POLICY,
):
    """Materialize the revision of ``DAY`` under ``policy``."""
    return materialize_daily_statistics(
        local_date=DAY,
        activation_date=ACTIVATION,
        origin_policy=policy,
    )


def _report_of(
    *,
    policy: OriginPolicy = DEFAULT_ORIGIN_POLICY,
) -> DailyStatisticsReport:
    """Materialize ``DAY`` and return the ready revision."""
    return _materialize(policy=policy).report


def _events(report: DailyStatisticsReport, record: str) -> list[DailyStatisticsEvent]:
    """Every event of ``record`` in revision order."""
    return list(report.events.filter(record=record).order_by("pk"))


def _single_event(report: DailyStatisticsReport, record: str) -> DailyStatisticsEvent:
    """The one logical event of ``record``, asserting it is not duplicated."""
    events = _events(report, record)
    assert len(events) == 1, f"expected exactly one event for {record}: {events}"
    return events[0]


def _event_of_kind(
    report: DailyStatisticsReport,
    record: str,
    kind: str,
) -> DailyStatisticsEvent:
    """The one event of ``record`` carrying ``kind``."""
    events = list(report.events.filter(record=record, kind=kind))
    assert len(events) == 1, f"expected one {kind} event for {record}: {events}"
    return events[0]


@pytest.fixture
def catalog(db) -> CapacityCatalogVersion:
    """Synthetic historical catalog of the closing measurement."""
    return _build_catalog()


# ---------------------------------------------------------------------------
# R2 - clinical time versus detection for deaths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeathClassification:
    """R2: exact and date-only death evidence without a synthesized hour."""

    def test_exact_death_keeps_the_clinical_instant_and_separate_detection(
        self, catalog
    ):
        _chain(
            catalog,
            anchor=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(obito_em=_bahia(DAY, 18, 0), data_obito="15/09/2026 18:00:00")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.occurred_at == _bahia(DAY, 18, 0)
        assert event.occurred_on is None
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == CLOSING_AT
        assert event.detected_at != event.occurred_at
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "GERAL"
        assert event.destination_sector is None
        assert (
            event.sector_attribution
            == DailyStatisticsSectorAttribution.INFERRED_LAST_CENSUS
        )
        assert (
            exit_event_label(
                kind=event.kind,
                destination_sector_id=event.destination_sector_id,
            )
            is None
        )

    def test_date_only_death_keeps_only_the_clinical_date(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(data_obito="15/09/2026")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.occurred_at is None
        assert event.occurred_on == DAY
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == CLOSING_AT

    def test_date_only_death_of_the_previous_day_matches_the_overnight_interval(
        self, catalog
    ):
        _chain(
            catalog,
            anchor=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            opening=[],
            closing=[],
        )
        _death(data_obito="14/09/2026")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.occurred_on == PREVIOUS_DAY
        assert event.occurred_at is None
        assert event.detected_not_before == ANCHOR_AT
        assert event.detected_at == OPENING_AT

    def test_date_only_death_outside_the_covered_dates_does_not_close_the_episode(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        # The disappearance interval covers only 15/09 locally, so a source
        # date outside it cannot explain this episode.
        _death(data_obito="14/09/2026")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE
        assert event.occurred_at is None
        assert event.occurred_on is None

    def test_multiple_death_evidence_uses_the_oldest_clinical_moment(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(obito_em=_bahia(DAY, 18, 0), data_obito="15/09/2026 18:00:00")
        _death(obito_em=_bahia(DAY, 9, 0), data_obito="15/09/2026 09:00:00")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.occurred_at == _bahia(DAY, 9, 0)

    def test_exact_death_at_the_previous_photograph_instant_is_not_matched(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        # The detection interval is half-open at its start, so an instant the
        # previous photograph already contained cannot explain this episode.
        _death(obito_em=OPENING_AT, data_obito="15/09/2026 00:30:00")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE
        assert event.occurred_at is None


# ---------------------------------------------------------------------------
# R3 - effective exit and unclassified departure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDischargeClassification:
    """R3: ``saida_em`` closes the episode; ``alta_em`` alone never does."""

    def test_effective_exit_matches_saida_em_and_keeps_it_as_clinical_instant(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _discharge(
            alta_em=_bahia(DAY, 20, 0),
            saida_em=_bahia(DAY, 17, 0),
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.HOSPITAL_DISCHARGE
        assert event.occurred_at == _bahia(DAY, 17, 0)
        assert event.occurred_on is None
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == CLOSING_AT
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "GERAL"

    def test_alta_em_alone_never_closes_the_episode(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _discharge(alta_em=_bahia(DAY, 20, 0))

        report = _report_of()

        assert not report.events.filter(
            record=PATIENT_RECORD,
            kind=DailyStatisticsEventKind.HOSPITAL_DISCHARGE,
        ).exists()
        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE

    def test_absence_without_evidence_is_an_unidentified_destination_exit(
        self, catalog
    ):
        _chain(
            catalog,
            anchor=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            opening=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE
        assert event.occurred_at is None
        assert event.occurred_on is None
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "EMERGENCIA"
        assert event.destination_sector is None
        assert event.origin_nature == "unknown"
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == CLOSING_AT
        assert (
            exit_event_label(
                kind=event.kind,
                destination_sector_id=event.destination_sector_id,
            )
            == EXIT_LABEL_UNIDENTIFIED_DESTINATION
        )


# ---------------------------------------------------------------------------
# R1 - exit precedence is global to the episode
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExitPrecedence:
    """R1: death > effective discharge > transfer > unclassified departure."""

    def test_death_wins_over_effective_discharge_without_double_counting(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(obito_em=_bahia(DAY, 8, 0), data_obito="15/09/2026 08:00:00")
        _discharge(saida_em=_bahia(DAY, 17, 0))

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.occurred_at == _bahia(DAY, 8, 0)
        assert not report.events.filter(
            record=PATIENT_RECORD,
            kind=DailyStatisticsEventKind.HOSPITAL_DISCHARGE,
        ).exists()

    def test_death_wins_over_a_later_reappearance(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )
        _death(obito_em=_bahia(DAY, 6, 0), data_obito="15/09/2026 06:00:00")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.occurred_at == _bahia(DAY, 6, 0)
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == INTERIOR_AT
        assert not report.events.filter(
            record=PATIENT_RECORD,
            kind=DailyStatisticsEventKind.INTERNAL_TRANSFER,
        ).exists()

    def test_effective_discharge_wins_over_a_later_reappearance(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )
        _discharge(saida_em=_bahia(DAY, 6, 0))

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.HOSPITAL_DISCHARGE
        assert event.occurred_at == _bahia(DAY, 6, 0)
        assert not report.events.filter(
            record=PATIENT_RECORD,
            kind=DailyStatisticsEventKind.INTERNAL_TRANSFER,
        ).exists()

    def test_reappearance_without_evidence_is_not_an_unclassified_departure(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.origin_sector is None
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "EMERGENCIA"
        assert event.detected_not_before == INTERIOR_AT
        assert event.detected_at == CLOSING_AT
        assert (
            event.sector_attribution == DailyStatisticsSectorAttribution.OBSERVED
        )
        assert not report.events.filter(
            record=PATIENT_RECORD,
            kind=DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE,
        ).exists()


# ---------------------------------------------------------------------------
# R4 - sector attribution of an exit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorAttribution:
    """R4: inferred last census sector, or explicitly unknown."""

    def test_exit_uses_the_last_census_sector_and_records_inferred_attribution(
        self, catalog
    ):
        _chain(
            catalog,
            anchor=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            opening=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(data_obito="15/09/2026")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "EMERGENCIA"
        assert (
            event.sector_attribution
            == DailyStatisticsSectorAttribution.INFERRED_LAST_CENSUS
        )

    def test_exit_without_unambiguous_prior_position_keeps_unknown_sector(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[],
        )
        _death(obito_em=_bahia(DAY, 6, 0), data_obito="15/09/2026 06:00:00")

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.origin_sector is None
        assert event.destination_sector is None
        assert event.sector_attribution == DailyStatisticsSectorAttribution.UNKNOWN
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json

    def test_exit_keeps_the_last_resolved_sector_of_the_chain(
        self, catalog
    ):
        # The anchor resolved the patient to ``GERAL`` and the opening
        # photograph observed the same record under a grouping that does not
        # belong to the catalog. The exit must still fall back to the last
        # unambiguous prior census position instead of staying unknown.
        _chain(
            catalog,
            anchor=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            opening=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "GERAL"
        assert event.destination_sector is None
        assert (
            event.sector_attribution
            == DailyStatisticsSectorAttribution.INFERRED_LAST_CENSUS
        )

    def test_census_event_keeps_the_observed_sector_attribution(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                )
            ],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                )
            ],
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.destination_sector is not None
        assert (
            event.sector_attribution == DailyStatisticsSectorAttribution.OBSERVED
        )


# ---------------------------------------------------------------------------
# R5 - transfer confirmation from the census sequence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTransferConfirmation:
    """R5: exit -> gap -> reappearance, with or without a resolved grouping."""

    def test_reappearance_without_resolved_grouping_confirms_transfer_without_destination(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "GERAL"
        assert event.destination_sector is None
        assert event.occurred_at is None
        assert event.occurred_on is None
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == INTERIOR_AT
        assert (
            event.sector_attribution
            == DailyStatisticsSectorAttribution.INFERRED_LAST_CENSUS
        )
        assert (
            exit_event_label(
                kind=event.kind,
                destination_sector_id=event.destination_sector_id,
            )
            == TRANSFER_LABEL_UNIDENTIFIED_DESTINATION
        )

    def test_resolved_reappearance_keeps_the_single_s3_fact(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _report_of()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.origin_sector is None
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "EMERGENCIA"
        assert event.detected_not_before == INTERIOR_AT
        assert event.detected_at == CLOSING_AT
        assert not report.events.filter(
            record=PATIENT_RECORD,
            kind=DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE,
        ).exists()

    def test_unresolved_grouping_keeps_the_quality_code_without_a_transfer(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[],
            closing=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _report_of()

        assert _events(report, PATIENT_RECORD) == []
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json

    def test_conflicting_identity_is_never_an_exit(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                ),
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                ),
            ],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _report_of()

        # A photograph observing the same record twice proves no departure: the
        # record is still inside the hospital, so no exit is invented.
        assert _events(report, PATIENT_RECORD) == []
        assert QUALITY_AMBIGUOUS_PATIENT_IDENTITY in report.quality_warnings_json


# ---------------------------------------------------------------------------
# R6/R7 - automatic revisions and untouched clinical sources
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutomaticExitRevision:
    """R6/R7: idempotency and late-evidence revisions."""

    def test_rebuilding_the_same_exit_evidence_is_a_no_op(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(data_obito="15/09/2026")

        first = _materialize()
        second = _materialize()

        assert second.created is False
        assert second.report.pk == first.report.pk
        assert DailyStatisticsReport.objects.count() == 1
        assert _events(first.report, PATIENT_RECORD)[0].kind == (
            DailyStatisticsEventKind.DEATH
        )

    def test_late_death_evidence_publishes_a_new_current_revision(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        first = _materialize()
        assert _events(first.report, PATIENT_RECORD)[0].kind == (
            DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE
        )
        closing_run_id = first.report.closing_run_id
        measurement_id = first.report.measurement_id
        patients = list(first.report.patients.values_list("census_snapshot_id"))

        # Late clinical evidence arrives after the first materialization.
        _death(obito_em=_bahia(DAY, 10, 0), data_obito="15/09/2026 10:00:00")

        second = _materialize()

        assert second.created is True
        assert second.report.revision == first.report.revision + 1
        first.report.refresh_from_db()
        assert first.report.status == DailyStatisticsReportStatus.SUPERSEDED
        assert second.report.status == DailyStatisticsReportStatus.READY
        assert DailyStatisticsReport.objects.filter(
            local_date=DAY,
            status=DailyStatisticsReportStatus.READY,
        ).count() == 1
        # R7: the closing photograph, its measurement and the nominal closing
        # roster stay pinned to the same census close.
        assert second.report.closing_run_id == closing_run_id
        assert second.report.measurement_id == measurement_id
        assert (
            list(second.report.patients.values_list("census_snapshot_id"))
            == patients
        )
        revised = _events(second.report, PATIENT_RECORD)[0]
        assert revised.kind == DailyStatisticsEventKind.DEATH
        assert revised.occurred_at == _bahia(DAY, 10, 0)
        # The former revision keeps its own former classification.
        assert _events(first.report, PATIENT_RECORD)[0].kind == (
            DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE
        )

    def test_corrected_clinical_instant_publishes_a_new_current_revision(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        death = _death(
            obito_em=_bahia(DAY, 10, 0),
            data_obito="15/09/2026 10:00:00",
        )
        first = _materialize()
        assert _events(first.report, PATIENT_RECORD)[0].occurred_at == _bahia(
            DAY, 10, 0
        )

        DeathRecord.objects.filter(pk=death.pk).update(
            obito_em=_bahia(DAY, 11, 0),
            data_obito="15/09/2026 11:00:00",
        )

        second = _materialize()

        assert second.created is True
        assert second.report.revision == first.report.revision + 1
        assert _events(second.report, PATIENT_RECORD)[0].occurred_at == _bahia(
            DAY, 11, 0
        )

    def test_materialization_never_mutates_clinical_sources(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        _death(data_obito="15/09/2026")
        _discharge(saida_em=_bahia(DAY, 17, 0))
        deaths = list(DeathRecord.objects.values())
        discharges = list(DischargeRecord.objects.values())
        snapshots = list(CensusSnapshot.objects.values())

        _materialize()

        assert list(DeathRecord.objects.values()) == deaths
        assert list(DischargeRecord.objects.values()) == discharges
        assert list(CensusSnapshot.objects.values()) == snapshots
        assert Admission.objects.count() == 0
        assert Patient.objects.count() == 0


# ---------------------------------------------------------------------------
# Third round - inspectable provenance of the chosen clinical evidence row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventEvidenceProvenance:
    """The chosen clinical evidence row remains inspectable on the event.

    The fingerprint already covers the chosen source kind and primary key, but
    a hash cannot be inspected: the event persists both as nullable scalar
    columns. An exit explained by persisted clinical evidence keeps them; a
    fact only the census photographs proved keeps both null.
    """

    def test_death_event_persists_the_chosen_evidence_row(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        death = _death(
            obito_em=_bahia(DAY, 18, 0),
            data_obito="15/09/2026 18:00:00",
        )

        event = _single_event(_report_of(), PATIENT_RECORD)

        assert event.kind == DailyStatisticsEventKind.DEATH
        assert event.source_kind == DEATH_EVIDENCE_KIND
        assert event.source_pk == death.pk

    def test_multiple_death_evidence_persists_the_provenance_of_the_chosen_row(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        chosen = _death(
            obito_em=_bahia(DAY, 9, 0),
            data_obito="15/09/2026 09:00:00",
        )
        _death(obito_em=_bahia(DAY, 18, 0), data_obito="15/09/2026 18:00:00")

        event = _single_event(_report_of(), PATIENT_RECORD)

        assert event.occurred_at == _bahia(DAY, 9, 0)
        assert event.source_kind == DEATH_EVIDENCE_KIND
        assert event.source_pk == chosen.pk

    def test_date_only_death_persists_the_evidence_row_without_an_hour(
        self, catalog
    ):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        death = _death(data_obito="15/09/2026")

        event = _single_event(_report_of(), PATIENT_RECORD)

        assert event.occurred_at is None
        assert event.occurred_on == DAY
        assert event.source_kind == DEATH_EVIDENCE_KIND
        assert event.source_pk == death.pk

    def test_effective_exit_persists_the_discharge_evidence_row(self, catalog):
        _chain(
            catalog,
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[],
        )
        discharge = _discharge(
            alta_em=_bahia(DAY, 20, 0),
            saida_em=_bahia(DAY, 17, 0),
        )

        event = _single_event(_report_of(), PATIENT_RECORD)

        assert event.kind == DailyStatisticsEventKind.HOSPITAL_DISCHARGE
        assert event.source_kind == DISCHARGE_EVIDENCE_KIND
        assert event.source_pk == discharge.pk

    def test_census_only_events_keep_null_evidence_provenance(self, catalog):
        entry_record = "7001"
        departure_record = "7002"
        policy = OriginPolicy(
            version="provenance-test-v1",
            external=frozenset({EXTERNAL_ORIGIN}),
        )
        _chain(
            catalog,
            anchor=[],
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=entry_record,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                ),
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=departure_record,
                    name="PACIENTE SINTETICO DOIS",
                ),
            ],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=entry_record,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                )
            ],
        )

        report = _report_of(policy=policy)

        entry = _event_of_kind(
            report,
            entry_record,
            DailyStatisticsEventKind.HOSPITAL_ADMISSION,
        )
        assert entry.source_kind is None
        assert entry.source_pk is None
        departure = _event_of_kind(
            report,
            departure_record,
            DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE,
        )
        assert departure.source_kind is None
        assert departure.source_pk is None
