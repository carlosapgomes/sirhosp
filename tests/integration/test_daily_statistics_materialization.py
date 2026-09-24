"""DSRS-S2 integration tests: materialized daily statistics final photograph.

Covers the vertical slice requirements:

- R1: the persisted revision preserves Bahia local date, revision, status,
  anchor/opening/closing runs, exact measurement, catalog, algorithm,
  fingerprint and quality metadata;
- R2: every sector keeps its historical key/name and only copies metrics of
  the exact closing measurement, without recalculating capacity, occupancy,
  balance or excess;
- R3: patients are exactly the closing census rows, keeping provenance, bed,
  name, record and specialty;
- R4: repeating the same source fingerprint duplicates neither report, sector
  nor patient;
- R5: publication is atomic and at most one ready revision exists per date;
- R6: dates before the declared activation boundary are never materialized.

Everything here uses synthetic runs, sectors, beds and patients; no real
extraction data, no production access and no backfill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
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
from apps.census.occupancy import OccupancyMaterializationError
from apps.ingestion.models import IngestionRun
from apps.statistics_reports.materialization import (
    DateBeforeActivationError,
    IncompleteStatisticalDayError,
    materialize_daily_statistics,
)
from apps.statistics_reports.models import (
    DailyStatisticsPatient,
    DailyStatisticsReport,
    DailyStatisticsReportStatus,
    DailyStatisticsSector,
)
from apps.statistics_reports.selection import QUALITY_MISSING_ANCHOR

BAHIA_TZ = ZoneInfo("America/Bahia")

DAY = date(2026, 9, 15)
PREVIOUS_DAY = DAY - timedelta(days=1)
NEXT_DAY = DAY + timedelta(days=1)
ACTIVATION = date(2026, 9, 1)

# 38 generic synthetic sectors plus the 3A/obstetrics, unrated and unmapped
# sectors keep the photograph above the official census coverage minimum.
GENERIC_CODES = tuple(str(code) for code in range(900, 938))
OBSTETRIC_CODE = "654"
OBSTETRIC_NAME = "3A OBSTETRICIA CLINICA"
UNRATED_CODE = "950"
UNRATED_NAME = "SETOR SINTETICO 950"
UNMAPPED_CODE = "990"
UNMAPPED_NAME = "SETOR SEM CATALOGO"
UNMAPPED_BY_NAME = "SETOR SEM CODIGO"

CLOSING_RECORDS = ("111", "112", "4001", "4002", "4003", "5001", "6001")

PERCENT_QUANTUM = Decimal("0.01")


# ---------------------------------------------------------------------------
# Synthetic census helpers
# ---------------------------------------------------------------------------


def _bahia(day: date, hour: int, minute: int = 0) -> datetime:
    """Aware ``America/Bahia`` instant on ``day``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BAHIA_TZ)


@dataclass(frozen=True)
class _CensusLine:
    """One synthetic census row of a photograph."""

    code: str
    sector: str
    bed: str
    record: str = ""
    name: str = ""
    specialty: str = ""
    age_band: str = OccupancyAgeBand.NOT_APPLICABLE
    status: str = BedStatus.OCCUPIED


def _base_lines() -> list[_CensusLine]:
    """One non-occupied row per synthetic sector of the photograph."""
    lines = [
        _CensusLine(
            code=code,
            sector=f"SETOR SINTETICO {code}",
            bed=f"L{code}",
            status=BedStatus.EMPTY,
        )
        for code in GENERIC_CODES
    ]
    lines.extend(
        [
            _CensusLine(
                code=OBSTETRIC_CODE,
                sector=OBSTETRIC_NAME,
                bed="3A-VAGA",
                status=BedStatus.EMPTY,
            ),
            _CensusLine(
                code=UNRATED_CODE,
                sector=UNRATED_NAME,
                bed="950-VAGA",
                status=BedStatus.EMPTY,
            ),
            _CensusLine(
                code=UNMAPPED_CODE,
                sector=UNMAPPED_NAME,
                bed="990-VAGA",
                status=BedStatus.EMPTY,
            ),
        ]
    )
    return lines


