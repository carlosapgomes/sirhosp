"""DSRS-S1 unit tests: statistical day selection for one Bahia local date.

Covers the vertical slice requirements:

- R1: opening is the first accepted census completed in ``[00:00, 03:00)`` and
  may have started on the previous civil day;
- R2: closing is the last accepted census started at/after 20:00 and completed
  before midnight, distinct from the opening census;
- R3: anchor is the last accepted census before the opening, and its absence
  degrades quality without inventing movements;
- R4: an accepted census requires success, complete single-run snapshots and
  the exact official measurement of that same run;
- R5: ``CensusExecutionBatch.finished_at`` never participates in selection;
- R6: limits are explicit ``America/Bahia`` instants and an incomplete day
  exposes a structured reason.

Everything here uses synthetic runs, sectors, beds and patients; no real
extraction data, no production access and no backfill.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CapacityCatalogVersion,
    CensusSnapshot,
    OccupancyMeasurement,
)
from apps.census.services import MINIMUM_CENSUS_SECTORS
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.statistics_reports.selection import (
    INCOMPLETE_MISSING_CLOSING,
    INCOMPLETE_MISSING_OPENING,
    INCOMPLETE_OPENING_EQUALS_CLOSING,
    QUALITY_MISSING_ANCHOR,
    select_daily_statistics_window,
)

BAHIA_TZ = ZoneInfo("America/Bahia")

# Fixed synthetic Bahia civil dates; the closing photograph of ``DAY`` is
# already the next UTC civil date, which is exactly what R6 guards.
DAY = date(2026, 9, 15)
PREVIOUS_DAY = DAY - timedelta(days=1)
NEXT_DAY = DAY + timedelta(days=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bahia(day: date, hour: int, minute: int = 0) -> datetime:
    """Aware ``America/Bahia`` instant on ``day``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BAHIA_TZ)


def _make_run(
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str = "succeeded",
    intent: str = "census_extraction",
    batch: CensusExecutionBatch | None = None,
) -> IngestionRun:
    """Create a run and pin the auto-set lifecycle fields explicitly."""
    run = IngestionRun.objects.create(status=status, intent=intent, batch=batch)
    # ``started_at`` is auto_now_add and must be overridden after creation.
    IngestionRun.objects.filter(pk=run.pk).update(
        started_at=started_at,
        finished_at=finished_at,
    )
    run.refresh_from_db()
    return run


def _photograph(
    *,
    run: IngestionRun,
    captured_at: datetime,
    sectors: int = MINIMUM_CENSUS_SECTORS,
    mixed_with: IngestionRun | None = None,
) -> None:
    """Persist one synthetic census photograph at ``captured_at``.

    ``mixed_with`` appends a row of another run inside the same ``captured_at``
    to model a photograph whose provenance is not unique.
    """
    rows = [
        CensusSnapshot(
            captured_at=captured_at,
            ingestion_run=run,
            setor=f"SETOR SINTETICO {index:03d}",
            leito=f"LEITO {index:03d}",
            prontuario="",
            nome="DESOCUPADO",
            bed_status=BedStatus.EMPTY,
        )
        for index in range(sectors)
    ]
    if mixed_with is not None:
        rows.append(
            CensusSnapshot(
                captured_at=captured_at,
                ingestion_run=mixed_with,
                setor="SETOR MISTO",
                leito="LEITO MISTO",
                prontuario="",
                nome="DESOCUPADO",
                bed_status=BedStatus.EMPTY,
            )
        )
    CensusSnapshot.objects.bulk_create(rows)


def _measurement(
    *,
    run: IngestionRun,
    captured_at: datetime,
    catalog: CapacityCatalogVersion,
) -> OccupancyMeasurement:
    """Persist the exact official occupancy measurement of ``run``."""
    return OccupancyMeasurement.objects.create(
        census_run=run,
        catalog=catalog,
        captured_at=captured_at,
        local_date=timezone.localdate(captured_at),
        algorithm_version="occupancy-v5",
        observed_sector_count=MINIMUM_CENSUS_SECTORS,
        capacity_covered_sector_count=MINIMUM_CENSUS_SECTORS,
        calculable_sector_count=MINIMUM_CENSUS_SECTORS,
        known_capacity=MINIMUM_CENSUS_SECTORS,
        calculable_capacity=MINIMUM_CENSUS_SECTORS,
        occupied_for_rate=MINIMUM_CENSUS_SECTORS,
        exceeded_by=0,
    )


