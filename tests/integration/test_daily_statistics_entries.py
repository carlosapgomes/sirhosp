"""DSRS-S3 integration tests: detected entries and internal transfers.

Covers the vertical slice requirements:

- R1: an identified patient absent from the anchor photograph and present in a
  later one with an origin classified as external produces a hospital
  admission;
- R2: emergency, operating room, monitored and unmonitored hospital origins
  produce an internal transfer, an unclassified origin produces
  ``Entrada no setor — origem não identificada``, and a confirmed internal
  transfer without an identifiable origin produces ``Transferência interna —
  origem não identificada``;
- R3: a sector change is one logical event carrying origin and destination,
  read as the origin's exit and as the destination's entry without duplicating
  the fact;
- R4: a bed-only change inside the same official grouping produces no sector
  event;
- R5: absent or conflicting patient identity and an unresolvable official
  grouping fail closed and leave explicit quality, and neither ambiguity is
  ever resolved by a later photograph;
- R6: without a clinical instant the event keeps ``detected_not_before`` and
  ``detected_at`` and never synthesizes an hour;
- R7: natural bed ordering keeps present beds first and uses name and record as
  tie-breakers.

Everything here uses synthetic runs, sectors, beds, origin values and patients;
no real extraction data, no production access and no backfill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, transaction

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
from apps.ingestion.models import IngestionRun
from apps.statistics_reports.events import (
    ENTRY_LABEL_UNIDENTIFIED_ORIGIN,
    QUALITY_AMBIGUOUS_PATIENT_IDENTITY,
    QUALITY_AMBIGUOUS_SECTOR_MAPPING,
    TRANSFER_LABEL_UNIDENTIFIED_ORIGIN,
    entry_event_label,
    natural_bed_order_key,
)
from apps.statistics_reports.materialization import (
    materialize_daily_statistics,
)
from apps.statistics_reports.models import (
    DailyStatisticsEvent,
    DailyStatisticsEventKind,
    DailyStatisticsReport,
)
from apps.statistics_reports.origin_policy import (
    DEFAULT_ORIGIN_POLICY,
    ORIGIN_POLICY_VERSION,
    OriginNature,
    OriginPolicy,
    OriginPolicyError,
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

# Synthetic origin values: the declared policy keeps every real source value
# unclassified until it is characterized before activation, so tests supply
# their own data-driven mapping instead of asserting real codes.
EXTERNAL_ORIGIN = "AMBULATORIO EXTERNO SINTETICO"
UNCLASSIFIED_ORIGIN = "ORIGEM NAO CARACTERIZADA"
INTERNAL_ORIGINS = (
    "EMERGENCIA SINTETICA",
    "CENTRO CIRURGICO SINTETICO",
    "SETOR MONITORADO SINTETICO",
    "SETOR NAO MONITORADO SINTETICO",
)

PATIENT_RECORD = "7001"
PATIENT_NAME = "PACIENTE SINTETICO UM"
CORRECTED_NAME = "PACIENTE SINTETICO UM CORRIGIDO"
ANCHOR_RECORD = "7002"
ANCHOR_NAME = "PACIENTE SINTETICO DOIS"


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
        return self.sector or SECTOR_NAMES.get(self.code, f"SETOR SINTETICO {self.code}")


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


def _policy(
    *,
    external: tuple[str, ...] = (),
    hospital_internal: tuple[str, ...] = (),
) -> OriginPolicy:
    """Declared origin policy carrying the synthetic values of one test."""
    return OriginPolicy(
        version=ORIGIN_POLICY_VERSION,
        external=frozenset(external),
        hospital_internal=frozenset(hospital_internal),
    )


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
                {"observed_code": GERAL_CODE, "observed_name": SECTOR_NAMES[GERAL_CODE]},
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
                {"observed_code": EMERGENCY_CODE, "observed_name": EMERGENCY_SECTOR}
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
                {"observed_code": UNRATED_CODE, "observed_name": UNRATED_SECTOR}
            ],
        ),
    ]


def _build_catalog() -> CapacityCatalogVersion:
    """Persist the synthetic catalog of the closing measurement."""
    version = CapacityCatalogVersion.objects.create(
        effective_from=date(2026, 1, 1),
        source_reference="synthetic DSRS-S3 catalog",
        source_sha256="e" * 64,
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


def _materialize(
    *,
    policy: OriginPolicy = DEFAULT_ORIGIN_POLICY,
) -> DailyStatisticsReport:
    """Materialize the ready revision of ``DAY`` under ``policy``."""
    return materialize_daily_statistics(
        local_date=DAY,
        activation_date=ACTIVATION,
        origin_policy=policy,
    ).report


def _single_event(report: DailyStatisticsReport, record: str) -> DailyStatisticsEvent:
    """The one logical event of ``record``, asserting it is not duplicated."""
    events = list(report.events.filter(record=record))
    assert len(events) == 1, f"expected exactly one event for {record}: {events}"
    return events[0]


def _assert_no_sector_event(report: DailyStatisticsReport, record: str) -> None:
    """No sector event may exist for ``record``."""
    assert not report.events.filter(record=record).exists()


@pytest.fixture
def catalog(db) -> CapacityCatalogVersion:
    """Synthetic historical catalog of the closing measurement."""
    return _build_catalog()


# ---------------------------------------------------------------------------
# R1 - external origin produces a hospital admission
# ---------------------------------------------------------------------------


class TestDeclaredOriginPolicy:
    """R1/R2: the origin mapping is versioned data, not ad hoc string checks."""

    def test_declared_policy_classifies_no_source_value(self):
        assert DEFAULT_ORIGIN_POLICY.version == ORIGIN_POLICY_VERSION
        assert DEFAULT_ORIGIN_POLICY.classify(UNCLASSIFIED_ORIGIN) is None
        assert DEFAULT_ORIGIN_POLICY.classify(EXTERNAL_ORIGIN) is None

    def test_classification_ignores_case_and_inner_spacing(self):
        policy = _policy(external=(EXTERNAL_ORIGIN,))

        assert (
            policy.classify(f"  {EXTERNAL_ORIGIN.lower()}  ")
            == OriginNature.EXTERNAL
        )
        assert policy.classify("   ") is None

    def test_value_declared_in_both_natures_fails_closed(self):
        with pytest.raises(OriginPolicyError):
            OriginPolicy(
                version=ORIGIN_POLICY_VERSION,
                external=frozenset({EXTERNAL_ORIGIN}),
                hospital_internal=frozenset({EXTERNAL_ORIGIN}),
            )

    def test_unnormalized_declared_value_fails_closed(self):
        with pytest.raises(OriginPolicyError):
            OriginPolicy(
                version=ORIGIN_POLICY_VERSION,
                external=frozenset({"ambulatorio  externo"}),
            )


@pytest.mark.django_db
class TestExternalOriginEntry:
    """R1: absent in the anchor, present later with an external origin."""

    def test_external_origin_produces_hospital_admission(self, catalog):
        policy = _policy(external=(EXTERNAL_ORIGIN,))
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

        report = _materialize(policy=policy)

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.HOSPITAL_ADMISSION
        assert event.origin_nature == OriginNature.EXTERNAL
        assert event.origin_sector is None
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "GERAL"
        assert event.origin_value == EXTERNAL_ORIGIN
        assert event.origin_policy_version == ORIGIN_POLICY_VERSION
        assert entry_event_label(
            kind=event.kind, origin_sector_id=event.origin_sector_id
        ) is None

    def test_patient_absent_from_anchor_and_opening_stays_silent(self, catalog):
        policy = _policy(external=(EXTERNAL_ORIGIN,))
        _chain(
            catalog,
            anchor=[],
            opening=[],
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

        report = _materialize(policy=policy)

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.HOSPITAL_ADMISSION
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == CLOSING_AT

    def test_without_anchor_photograph_no_entry_is_invented(self, catalog):
        lines = [
            _occupied(
                code=GERAL_CODE,
                bed="900-A",
                record=PATIENT_RECORD,
                name=PATIENT_NAME,
                origem=EXTERNAL_ORIGIN,
            )
        ]
        _chain(
            catalog,
            opening=lines,
            closing=lines,
        )

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        _assert_no_sector_event(report, PATIENT_RECORD)


# ---------------------------------------------------------------------------
# R2 - institutional entry classification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInstitutionalEntryClassification:
    """R2: internal, unknown and confirmed-without-origin entries."""

    @pytest.mark.parametrize("origin_value", INTERNAL_ORIGINS)
    def test_hospital_origin_is_an_internal_transfer(self, catalog, origin_value):
        policy = _policy(hospital_internal=INTERNAL_ORIGINS)
        _chain(
            catalog,
            anchor=[],
            opening=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=origin_value,
                )
            ],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=origin_value,
                )
            ],
        )

        report = _materialize(policy=policy)

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.origin_nature == OriginNature.HOSPITAL_INTERNAL
        assert event.origin_sector is None
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "EMERGENCIA"
        assert entry_event_label(
            kind=event.kind, origin_sector_id=event.origin_sector_id
        ) == TRANSFER_LABEL_UNIDENTIFIED_ORIGIN

    def test_unclassified_origin_is_not_silently_an_admission(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=UNCLASSIFIED_ORIGIN,
                )
            ],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=UNCLASSIFIED_ORIGIN,
                )
            ],
        )

        report = _materialize()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_ENTRY
        assert event.origin_nature == OriginNature.UNKNOWN
        assert event.origin_sector is None
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "GERAL"
        assert entry_event_label(
            kind=event.kind, origin_sector_id=event.origin_sector_id
        ) == ENTRY_LABEL_UNIDENTIFIED_ORIGIN

    def test_absent_origin_value_is_unclassified(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
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

        report = _materialize()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.UNCLASSIFIED_ENTRY
        assert event.origin_value == ""

    def test_confirmed_transfer_without_identifiable_origin_keeps_destination(
        self, catalog
    ):
        _chain(
            catalog,
            anchor=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
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
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.origin_nature == OriginNature.HOSPITAL_INTERNAL
        assert event.origin_sector is None
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "GERAL"
        assert entry_event_label(
            kind=event.kind, origin_sector_id=event.origin_sector_id
        ) == TRANSFER_LABEL_UNIDENTIFIED_ORIGIN
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json


# ---------------------------------------------------------------------------
# R3 - one logical transfer fact
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorChangeIsOneEvent:
    """R3: a sector change is one event with both legs."""

    def test_sector_change_is_one_event_with_origin_and_destination(self, catalog):
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
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.origin_nature == OriginNature.HOSPITAL_INTERNAL
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "GERAL"
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "EMERGENCIA"
        assert event.detected_not_before == ANCHOR_AT
        assert event.detected_at == OPENING_AT

    def test_one_transfer_is_the_origin_exit_and_the_destination_entry(self, catalog):
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
                    code=UNRATED_CODE,
                    bed="950-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[
                _occupied(
                    code=UNRATED_CODE,
                    bed="950-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        exit_events = list(report.events.filter(origin_sector__stable_key="GERAL"))
        entry_events = list(
            report.events.filter(destination_sector__stable_key="NAO-TARIFADO")
        )
        assert len(exit_events) == 1
        assert len(entry_events) == 1
        assert exit_events[0].pk == entry_events[0].pk
        assert report.events.filter(record=PATIENT_RECORD).count() == 1


# ---------------------------------------------------------------------------
# R4 - bed-only change inside one grouping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBedChangeInsideGrouping:
    """R4: moving between beds of one official grouping is no sector event."""

    def test_bed_change_inside_the_same_grouping_creates_no_event(self, catalog):
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
                    code=GERAL_SECOND_CODE,
                    bed="901-C",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                )
            ],
        )

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.HOSPITAL_ADMISSION
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "GERAL"

    def test_stable_patient_of_the_anchor_keeps_the_day_silent(self, catalog):
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
                    bed="900-B",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[
                _occupied(
                    code=GERAL_SECOND_CODE,
                    bed="901-C",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        _assert_no_sector_event(report, PATIENT_RECORD)


# ---------------------------------------------------------------------------
# R5 - fail-closed identity and sector attribution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFailClosedAttribution:
    """R5: missing identity, conflicting identity and unresolved grouping."""

    def test_row_without_identity_fails_closed_with_quality(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-B",
                    record="",
                    name="PACIENTE SEM PRONTUARIO",
                )
            ],
        )

        report = _materialize()

        assert not report.events.exists()
        assert QUALITY_AMBIGUOUS_PATIENT_IDENTITY in report.quality_warnings_json

    def test_incomplete_row_colliding_with_valid_record_fails_closed(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                ),
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name="",
                ),
            ],
        )

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        # The same record is observed by a valid row and by an occupied row
        # whose identity is incomplete, so the record is unusable in this
        # photograph: it keeps the explicit quality and never becomes an
        # admission.
        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_PATIENT_IDENTITY in report.quality_warnings_json

    def test_operational_marker_row_creates_no_event(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[],
            closing=[
                _occupied(
                    code=GERAL_CODE,
                    bed="900-B",
                    record="222",
                    name="RESERVA INTERNA",
                )
            ],
        )

        report = _materialize()

        # An operational state label never was a patient, so the shared
        # identity contract excludes it without an identity ambiguity to
        # report.
        assert not report.events.exists()
        assert (
            QUALITY_AMBIGUOUS_PATIENT_IDENTITY not in report.quality_warnings_json
        )

    def test_conflicting_identity_fails_closed_with_quality(self, catalog):
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
                ),
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                ),
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

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_PATIENT_IDENTITY in report.quality_warnings_json

    def test_conflicting_identity_taints_a_later_reappearance_after_a_gap(
        self, catalog
    ):
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
                ),
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                ),
            ],
            interior=[],
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

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        # The contradiction is not resolved by a gap: an untrusted record can
        # never become an admission, an entry or a transfer later.
        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_PATIENT_IDENTITY in report.quality_warnings_json

    def test_unresolvable_destination_creates_no_event_with_quality(self, catalog):
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
            closing=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json

    def test_appearing_in_an_unresolvable_group_creates_no_event(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[],
            closing=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                    origem=EXTERNAL_ORIGIN,
                )
            ],
        )

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json

    def test_unchanged_unresolved_grouping_still_reports_quality(self, catalog):
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
            closing=[
                _occupied(
                    code=OUTSIDE_CATALOG_CODE,
                    bed="970-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        # An identified row without an official grouping is explicit quality
        # even when it never changes position between two photographs.
        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json

    def test_unresolved_grouping_taints_a_later_known_destination_after_a_gap(
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
                    code=GERAL_CODE,
                    bed="900-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        # The origin never resolved to an official grouping, so the later
        # arrival after a gap cannot be read as a transfer of unknown origin.
        _assert_no_sector_event(report, PATIENT_RECORD)
        assert QUALITY_AMBIGUOUS_SECTOR_MAPPING in report.quality_warnings_json


# ---------------------------------------------------------------------------
# R6 - clinical time versus detection interval
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDetectionInterval:
    """R6: the detected interval survives without a clinical hour."""

    def test_event_without_clinical_time_keeps_the_detection_interval(self, catalog):
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

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        event = _single_event(report, PATIENT_RECORD)
        assert event.occurred_at is None
        assert event.occurred_on is None
        assert event.detected_not_before == ANCHOR_AT
        assert event.detected_at == OPENING_AT
        assert event.detected_at > event.detected_not_before

    def test_interior_photograph_refines_the_detection_interval(self, catalog):
        _chain(
            catalog,
            anchor=[],
            opening=[],
            interior=[
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

        report = _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,)))

        event = _single_event(report, PATIENT_RECORD)
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == INTERIOR_AT

    def test_interior_photograph_detects_a_transfer_between_boundaries(self, catalog):
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
                    bed="900-B",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            interior=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
            closing=[
                _occupied(
                    code=EMERGENCY_CODE,
                    bed="940-A",
                    record=PATIENT_RECORD,
                    name=PATIENT_NAME,
                )
            ],
        )

        report = _materialize()

        event = _single_event(report, PATIENT_RECORD)
        assert event.kind == DailyStatisticsEventKind.INTERNAL_TRANSFER
        assert event.detected_not_before == OPENING_AT
        assert event.detected_at == INTERIOR_AT
        assert event.origin_sector is not None
        assert event.origin_sector.stable_key == "GERAL"
        assert event.destination_sector is not None
        assert event.destination_sector.stable_key == "EMERGENCIA"


# ---------------------------------------------------------------------------
# R7 - natural bed ordering
# ---------------------------------------------------------------------------


class TestBedNaturalOrdering:
    """R7: natural bed order with missing beds last and stable tie-breakers."""

    def test_numeric_and_alphanumeric_beds_follow_natural_order(self):
        rows = [
            ("10", "PACIENTE B", "2"),
            ("UTI02", "PACIENTE C", "3"),
            ("", "PACIENTE Z", "4"),
            ("2", "PACIENTE A", "1"),
            ("101A", "PACIENTE D", "5"),
            ("UTI10", "PACIENTE E", "6"),
        ]

        ordered = [
            bed
            for bed, *_ in sorted(
                rows,
                key=lambda row: natural_bed_order_key(
                    bed=row[0], name=row[1], record=row[2]
                ),
            )
        ]

        assert ordered == ["2", "10", "101A", "UTI02", "UTI10", ""]

    def test_missing_beds_come_last_ordered_by_name_and_record(self):
        rows = [
            ("", "PACIENTE B", "2"),
            ("", "PACIENTE A", "9"),
            ("", "PACIENTE A", "3"),
        ]

        ordered = [
            record
            for _, _, record in sorted(
                rows,
                key=lambda row: natural_bed_order_key(
                    bed=row[0], name=row[1], record=row[2]
                ),
            )
        ]

        assert ordered == ["3", "9", "2"]

    def test_name_case_and_spacing_do_not_change_the_order(self):
        rows = [
            ("", "  paciente  b ", "2"),
            ("", "PACIENTE A", "1"),
        ]

        ordered = [
            record
            for _, _, record in sorted(
                rows,
                key=lambda row: natural_bed_order_key(
                    bed=row[0], name=row[1], record=row[2]
                ),
            )
        ]

        assert ordered == ["1", "2"]


# ---------------------------------------------------------------------------
# Ledger identity and idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventLedgerIdentity:
    """The ledger keeps one durable row per detected fact."""

    def test_rebuilding_the_same_sources_keeps_one_event_row(self, catalog):
        policy = _policy(external=(EXTERNAL_ORIGIN,))
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

        first = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION, origin_policy=policy
        )
        second = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION, origin_policy=policy
        )

        assert second.created is False
        assert second.report.pk == first.report.pk
        assert DailyStatisticsReport.objects.count() == 1
        assert second.report.events.count() == 1

    def test_corrected_detecting_name_publishes_a_new_revision(self, catalog):
        policy = _policy(external=(EXTERNAL_ORIGIN,))
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
        first = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION, origin_policy=policy
        )
        detecting = _single_event(first.report, PATIENT_RECORD).census_snapshot
        assert detecting.captured_at == OPENING_AT

        CensusSnapshot.objects.filter(pk=detecting.pk).update(nome=CORRECTED_NAME)

        second = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION, origin_policy=policy
        )

        # The nominal name is a persisted event value: correcting it in the
        # detecting (non-closing) photograph publishes a new revision instead
        # of returning the former one as a no-op.
        assert second.created is True
        assert second.report.revision == first.report.revision + 1
        assert DailyStatisticsReport.objects.count() == 2
        assert _single_event(first.report, PATIENT_RECORD).name == PATIENT_NAME
        assert (
            _single_event(second.report, PATIENT_RECORD).name == CORRECTED_NAME
        )

    def test_schema_refuses_duplicate_event_fingerprint(self, catalog):
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
        event = _single_event(
            _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,))),
            PATIENT_RECORD,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyStatisticsEvent.objects.create(
                    report=event.report,
                    kind=event.kind,
                    origin_nature=event.origin_nature,
                    origin_value=event.origin_value,
                    origin_policy_version=event.origin_policy_version,
                    origin_sector=event.origin_sector,
                    destination_sector=event.destination_sector,
                    census_snapshot_id=event.census_snapshot_id,
                    record=event.record,
                    name=event.name,
                    bed=event.bed,
                    detected_not_before=event.detected_not_before,
                    detected_at=event.detected_at,
                    fingerprint=event.fingerprint,
                )

    def test_schema_refuses_event_without_any_endpoint(self, catalog):
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
            closing=[],
        )
        event = _single_event(
            _materialize(policy=_policy(external=(EXTERNAL_ORIGIN,))),
            PATIENT_RECORD,
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyStatisticsEvent.objects.create(
                    report=event.report,
                    kind=event.kind,
                    origin_nature=event.origin_nature,
                    origin_value=event.origin_value,
                    origin_policy_version=event.origin_policy_version,
                    origin_sector=None,
                    destination_sector=None,
                    census_snapshot_id=event.census_snapshot_id,
                    record=event.record,
                    name=event.name,
                    bed=event.bed,
                    detected_not_before=event.detected_not_before,
                    detected_at=event.detected_at,
                    fingerprint="f" * 64,
                )