def _closing_lines() -> list[_CensusLine]:
    """Occupied identified rows of the closing photograph."""
    return [
        _CensusLine(
            code="900",
            sector="SETOR SINTETICO 900",
            bed="900-A",
            record="111",
            name="PACIENTE GERAL UM",
            specialty="CLI",
        ),
        _CensusLine(
            code="901",
            sector="SETOR SINTETICO 901",
            bed="901-A",
            record="112",
            name="PACIENTE GERAL DOIS",
            specialty="CLI",
        ),
        _CensusLine(
            code=OBSTETRIC_CODE,
            sector=OBSTETRIC_NAME,
            bed="3A-01",
            record="4001",
            name="PACIENTE ADULTO 3A",
            specialty="OBS",
            age_band=OccupancyAgeBand.AGE_12_OR_OVER,
        ),
        _CensusLine(
            code=OBSTETRIC_CODE,
            sector=OBSTETRIC_NAME,
            bed="3A-02",
            record="4002",
            name="RN BEBE SINTETICO",
            specialty="PED",
            age_band=OccupancyAgeBand.UNKNOWN,
        ),
        _CensusLine(
            code=OBSTETRIC_CODE,
            sector=OBSTETRIC_NAME,
            bed="3A-03",
            record="4003",
            name="PACIENTE SEM IDADE",
            specialty="OBS",
            age_band=OccupancyAgeBand.UNKNOWN,
        ),
        _CensusLine(
            code=UNRATED_CODE,
            sector=UNRATED_NAME,
            bed="950-A",
            record="5001",
            name="PACIENTE NAO TARIFADO",
            specialty="CLI",
        ),
        _CensusLine(
            code=UNMAPPED_CODE,
            sector=UNMAPPED_NAME,
            bed="990-A",
            record="6001",
            name="PACIENTE SEM CATALOGO",
            specialty="CLI",
        ),
    ]


def _lines_with_patient(record: str) -> list[_CensusLine]:
    """A complete photograph carrying one out-of-window patient."""
    return _base_lines() + [
        _CensusLine(
            code="900",
            sector="SETOR SINTETICO 900",
            bed="900-Z",
            record=record,
            name=f"PACIENTE {record}",
            specialty="CLI",
        )
    ]


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
                setor=line.sector,
                setor_codigo=line.code,
                leito=line.bed,
                prontuario=line.record,
                nome=line.name,
                especialidade=line.specialty,
                bed_status=line.status,
                age_band=line.age_band,
            )
            for line in lines
        ]
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