def _accepted_census(
    *,
    catalog: CapacityCatalogVersion,
    started_at: datetime,
    finished_at: datetime,
    captured_at: datetime | None = None,
    batch: CensusExecutionBatch | None = None,
    sectors: int = MINIMUM_CENSUS_SECTORS,
    with_measurement: bool = True,
    status: str = "succeeded",
    intent: str = "census_extraction",
    mixed_with: IngestionRun | None = None,
) -> IngestionRun:
    """Create one run that satisfies every acceptance rule by default."""
    run = _make_run(
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        intent=intent,
        batch=batch,
    )
    instant = captured_at if captured_at is not None else finished_at
    _photograph(
        run=run,
        captured_at=instant,
        sectors=sectors,
        mixed_with=mixed_with,
    )
    if with_measurement:
        _measurement(run=run, captured_at=instant, catalog=catalog)
    return run


def _opening_census(catalog: CapacityCatalogVersion) -> IngestionRun:
    """An accepted census completed inside the opening window of ``DAY``."""
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(PREVIOUS_DAY, 23, 30),
        finished_at=_bahia(DAY, 0, 30),
    )


def _closing_census(catalog: CapacityCatalogVersion) -> IngestionRun:
    """An accepted census completed inside the closing window of ``DAY``."""
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(DAY, 21, 0),
        finished_at=_bahia(DAY, 21, 30),
    )


@pytest.fixture
def catalog(db) -> CapacityCatalogVersion:
    """Minimal synthetic capacity catalog referenced by occupied run evidence."""
    return CapacityCatalogVersion.objects.create(
        effective_from=date(2026, 1, 1),
        source_reference="synthetic DSRS-S1 catalog",
        source_sha256="a" * 64,
        schema_version="1.0",
    )


# ---------------------------------------------------------------------------
# R1 - opening census
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOpeningCensusSelection:
    """R1: opening is the first accepted census completed in [00:00, 03:00)."""

    def test_opening_is_first_accepted_census_finished_in_window(self, catalog):
        earlier = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 20),
        )
        later = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 2, 0),
            finished_at=_bahia(DAY, 2, 40),
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.opening.run.pk == earlier.pk
        assert window.opening.run.pk != later.pk
        assert window.complete is True

    def test_opening_may_have_started_on_the_previous_civil_day(self, catalog):
        run = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 15),
            finished_at=_bahia(DAY, 0, 45),
        )

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.opening.run.pk == run.pk

    def test_midnight_start_is_inclusive_for_the_opening_window(self, catalog):
        run = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 0),
            finished_at=_bahia(DAY, 0, 0),
        )

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.opening.run.pk == run.pk

    def test_opening_window_ends_exclusively_at_three_local_hours(self, catalog):
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 2, 0),
            finished_at=_bahia(DAY, 3, 0),
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert window.complete is False
        assert window.incomplete_reasons == (INCOMPLETE_MISSING_OPENING,)

    def test_rejected_candidate_falls_through_to_the_next_accepted_census(
        self, catalog
    ):
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            sectors=MINIMUM_CENSUS_SECTORS - 1,
        )
        accepted = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 1, 30),
            finished_at=_bahia(DAY, 2, 10),
        )

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.opening.run.pk == accepted.pk