def _default_group_specs() -> list[dict[str, object]]:
    """Persisted official groups of the synthetic closing measurement."""
    return [
        _group_spec(
            stable_key="GERAL",
            display_name="Gerais",
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=40,
            occupied_count=2,
            occupancy_percentage=(Decimal(2) / Decimal(40) * 100).quantize(
                PERCENT_QUANTUM
            ),
            exceeded_by=0,
            official_availability=38,
            calculation_policy="standard",
            components=[
                {"observed_code": "900", "observed_name": "SETOR SINTETICO 900"},
                {"observed_code": "901", "observed_name": "SETOR SINTETICO 901"},
            ],
        ),
        _group_spec(
            stable_key="OBST-3A-ADULTO",
            display_name="Enfermaria 3A - Adulto",
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=4,
            occupied_count=2,
            occupancy_percentage=Decimal("50.00"),
            exceeded_by=0,
            official_availability=2,
            calculation_policy="standard",
            components=[
                {
                    "observed_code": OBSTETRIC_CODE,
                    "observed_name": OBSTETRIC_NAME,
                    "age_selector": OccupancyAgeBand.AGE_12_OR_OVER,
                }
            ],
        ),
        _group_spec(
            stable_key="OBST-3A-INFANTIL",
            display_name="Enfermaria 3A - Infantil",
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=2,
            occupied_count=1,
            occupancy_percentage=Decimal("50.00"),
            exceeded_by=0,
            official_availability=1,
            calculation_policy="standard",
            components=[
                {
                    "observed_code": OBSTETRIC_CODE,
                    "observed_name": OBSTETRIC_NAME,
                    "age_selector": OccupancyAgeBand.UNDER_12,
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
                {"observed_code": UNRATED_CODE, "observed_name": UNRATED_NAME}
            ],
        ),
        _group_spec(
            stable_key="UNMAPPED-CODE-990",
            display_name=UNMAPPED_NAME,
            calculation_status=OccupancyCalculationStatus.UNMAPPED,
            official_capacity=None,
            occupied_count=None,
            occupancy_percentage=None,
            exceeded_by=None,
            official_availability=None,
            calculation_policy="",
            components=[
                {"observed_code": UNMAPPED_CODE, "observed_name": UNMAPPED_NAME}
            ],
        ),
        _group_spec(
            stable_key="UNMAPPED-NAME-SEM-CODIGO",
            display_name=UNMAPPED_BY_NAME,
            calculation_status=OccupancyCalculationStatus.UNMAPPED,
            official_capacity=None,
            occupied_count=None,
            occupancy_percentage=None,
            exceeded_by=None,
            official_availability=None,
            calculation_policy="",
            components=[
                {"observed_code": "", "observed_name": UNMAPPED_BY_NAME}
            ],
        ),
    ]


def _legacy_group_specs() -> list[dict[str, object]]:
    """Persisted groups of one ``occupancy-v2`` measurement of the same day.

    v2 counts a partitioned source code by each row's own age band, so the 3A
    values follow the one occupied row with a reliable band while the two
    unknown-band rows are counted in no official group (``age_partial``).
    """
    specs = _default_group_specs()
    specs[1] = _group_spec(
        stable_key="OBST-3A-ADULTO",
        display_name="Enfermaria 3A - Adulto",
        calculation_status=OccupancyCalculationStatus.CALCULATED,
        official_capacity=4,
        occupied_count=1,
        occupancy_percentage=Decimal("25.00"),
        exceeded_by=0,
        official_availability=3,
        calculation_policy="standard",
        components=[
            {
                "observed_code": OBSTETRIC_CODE,
                "observed_name": OBSTETRIC_NAME,
                "age_selector": OccupancyAgeBand.AGE_12_OR_OVER,
            }
        ],
    )
    specs[2] = _group_spec(
        stable_key="OBST-3A-INFANTIL",
        display_name="Enfermaria 3A - Infantil",
        calculation_status=OccupancyCalculationStatus.CALCULATED,
        official_capacity=2,
        occupied_count=0,
        occupancy_percentage=Decimal("0.00"),
        exceeded_by=0,
        official_availability=2,
        calculation_policy="standard",
        components=[
            {
                "observed_code": OBSTETRIC_CODE,
                "observed_name": OBSTETRIC_NAME,
                "age_selector": OccupancyAgeBand.UNDER_12,
            }
        ],
    )
    return specs


def _measurement(
    *,
    run: IngestionRun,
    captured_at: datetime,
    catalog: CapacityCatalogVersion,
    groups: list[dict[str, object]] | None = None,
    algorithm_version: str = "occupancy-v5",
) -> OccupancyMeasurement:
    """Persist the exact closing measurement evidence of ``run``."""
    measurement = OccupancyMeasurement.objects.create(
        census_run=run,
        catalog=catalog,
        captured_at=captured_at,
        local_date=DAY,
        algorithm_version=algorithm_version,
        observed_sector_count=41,
        capacity_covered_sector_count=3,
        calculable_sector_count=3,
        known_capacity=46,
        calculable_capacity=46,
        occupied_for_rate=5,
        exceeded_by=0,
    )
    OccupancyGroupMeasurement.objects.bulk_create(
        [
            OccupancyGroupMeasurement(measurement=measurement, **spec)
            for spec in (groups if groups is not None else _default_group_specs())
        ]
    )
    return measurement


def _accepted_census(
    *,
    catalog: CapacityCatalogVersion,
    started_at: datetime,
    finished_at: datetime,
    lines: list[_CensusLine] | None = None,
    groups: list[dict[str, object]] | None = None,
    algorithm_version: str = "occupancy-v5",
) -> IngestionRun:
    """Create one run satisfying every accepted-census rule."""
    run = _make_run(started_at=started_at, finished_at=finished_at)
    _persist_photograph(
        run=run,
        captured_at=finished_at,
        lines=lines if lines is not None else _base_lines() + _closing_lines(),
    )
    _measurement(
        run=run,
        captured_at=finished_at,
        catalog=catalog,
        groups=groups,
        algorithm_version=algorithm_version,
    )
    return run


def _anchor_census(catalog: CapacityCatalogVersion) -> IngestionRun:
    """Accepted census completed before the opening of ``DAY``."""
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(PREVIOUS_DAY, 21, 30),
        finished_at=_bahia(PREVIOUS_DAY, 22, 0),
        lines=_lines_with_patient("7001"),
    )


def _opening_census(catalog: CapacityCatalogVersion) -> IngestionRun:
    """Accepted first census completed inside the opening window of ``DAY``."""
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(PREVIOUS_DAY, 23, 30),
        finished_at=_bahia(DAY, 0, 30),
        lines=_lines_with_patient("7002"),
    )


def _closing_census(
    catalog: CapacityCatalogVersion,
    *,
    lines: list[_CensusLine] | None = None,
    groups: list[dict[str, object]] | None = None,
    algorithm_version: str = "occupancy-v5",
) -> IngestionRun:
    """Accepted closing census of ``DAY``."""
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(DAY, 21, 0),
        finished_at=_bahia(DAY, 21, 30),
        lines=lines,
        groups=groups,
        algorithm_version=algorithm_version,
    )


def _next_day_census(catalog: CapacityCatalogVersion) -> IngestionRun:
    """Accepted census of ``NEXT_DAY``, later than the closing photograph."""
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(NEXT_DAY, 8, 0),
        finished_at=_bahia(NEXT_DAY, 8, 30),
        lines=_lines_with_patient("7003"),
    )


def _full_day(
    catalog: CapacityCatalogVersion,
    *,
    lines: list[_CensusLine] | None = None,
    groups: list[dict[str, object]] | None = None,
    algorithm_version: str = "occupancy-v5",
) -> IngestionRun:
    """Anchor, opening and closing accepted censuses of ``DAY``."""
    _anchor_census(catalog)
    _opening_census(catalog)
    return _closing_census(
        catalog,
        lines=lines,
        groups=groups,
        algorithm_version=algorithm_version,
    )


def _late_patient(closing: IngestionRun, record: str) -> None:
    """Add one identified patient to the already persisted closing photo."""
    captured_at = closing.finished_at
    assert captured_at is not None
    CensusSnapshot.objects.create(
        captured_at=captured_at,
        ingestion_run=closing,
        setor="SETOR SINTETICO 900",
        setor_codigo="900",
        leito="900-LATE",
        prontuario=record,
        nome=f"PACIENTE {record}",
        especialidade="CLI",
        bed_status=BedStatus.OCCUPIED,
    )


def _revision_payload(report: DailyStatisticsReport, status: str) -> dict[str, object]:
    """Copy the provenance of ``report`` into another revision candidate."""
    return {
        "local_date": report.local_date,
        "status": status,
        "activation_date": report.activation_date,
        "anchor_run_id": report.anchor_run_id,
        "opening_run_id": report.opening_run_id,
        "closing_run_id": report.closing_run_id,
        "measurement_id": report.measurement_id,
        "catalog_id": report.catalog_id,
        "algorithm_version": report.algorithm_version,
        "source_fingerprint": report.source_fingerprint,
        "quality_warnings_json": report.quality_warnings_json,
    }


@pytest.fixture
def catalog(db) -> CapacityCatalogVersion:
    """Synthetic historical catalog partitioning the 3A obstetric code."""
    return _build_catalog(
        effective_from=date(2026, 1, 1),
        algorithm_version="occupancy-v5",
        source_reference="synthetic DSRS-S2 catalog",
        source_sha256="c" * 64,
    )


@pytest.fixture
def legacy_catalog(db) -> CapacityCatalogVersion:
    """Synthetic ``occupancy-v2`` catalog partitioning the 3A code."""
    return _build_catalog(
        effective_from=date(2026, 2, 1),
        algorithm_version="occupancy-v2",
        source_reference="synthetic DSRS-S2 legacy catalog",
        source_sha256="d" * 64,
    )


def _build_catalog(
    *,
    effective_from: date,
    algorithm_version: str,
    source_reference: str,
    source_sha256: str,
) -> CapacityCatalogVersion:
    """Persist the synthetic catalog shared by the v5 and legacy fixtures."""
    version = CapacityCatalogVersion.objects.create(
        effective_from=effective_from,
        source_reference=source_reference,
        source_sha256=source_sha256,
        schema_version="3.0",
        algorithm_version=algorithm_version,
    )
    _catalog_group(
        version,
        stable_key="GERAL",
        display_name="Gerais",
        official_capacity=40,
        calculation_policy="standard",
        members=[
            ("900", "SETOR SINTETICO 900", "all"),
            ("901", "SETOR SINTETICO 901", "all"),
        ],
    )
    _catalog_group(
        version,
        stable_key="OBST-3A-ADULTO",
        display_name="Enfermaria 3A - Adulto",
        official_capacity=4,
        calculation_policy="standard",
        members=[
            (OBSTETRIC_CODE, OBSTETRIC_NAME, OccupancyAgeBand.AGE_12_OR_OVER)
        ],
    )
    _catalog_group(
        version,
        stable_key="OBST-3A-INFANTIL",
        display_name="Enfermaria 3A - Infantil",
        official_capacity=2,
        calculation_policy="standard",
        members=[(OBSTETRIC_CODE, OBSTETRIC_NAME, OccupancyAgeBand.UNDER_12)],
    )
    _catalog_group(
        version,
        stable_key="NAO-TARIFADO",
        display_name="Setor nao tarifado",
        official_capacity=None,
        calculation_policy="unrated",
        members=[(UNRATED_CODE, UNRATED_NAME, "all")],
    )
    return version