# ---------------------------------------------------------------------------
# R2 - closing census
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClosingCensusSelection:
    """R2: closing is the last accepted census started at/after 20:00."""

    def test_closing_is_last_accepted_census_started_after_twenty(self, catalog):
        _opening_census(catalog)
        first = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 20, 15),
            finished_at=_bahia(DAY, 20, 45),
        )
        last = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 22, 5),
            finished_at=_bahia(DAY, 22, 40),
        )

        window = select_daily_statistics_window(DAY)

        assert window.closing is not None
        assert window.closing.run.pk == last.pk
        assert window.closing.run.pk != first.pk
        assert window.complete is True

    def test_closing_window_starts_inclusively_at_twenty(self, catalog):
        _opening_census(catalog)
        run = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 20, 0),
            finished_at=_bahia(DAY, 20, 30),
        )

        window = select_daily_statistics_window(DAY)

        assert window.closing is not None
        assert window.closing.run.pk == run.pk

    def test_run_started_before_twenty_is_not_a_closing_census(self, catalog):
        _opening_census(catalog)
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 19, 50),
            finished_at=_bahia(DAY, 21, 0),
        )

        window = select_daily_statistics_window(DAY)

        assert window.closing is None
        assert window.incomplete_reasons == (INCOMPLETE_MISSING_CLOSING,)

    def test_closing_census_must_finish_before_midnight(self, catalog):
        _opening_census(catalog)
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 22, 30),
            finished_at=_bahia(NEXT_DAY, 0, 15),
        )

        window = select_daily_statistics_window(DAY)

        assert window.closing is None
        assert INCOMPLETE_MISSING_CLOSING in window.incomplete_reasons

    def test_rejected_closing_candidate_leaves_the_day_incomplete(self, catalog):
        _opening_census(catalog)
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 21, 0),
            finished_at=_bahia(DAY, 21, 30),
            with_measurement=False,
        )

        window = select_daily_statistics_window(DAY)

        assert window.closing is None
        assert INCOMPLETE_MISSING_CLOSING in window.incomplete_reasons

    def test_one_anomalous_run_cannot_be_opening_and_closing(self, catalog):
        """R2: opening and closing must be distinct photographs.

        A run whose recorded completion precedes its own start is an
        operational anomaly; it must never supply both boundaries.
        """
        anomalous = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 20, 30),
            finished_at=_bahia(DAY, 1, 0),
        )

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.opening.run.pk == anomalous.pk
        assert window.closing is None
        assert window.incomplete_reasons == (INCOMPLETE_OPENING_EQUALS_CLOSING,)


# ---------------------------------------------------------------------------
# R3 - anchor census
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnchorCensusSelection:
    """R3: anchor is the last accepted census before the opening."""

    def test_anchor_is_last_accepted_census_before_opening(self, catalog):
        older = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 20, 0),
            finished_at=_bahia(PREVIOUS_DAY, 20, 30),
        )
        anchor = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 22, 0),
            finished_at=_bahia(PREVIOUS_DAY, 22, 40),
        )
        _opening_census(catalog)
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.anchor is not None
        assert window.anchor.run.pk == anchor.pk
        assert window.anchor.run.pk != older.pk
        assert window.quality_warnings == ()

    def test_anchor_skips_unaccepted_census(self, catalog):
        accepted = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 21, 0),
            finished_at=_bahia(PREVIOUS_DAY, 21, 40),
        )
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 0),
            finished_at=_bahia(PREVIOUS_DAY, 23, 30),
            sectors=MINIMUM_CENSUS_SECTORS - 1,
        )
        _opening_census(catalog)
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.anchor is not None
        assert window.anchor.run.pk == accepted.pk

    def test_anchor_absent_degrades_quality_without_inventing_movements(
        self, catalog
    ):
        _opening_census(catalog)
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.anchor is None
        assert window.quality_warnings == (QUALITY_MISSING_ANCHOR,)
        assert window.complete is True

    def test_later_census_is_never_used_as_anchor(self, catalog):
        anchor = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 22, 0),
            finished_at=_bahia(PREVIOUS_DAY, 22, 40),
        )
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 1, 30),
            finished_at=_bahia(DAY, 2, 10),
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.anchor is not None
        assert window.anchor.run.pk == anchor.pk


# ---------------------------------------------------------------------------
# R4 - accepted census rules
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAcceptedCensusRules:
    """R4: success, complete single-run snapshots and exact measurement."""

    def test_incomplete_photograph_is_rejected(self, catalog):
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            sectors=MINIMUM_CENSUS_SECTORS - 1,
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert INCOMPLETE_MISSING_OPENING in window.incomplete_reasons

    def test_mixed_provenance_photograph_is_rejected(self, catalog):
        other_run = _make_run(
            started_at=_bahia(PREVIOUS_DAY, 23, 0),
            finished_at=_bahia(DAY, 0, 10),
        )
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            mixed_with=other_run,
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert INCOMPLETE_MISSING_OPENING in window.incomplete_reasons

    def test_missing_exact_measurement_is_never_reused_from_another_run(
        self, catalog
    ):
        donor = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 4, 0),
            finished_at=_bahia(DAY, 4, 30),
        )
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            with_measurement=False,
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert OccupancyMeasurement.objects.filter(
            census_run_id=donor.pk
        ).exists()
        assert INCOMPLETE_MISSING_OPENING in window.incomplete_reasons

    def test_selected_census_exposes_its_own_exact_measurement(self, catalog):
        opening = _opening_census(catalog)
        closing = _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.closing is not None
        assert window.opening.measurement.census_run_id == opening.pk
        assert window.closing.measurement.census_run_id == closing.pk

    def test_failed_run_is_never_an_accepted_census(self, catalog):
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            status="failed",
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert INCOMPLETE_MISSING_OPENING in window.incomplete_reasons

    def test_non_census_intent_is_ignored(self, catalog):
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            intent="admissions_only",
        )
        _closing_census(catalog)

        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert INCOMPLETE_MISSING_OPENING in window.incomplete_reasons