def _catalog_group(
    catalog: CapacityCatalogVersion,
    *,
    stable_key: str,
    display_name: str,
    official_capacity: int | None,
    calculation_policy: str,
    members: list[tuple[str, str, str]],
) -> CapacityGroupDefinition:
    group = CapacityGroupDefinition.objects.create(
        catalog=catalog,
        stable_key=stable_key,
        display_name=display_name,
        official_capacity=official_capacity,
        calculation_policy=calculation_policy,
    )
    for code, configured_name, selector in members:
        CapacitySectorMembership.objects.create(
            catalog=catalog,
            group=group,
            source_code=code,
            configured_source_name=configured_name,
            age_selector=selector,
        )
    return group


# ---------------------------------------------------------------------------
# R1/R5 - persisted revision schema
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReportRevisionSchema:
    """R1: the revision preserves official provenance and quality metadata."""

    def test_report_persists_bahia_date_and_official_provenance(self, catalog):
        closing = _closing_census(catalog)
        opening = _opening_census(catalog)
        anchor = _anchor_census(catalog)

        outcome = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )

        report = outcome.report
        assert outcome.created is True
        assert report.local_date == DAY
        assert report.revision == 1
        assert report.status == DailyStatisticsReportStatus.READY
        assert report.activation_date == ACTIVATION
        assert report.opening_run_id == opening.pk
        assert report.closing_run_id == closing.pk
        assert report.anchor_run_id == anchor.pk
        assert report.measurement_id == closing.occupancy_measurement.pk
        assert report.catalog_id == catalog.pk
        assert report.algorithm_version == "occupancy-v5"
        assert len(report.source_fingerprint) == 64
        assert report.quality_warnings_json == []
        assert report.generated_at is not None

    def test_report_records_quality_warning_when_anchor_is_absent(self, catalog):
        _closing_census(catalog)
        _opening_census(catalog)

        outcome = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )

        assert outcome.report.quality_warnings_json == [QUALITY_MISSING_ANCHOR]

    def test_incomplete_day_is_refused_without_persisting(self, catalog):
        _closing_census(catalog)

        with pytest.raises(IncompleteStatisticalDayError):
            materialize_daily_statistics(
                local_date=DAY, activation_date=ACTIVATION
            )

        assert DailyStatisticsReport.objects.count() == 0

    def test_schema_allows_only_one_ready_revision_per_date(self, catalog):
        _full_day(catalog)
        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        with transaction.atomic():
            DailyStatisticsReport.objects.create(
                revision=2,
                **_revision_payload(report, DailyStatisticsReportStatus.SUPERSEDED),
            )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyStatisticsReport.objects.create(
                    revision=3,
                    **_revision_payload(
                        report, DailyStatisticsReportStatus.READY
                    ),
                )

    def test_schema_refuses_duplicate_date_revision(self, catalog):
        _full_day(catalog)
        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyStatisticsReport.objects.create(
                    revision=report.revision,
                    **_revision_payload(
                        report, DailyStatisticsReportStatus.SUPERSEDED
                    ),
                )

    def test_schema_refuses_non_positive_revision(self, catalog):
        _full_day(catalog)
        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyStatisticsReport.objects.create(
                    revision=0,
                    **_revision_payload(
                        report, DailyStatisticsReportStatus.SUPERSEDED
                    ),
                )

    def test_schema_refuses_revision_before_activation(self, catalog):
        _full_day(catalog)
        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report
        payload = _revision_payload(report, DailyStatisticsReportStatus.SUPERSEDED)
        payload["activation_date"] = NEXT_DAY

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DailyStatisticsReport.objects.create(revision=2, **payload)


# ---------------------------------------------------------------------------
# R2 - official closing sectors
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOfficialClosingSectors:
    """R2: sectors copy the exact measurement values without recalculation."""

    def test_sectors_are_the_official_groups_of_the_exact_measurement(
        self, catalog
    ):
        closing = _closing_census(catalog)
        _opening_census(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        measurement = closing.occupancy_measurement
        measured = {group.stable_key: group for group in measurement.groups.all()}
        persisted = {sector.stable_key: sector for sector in report.sectors.all()}
        assert set(persisted) == set(measured)
        for stable_key, group in measured.items():
            sector = persisted[stable_key]
            assert sector.display_name == group.display_name
            assert sector.calculation_status == group.calculation_status
            assert sector.calculation_policy == group.calculation_policy
            assert sector.official_capacity == group.official_capacity
            assert sector.occupied_count == group.occupied_count
            assert sector.occupancy_percentage == group.occupancy_percentage
            assert sector.exceeded_by == group.exceeded_by
            assert sector.official_availability == group.official_availability

    def test_sector_metrics_are_copied_and_never_recalculated(self, catalog):
        groups = _default_group_specs()
        groups[0] = _group_spec(
            stable_key="GERAL",
            display_name="Gerais",
            calculation_status=OccupancyCalculationStatus.CALCULATED,
            official_capacity=5,
            occupied_count=7,
            occupancy_percentage=Decimal("140.00"),
            exceeded_by=2,
            official_availability=0,
            calculation_policy="standard",
            components=[
                {"observed_code": "900", "observed_name": "SETOR SINTETICO 900"},
                {"observed_code": "901", "observed_name": "SETOR SINTETICO 901"},
            ],
        )
        _closing_census(catalog, groups=groups)
        _opening_census(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        geral = report.sectors.get(stable_key="GERAL")
        assert geral.official_capacity == 5
        assert geral.occupied_count == 7
        assert geral.occupancy_percentage == Decimal("140.00")
        assert geral.exceeded_by == 2
        assert geral.official_availability == 0
        # The closing photograph itself only carries two GERAL patients.
        assert report.patients.filter(sector=geral).count() == 2

    def test_partitioned_official_code_keeps_independent_sector_values(
        self, catalog
    ):
        _full_day(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        adulto = report.sectors.get(stable_key="OBST-3A-ADULTO")
        infantil = report.sectors.get(stable_key="OBST-3A-INFANTIL")
        assert adulto.pk != infantil.pk
        assert adulto.official_capacity == 4
        assert adulto.occupied_count == 2
        assert infantil.official_capacity == 2
        assert infantil.occupied_count == 1

    def test_group_without_calculable_capacity_preserves_its_state(
        self, catalog
    ):
        _full_day(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        unrated = report.sectors.get(stable_key="NAO-TARIFADO")
        assert unrated.calculation_status == OccupancyCalculationStatus.UNRATED
        assert unrated.official_capacity is None
        assert unrated.occupied_count is None
        assert unrated.occupancy_percentage is None
        assert unrated.exceeded_by is None


# ---------------------------------------------------------------------------
# R3 - closing patient roster
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClosingPatientRoster:
    """R3: nominal rows come exclusively from the closing census photograph."""

    def test_patients_are_exactly_the_closing_census_rows(self, catalog):
        _anchor_census(catalog)
        _opening_census(catalog)
        _closing_census(catalog)
        _next_day_census(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        records = sorted(report.patients.values_list("record", flat=True))
        assert records == sorted(CLOSING_RECORDS)
        assert "7001" not in records
        assert "7002" not in records
        assert "7003" not in records

    def test_patient_rows_keep_provenance_bed_name_record_and_specialty(
        self, catalog
    ):
        closing = _closing_census(catalog)
        _opening_census(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        patient = report.patients.get(record="4001")
        snapshot = CensusSnapshot.objects.get(pk=patient.census_snapshot_id)
        assert snapshot.ingestion_run_id == closing.pk
        assert patient.bed == "3A-01"
        assert patient.name == "PACIENTE ADULTO 3A"
        assert patient.specialty == "OBS"
        assert patient.sector is not None
        assert patient.sector.stable_key == "OBST-3A-ADULTO"

    def test_patient_follows_the_official_age_partition_fallback(self, catalog):
        _full_day(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        def sector_of(record: str) -> str:
            patient = report.patients.get(record=record)
            assert patient.sector is not None
            return patient.sector.stable_key

        assert sector_of("4001") == "OBST-3A-ADULTO"
        assert sector_of("4002") == "OBST-3A-INFANTIL"
        assert sector_of("4003") == "OBST-3A-ADULTO"

    def test_patient_of_unmapped_code_uses_the_persisted_unmapped_group(
        self, catalog
    ):
        _full_day(catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        patient = report.patients.get(record="6001")
        assert patient.sector is not None
        assert patient.sector.stable_key == "UNMAPPED-CODE-990"

    def test_patient_without_source_code_uses_the_official_sector_name(
        self, catalog
    ):
        lines = _closing_lines() + [
            _CensusLine(
                code="",
                sector=UNMAPPED_BY_NAME,
                bed="SC-01",
                record="6100",
                name="PACIENTE SEM CODIGO",
                specialty="CLI",
            )
        ]
        _full_day(catalog, lines=_base_lines() + lines)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        patient = report.patients.get(record="6100")
        assert patient.sector is not None
        assert patient.sector.stable_key == "UNMAPPED-NAME-SEM-CODIGO"

    def test_operational_and_incomplete_identity_rows_are_not_patients(
        self, catalog
    ):
        lines = _closing_lines() + [
            _CensusLine(
                code="900",
                sector="SETOR SINTETICO 900",
                bed="900-B",
                record="222",
                name="RESERVA INTERNA",
            ),
            _CensusLine(
                code="900",
                sector="SETOR SINTETICO 900",
                bed="900-C",
                record="",
                name="PACIENTE SEM PRONTUARIO",
            ),
        ]
        _full_day(catalog, lines=_base_lines() + lines)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        records = sorted(report.patients.values_list("record", flat=True))
        assert records == sorted(CLOSING_RECORDS)
        assert "222" not in records

    def test_same_run_measurement_instant_keeps_the_closing_roster(
        self, catalog
    ):
        """R3: the closing roster follows the accepted photograph, not a
        same-run measurement instant that differs from it."""
        closing = _closing_census(catalog)
        _opening_census(catalog)
        measurement = closing.occupancy_measurement
        OccupancyMeasurement.objects.filter(pk=measurement.pk).update(
            captured_at=_bahia(DAY, 20, 45)
        )

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        assert report.measurement_id == measurement.pk
        assert sorted(report.patients.values_list("record", flat=True)) == sorted(
            CLOSING_RECORDS
        )
        assert report.sectors.count() == len(_default_group_specs())


# ---------------------------------------------------------------------------
# R2/R3 - historical occupancy algorithm contracts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHistoricalOccupancyAlgorithms:
    """R2/R3: an accepted non-v5 measurement keeps its own official grouping."""

    def test_v2_measurement_attributes_rows_by_its_own_age_band(
        self, legacy_catalog
    ):
        lines = _base_lines() + _closing_lines() + [
            _CensusLine(
                code="",
                sector=UNMAPPED_BY_NAME,
                bed="SC-01",
                record="6100",
                name="PACIENTE SEM CODIGO",
                specialty="CLI",
            )
        ]
        closing = _closing_census(
            legacy_catalog,
            lines=lines,
            groups=_legacy_group_specs(),
            algorithm_version="occupancy-v2",
        )
        # v2 omitted the two occupied rows of the partitioned code whose age
        # band is unknown; such a measurement still materializes as selected.
        OccupancyMeasurement.objects.filter(
            pk=closing.occupancy_measurement.pk
        ).update(age_partial=True, unknown_age_count=2)
        _opening_census(legacy_catalog)

        report = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        ).report

        assert report.algorithm_version == "occupancy-v2"
        measurement = closing.occupancy_measurement
        assert {sector.stable_key for sector in report.sectors.all()} == {
            group.stable_key for group in measurement.groups.all()
        }
        adulto = report.sectors.get(stable_key="OBST-3A-ADULTO")
        assert adulto.occupied_count == 1
        assert report.patients.count() == len(CLOSING_RECORDS) + 1
        closing_rows = report.patients.filter(
            census_snapshot__ingestion_run=closing
        ).count()
        assert closing_rows == len(CLOSING_RECORDS) + 1

        def sector_key(record: str) -> str | None:
            sector = report.patients.get(record=record).sector
            return None if sector is None else sector.stable_key

        assert sector_key("111") == "GERAL"
        assert sector_key("4001") == "OBST-3A-ADULTO"
        # v2 counted no official group for the occupied rows of the partitioned
        # code whose age band is unknown: provenance is kept and no v5 record
        # fallback invents a sector for them.
        assert sector_key("4002") is None
        assert sector_key("4003") is None
        assert sector_key("5001") == "NAO-TARIFADO"
        assert sector_key("6001") == "UNMAPPED-CODE-990"
        assert sector_key("6100") == "UNMAPPED-NAME-SEM-CODIGO"

    def test_unimplemented_algorithm_is_refused_without_persisting(
        self, catalog
    ):
        """Every stored contract v1-v5 dispatches; an unknown declaration is
        refused closed instead of receiving a silently coerced grouping."""
        _closing_census(catalog, algorithm_version="occupancy-v9")
        _opening_census(catalog)

        with pytest.raises(OccupancyMaterializationError):
            materialize_daily_statistics(
                local_date=DAY, activation_date=ACTIVATION
            )

        assert DailyStatisticsReport.objects.count() == 0


# ---------------------------------------------------------------------------
# R4 - idempotent rebuild
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIdempotentRebuild:
    """R4: the same source fingerprint never duplicates persisted rows."""

    def test_repeating_the_same_fingerprint_does_not_duplicate_rows(
        self, catalog
    ):
        _full_day(catalog)
        first = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )
        counts = (
            DailyStatisticsReport.objects.count(),
            DailyStatisticsSector.objects.count(),
            DailyStatisticsPatient.objects.count(),
        )

        second = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )

        assert second.created is False
        assert second.report.pk == first.report.pk
        assert second.report.revision == 1
        assert second.report.source_fingerprint == first.report.source_fingerprint
        assert (
            DailyStatisticsReport.objects.count(),
            DailyStatisticsSector.objects.count(),
            DailyStatisticsPatient.objects.count(),
        ) == counts
        assert (
            DailyStatisticsReport.objects.filter(
                status=DailyStatisticsReportStatus.READY
            ).count()
            == 1
        )


# ---------------------------------------------------------------------------
# R5 - atomic publication and single current revision
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAtomicPublication:
    """R5: atomic publication keeps exactly one ready revision per date."""

    def test_changed_closing_evidence_creates_a_new_current_revision(self, catalog):
        closing = _full_day(catalog)
        first = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )
        first_sectors = DailyStatisticsSector.objects.count()
        _late_patient(closing, "333")

        second = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )

        assert second.created is True
        assert second.report.revision == 2
        assert second.report.status == DailyStatisticsReportStatus.READY
        first.report.refresh_from_db()
        assert first.report.status == DailyStatisticsReportStatus.SUPERSEDED
        assert (
            DailyStatisticsReport.objects.filter(
                status=DailyStatisticsReportStatus.READY
            ).count()
            == 1
        )
        # The closing photograph and its official metrics stay pinned.
        assert second.report.closing_run_id == first.report.closing_run_id
        assert second.report.measurement_id == first.report.measurement_id
        assert DailyStatisticsSector.objects.count() == 2 * first_sectors
        first_records = list(first.report.patients.values_list("record", flat=True))
        second_records = list(
            second.report.patients.values_list("record", flat=True)
        )
        assert "333" not in first_records
        assert "333" in second_records

    def test_failed_build_never_replaces_the_current_revision(self, catalog):
        closing = _full_day(catalog)
        first = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )
        first_counts = (
            DailyStatisticsReport.objects.count(),
            DailyStatisticsSector.objects.count(),
            DailyStatisticsPatient.objects.count(),
        )
        _late_patient(closing, "333")

        with patch(
            "apps.statistics_reports.materialization._create_patients",
            side_effect=RuntimeError("synthetic build failure"),
        ):
            with pytest.raises(RuntimeError):
                materialize_daily_statistics(
                    local_date=DAY, activation_date=ACTIVATION
                )

        assert (
            DailyStatisticsReport.objects.count(),
            DailyStatisticsSector.objects.count(),
            DailyStatisticsPatient.objects.count(),
        ) == first_counts
        kept = DailyStatisticsReport.objects.get(pk=first.report.pk)
        assert kept.status == DailyStatisticsReportStatus.READY
        assert kept.revision == 1
        assert "333" not in list(
            kept.patients.values_list("record", flat=True)
        )


# ---------------------------------------------------------------------------
# R6 - activation boundary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestActivationBoundary:
    """R6: no revision is materialized before the declared activation date."""

    def test_date_before_activation_is_refused_without_persisting(self, catalog):
        _full_day(catalog)

        with pytest.raises(DateBeforeActivationError):
            materialize_daily_statistics(
                local_date=PREVIOUS_DAY, activation_date=DAY
            )

        assert DailyStatisticsReport.objects.count() == 0

    def test_activation_date_itself_is_materializable(self, catalog):
        _full_day(catalog)

        outcome = materialize_daily_statistics(
            local_date=DAY, activation_date=DAY
        )

        assert outcome.created is True
        assert outcome.report.local_date == DAY
        assert outcome.report.activation_date == DAY