# ---------------------------------------------------------------------------
# R5 - clinical batch is out of the window contract
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClinicalBatchExcludedFromSelection:
    """R5: ``CensusExecutionBatch.finished_at`` never participates."""

    def test_late_batch_drain_does_not_move_a_completed_census(self, catalog):
        late_batch = CensusExecutionBatch.objects.create(
            status="succeeded",
            finished_at=_bahia(NEXT_DAY, 5, 0),
        )
        opening = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 30),
            finished_at=_bahia(DAY, 0, 30),
            batch=late_batch,
        )
        closing = _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 21, 0),
            finished_at=_bahia(DAY, 21, 30),
            batch=late_batch,
        )

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.closing is not None
        assert window.opening.run.pk == opening.pk
        assert window.closing.run.pk == closing.pk
        assert window.complete is True

    def test_batch_drain_moment_never_creates_a_window_candidate(self, catalog):
        early_batch = CensusExecutionBatch.objects.create(
            status="succeeded",
            finished_at=_bahia(DAY, 1, 0),
        )
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(DAY, 3, 30),
            finished_at=_bahia(DAY, 4, 30),
            batch=early_batch,
        )
        accepted = _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 23, 45),
            finished_at=_bahia(DAY, 0, 40),
        )

        window = select_daily_statistics_window(DAY)

        assert window.opening is not None
        assert window.opening.run.pk == accepted.pk


# ---------------------------------------------------------------------------
# R6 - Bahia boundaries and structured incomplete reasons
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBahiaLocalBoundaries:
    """R6: explicit ``America/Bahia`` limits and structured reasons."""

    def test_late_evening_bahia_instant_belongs_to_the_bahia_day(self, catalog):
        _opening_census(catalog)
        closing = _closing_census(catalog)

        # The closing photograph already belongs to the next UTC civil date.
        assert closing.finished_at.astimezone(ZoneInfo("UTC")).date() == NEXT_DAY

        window = select_daily_statistics_window(DAY)

        assert window.closing is not None
        assert window.closing.run.pk == closing.pk
        assert window.complete is True

    def test_bahia_day_does_not_borrow_the_next_day_census(self, catalog):
        _opening_census(catalog)
        _closing_census(catalog)

        window = select_daily_statistics_window(NEXT_DAY)

        assert window.opening is None
        assert window.closing is None
        assert window.incomplete_reasons == (
            INCOMPLETE_MISSING_OPENING,
            INCOMPLETE_MISSING_CLOSING,
        )

    def test_empty_day_reports_structured_incomplete_reasons(self):
        window = select_daily_statistics_window(DAY)

        assert window.opening is None
        assert window.closing is None
        assert window.anchor is None
        assert window.complete is False
        assert window.incomplete_reasons == (
            INCOMPLETE_MISSING_OPENING,
            INCOMPLETE_MISSING_CLOSING,
        )
        assert window.quality_warnings == ()

    def test_selection_is_read_only(self, catalog):
        _accepted_census(
            catalog=catalog,
            started_at=_bahia(PREVIOUS_DAY, 22, 0),
            finished_at=_bahia(PREVIOUS_DAY, 22, 40),
        )
        _opening_census(catalog)
        _closing_census(catalog)

        snapshot_ids = list(
            CensusSnapshot.objects.order_by("pk").values_list("pk", flat=True)
        )
        run_state = list(
            IngestionRun.objects.order_by("pk").values_list(
                "pk", "status", "finished_at"
            )
        )

        select_daily_statistics_window(DAY)

        assert list(
            CensusSnapshot.objects.order_by("pk").values_list("pk", flat=True)
        ) == snapshot_ids
        assert list(
            IngestionRun.objects.order_by("pk").values_list(
                "pk", "status", "finished_at"
            )
        ) == run_state
