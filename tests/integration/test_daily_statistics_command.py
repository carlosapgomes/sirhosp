"""DSRS-S5 integration tests: operational close of the statistical day.

Covers the vertical slice requirements:

- R1: ``--date`` materializes exactly the requested America/Bahia local date and
  returns its revision, status and aggregate counts;
- R2: the automatic mode only closes dates that are concluded, complete and
  equal to or later than the declared activation date, never today;
- R3: repeating an unchanged close is an idempotent no-op, while changed
  evidence publishes the automatic revision defined by DSRS-S4;
- R4: concurrent closes serialize through PostgreSQL and publish one single
  ready revision;
- R5: a failed build keeps the previous ready revision intact, persists nothing
  and returns a safe, identity-free error;
- R6: an incomplete or degraded day is reported structurally without inventing
  data, and no date before activation is ever rebuilt;
- R7: stdout, stderr and logs carry only technical IDs, dates, status and
  aggregate counts.

The synthetic census fixtures (catalog, accepted runs, photographs and nominal
closing rows) are imported from the DSRS-S2 module instead of being duplicated,
following the existing cross-module test helper reuse of ``tests/unit``.

Everything here uses synthetic runs, sectors, beds and patients; no real
extraction data, no production access and no backfill.
"""

from __future__ import annotations

import re
import threading
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import override_settings

from apps.census.models import CapacityCatalogVersion
from apps.ingestion.models import IngestionRun
from apps.statistics_reports.materialization import (
    DailyStatisticsCloseOutcome,
    DailyStatisticsMaterializationError,
    close_daily_statistics,
    eligible_finalization_dates,
    materialize_daily_statistics,
)
from apps.statistics_reports.models import (
    DailyStatisticsReport,
    DailyStatisticsReportStatus,
)
from apps.statistics_reports.selection import QUALITY_MISSING_ANCHOR
from tests.integration.test_daily_statistics_materialization import (
    ACTIVATION,
    CLOSING_RECORDS,
    DAY,
    PREVIOUS_DAY,
    _accepted_census,
    _bahia,
    _base_lines,
    _build_catalog,
    _closing_lines,
    _full_day,
    _late_patient,
)

# The command module owns the Bahia "today" lookup; patching it keeps the
# automatic mode deterministic instead of depending on the wall clock.
_COMMAND_MODULE = (
    "apps.statistics_reports.management.commands.materialize_daily_statistics"
)

# One ready line carries technical values only: dates, run/report IDs, status,
# revision and aggregate counts. Nominal text can never satisfy it.
_READY_LINE = re.compile(
    r"date=(?P<date>\d{4}-\d{2}-\d{2}) status=ready revision=\d+ "
    r"created=(?:true|false) report=\d+ anchor_run=(?:none|\d+) "
    r"opening_run=\d+ closing_run=\d+ sectors=\d+ patients=\d+ events=\d+ "
    r"quality=\S+"
)


@pytest.fixture
def catalog(db) -> CapacityCatalogVersion:
    """Synthetic historical catalog of the shared DSRS-S2 fixtures."""
    return _build_catalog(
        effective_from=date(2026, 1, 1),
        algorithm_version="occupancy-v5",
        source_reference="synthetic DSRS-S5 catalog",
        source_sha256="e" * 64,
    )


def _complete_day(catalog: CapacityCatalogVersion, local_date: date) -> IngestionRun:
    """Anchor, opening and closing accepted censuses of one local date.

    The reused DSRS-S2 measurement helper always records ``DAY`` as its own
    ``local_date``; window selection and the source fingerprint never read that
    field, so it stays irrelevant for any other synthetic date.
    """
    previous = local_date - timedelta(days=1)
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(previous, 19, 0),
        finished_at=_bahia(previous, 19, 30),
        lines=_base_lines(),
    )
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(previous, 23, 30),
        finished_at=_bahia(local_date, 0, 30),
        lines=_base_lines(),
    )
    return _accepted_census(
        catalog=catalog,
        started_at=_bahia(local_date, 21, 0),
        finished_at=_bahia(local_date, 21, 30),
        lines=_base_lines() + _closing_lines(),
    )


def _opening_only_day(catalog: CapacityCatalogVersion) -> None:
    """An incomplete day of ``DAY``: accepted opening, no accepted closing."""
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(PREVIOUS_DAY, 23, 30),
        finished_at=_bahia(DAY, 0, 30),
        lines=_base_lines(),
    )


def _degraded_day(catalog: CapacityCatalogVersion) -> None:
    """A complete day of ``DAY`` without any accepted anchor census."""
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(PREVIOUS_DAY, 23, 30),
        finished_at=_bahia(DAY, 0, 30),
        lines=_base_lines(),
    )
    _accepted_census(
        catalog=catalog,
        started_at=_bahia(DAY, 21, 0),
        finished_at=_bahia(DAY, 21, 30),
        lines=_base_lines() + _closing_lines(),
    )


def _finalize(today: date) -> None:
    """Run the automatic mode with a deterministic Bahia ``today``."""
    with patch(f"{_COMMAND_MODULE}._bahia_today", return_value=today):
        call_command("materialize_daily_statistics", "--finalize")


def _line_of(output: str, local_date: date) -> str:
    """The single output line of ``local_date``."""
    prefix = f"date={local_date.isoformat()} "
    for line in output.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(
        f"no output line for {local_date.isoformat()} in {output!r}"
    )


# ---------------------------------------------------------------------------
# R1 - explicit date materialization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestedDateMaterialization:
    """R1: ``--date`` materializes only the requested Bahia local date."""

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_explicit_date_materializes_only_that_date(self, catalog, capsys):
        _complete_day(catalog, PREVIOUS_DAY)
        _complete_day(catalog, DAY)

        call_command("materialize_daily_statistics", "--date", DAY.isoformat())

        assert DailyStatisticsReport.objects.filter(local_date=DAY).count() == 1
        assert not DailyStatisticsReport.objects.filter(
            local_date=PREVIOUS_DAY
        ).exists()
        assert f"date={DAY.isoformat()} status=ready" in capsys.readouterr().out

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_explicit_date_reports_revision_status_and_counts(self, catalog, capsys):
        _complete_day(catalog, DAY)

        call_command("materialize_daily_statistics", "--date", DAY.isoformat())

        line = _line_of(capsys.readouterr().out, DAY)
        assert _READY_LINE.fullmatch(line)
        assert " revision=1 " in line
        assert " created=true " in line
        assert f" patients={len(CLOSING_RECORDS)} " in line

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_explicit_date_before_activation_is_refused(self, catalog, capsys):
        _complete_day(catalog, PREVIOUS_DAY)

        with pytest.raises(
            CommandError, match="precedes the declared activation date"
        ):
            call_command(
                "materialize_daily_statistics", "--date", PREVIOUS_DAY.isoformat()
            )

        assert DailyStatisticsReport.objects.count() == 0
        assert capsys.readouterr().out == ""

    @override_settings(STATISTICS_ACTIVATION_DATE=None)
    def test_undeclared_activation_refuses_every_date(self, catalog, capsys):
        _complete_day(catalog, DAY)

        with pytest.raises(CommandError, match="STATISTICS_ACTIVATION_DATE"):
            call_command("materialize_daily_statistics", "--date", DAY.isoformat())

        assert DailyStatisticsReport.objects.count() == 0
        assert capsys.readouterr().out == ""

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_explicit_incomplete_date_returns_a_safe_structured_error(
        self, catalog, capsys
    ):
        _opening_only_day(catalog)

        with pytest.raises(
            CommandError, match="missing_accepted_closing_census"
        ):
            call_command("materialize_daily_statistics", "--date", DAY.isoformat())

        assert DailyStatisticsReport.objects.count() == 0
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# R2 - eligible closed dates
# ---------------------------------------------------------------------------


class TestEligibleFinalizationDates:
    """R2: automatic close candidates are bounded, closed, post-activation days."""

    def test_candidates_start_at_activation_and_stop_before_today(self):
        dates = eligible_finalization_dates(
            activation_date=DAY,
            today=DAY + timedelta(days=3),
            lookback_days=7,
        )

        assert dates == (DAY, DAY + timedelta(days=1), DAY + timedelta(days=2))

    def test_today_itself_is_never_a_candidate(self):
        assert (
            eligible_finalization_dates(
                activation_date=DAY, today=DAY, lookback_days=7
            )
            == ()
        )

    def test_no_candidate_precedes_activation(self):
        assert eligible_finalization_dates(
            activation_date=DAY, today=DAY + timedelta(days=1), lookback_days=7
        ) == (DAY,)

    def test_window_is_bounded_to_the_last_lookback_dates(self):
        dates = eligible_finalization_dates(
            activation_date=ACTIVATION, today=DAY, lookback_days=7
        )

        assert dates == tuple(
            DAY - timedelta(days=offset) for offset in range(7, 0, -1)
        )

    def test_activation_wins_when_it_is_inside_the_window(self):
        dates = eligible_finalization_dates(
            activation_date=DAY - timedelta(days=2),
            today=DAY,
            lookback_days=7,
        )

        assert dates == (DAY - timedelta(days=2), DAY - timedelta(days=1))

    def test_non_positive_lookback_is_refused(self):
        with pytest.raises(ValueError, match="lookback_days"):
            eligible_finalization_dates(
                activation_date=DAY, today=DAY + timedelta(days=1), lookback_days=0
            )


# ---------------------------------------------------------------------------
# R2, R3 and R6 - automatic finalization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutomaticFinalization:
    """R2/R3/R6: the automatic mode closes exactly the eligible days."""

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_finalize_closes_only_eligible_closed_dates(self, catalog, capsys):
        _complete_day(catalog, PREVIOUS_DAY)
        _complete_day(catalog, DAY)

        _finalize(today=DAY + timedelta(days=1))

        assert DailyStatisticsReport.objects.filter(local_date=DAY).count() == 1
        assert not DailyStatisticsReport.objects.filter(
            local_date=PREVIOUS_DAY
        ).exists()
        out = capsys.readouterr().out
        assert _READY_LINE.fullmatch(_line_of(out, DAY))
        assert "totals dates=1 materialized=1 reused=0 incomplete=0 failed=0" in out

    @override_settings(STATISTICS_ACTIVATION_DATE=PREVIOUS_DAY)
    def test_finalize_never_selects_today(self, catalog, capsys):
        _complete_day(catalog, DAY)

        _finalize(today=DAY)

        assert DailyStatisticsReport.objects.count() == 0
        out = capsys.readouterr().out
        assert f"date={DAY.isoformat()}" not in out
        assert _line_of(out, PREVIOUS_DAY).startswith("date=2026-09-14 status=incomplete")

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_incomplete_day_is_reported_without_persisting(self, catalog, capsys):
        _opening_only_day(catalog)

        _finalize(today=DAY + timedelta(days=1))

        out = capsys.readouterr().out
        line = _line_of(out, DAY)
        assert line == (
            f"date={DAY.isoformat()} status=incomplete "
            "reasons=missing_accepted_closing_census"
        )
        assert "totals dates=1 materialized=0 reused=0 incomplete=1 failed=0" in out
        assert DailyStatisticsReport.objects.count() == 0

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_close_returns_structured_incomplete_reasons(self, catalog):
        _opening_only_day(catalog)

        outcome = close_daily_statistics(
            local_date=DAY, activation_date=DAY
        )

        assert outcome.report is None
        assert outcome.created is False
        assert outcome.incomplete_reasons == ("missing_accepted_closing_census",)

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_degraded_day_reports_its_quality_code(self, catalog, capsys):
        _degraded_day(catalog)

        _finalize(today=DAY + timedelta(days=1))

        out = capsys.readouterr().out
        assert f"quality={QUALITY_MISSING_ANCHOR}" in _line_of(out, DAY)
        report = DailyStatisticsReport.objects.get(local_date=DAY)
        assert report.quality_warnings_json == [QUALITY_MISSING_ANCHOR]

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_repeating_an_unchanged_finalization_is_a_no_op(self, catalog, capsys):
        _complete_day(catalog, DAY)
        _finalize(today=DAY + timedelta(days=1))
        first = DailyStatisticsReport.objects.get(local_date=DAY)
        capsys.readouterr()

        _finalize(today=DAY + timedelta(days=1))

        out = capsys.readouterr().out
        assert DailyStatisticsReport.objects.count() == 1
        assert DailyStatisticsReport.objects.get(local_date=DAY).pk == first.pk
        assert "created=false" in _line_of(out, DAY)
        assert "totals dates=1 materialized=0 reused=1 incomplete=0 failed=0" in out

    @override_settings(STATISTICS_ACTIVATION_DATE=DAY)
    def test_changed_evidence_finalizes_a_new_current_revision(self, catalog, capsys):
        closing = _complete_day(catalog, DAY)
        _finalize(today=DAY + timedelta(days=1))
        _late_patient(closing, "333")

        _finalize(today=DAY + timedelta(days=1))

        revisions = {
            report.revision: report.status
            for report in DailyStatisticsReport.objects.filter(local_date=DAY)
        }
        assert revisions == {
            1: DailyStatisticsReportStatus.SUPERSEDED,
            2: DailyStatisticsReportStatus.READY,
        }
        assert "created=true" in _line_of(capsys.readouterr().out, DAY)


# ---------------------------------------------------------------------------
# R2 and R6 - bounded automatic window
# ---------------------------------------------------------------------------

# Deterministic "today" for the bounded-window regressions: far enough after
# activation that the configured lookback window, not the activation date,
# bounds the candidate dates.
_BOUNDED_TODAY = ACTIVATION + timedelta(days=10)
_WINDOW_DAYS = 7


@pytest.mark.django_db
class TestBoundedFinalization:
    """R2/R6: the automatic window never reaches older post-activation dates."""

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_date_just_outside_the_window_is_not_selected(self, catalog, capsys):
        outside = _BOUNDED_TODAY - timedelta(days=_WINDOW_DAYS + 1)
        inside = _BOUNDED_TODAY - timedelta(days=_WINDOW_DAYS - 2)
        _complete_day(catalog, outside)
        _complete_day(catalog, inside)

        _finalize(today=_BOUNDED_TODAY)

        out = capsys.readouterr().out
        assert DailyStatisticsReport.objects.filter(local_date=inside).count() == 1
        assert not DailyStatisticsReport.objects.filter(local_date=outside).exists()
        assert f"date={outside.isoformat()}" not in out

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_totals_reflect_only_the_bounded_window(self, catalog, capsys):
        outside = _BOUNDED_TODAY - timedelta(days=_WINDOW_DAYS + 1)
        inside = _BOUNDED_TODAY - timedelta(days=_WINDOW_DAYS - 2)
        _complete_day(catalog, outside)
        _complete_day(catalog, inside)

        _finalize(today=_BOUNDED_TODAY)

        out = capsys.readouterr().out
        date_lines = [line for line in out.splitlines() if line.startswith("date=")]
        assert len(date_lines) == _WINDOW_DAYS
        assert (
            f"totals dates={_WINDOW_DAYS} materialized=1 reused=0 "
            "incomplete=6 failed=0" in out
        )

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_explicit_date_reaches_an_older_date_outside_the_window(
        self, catalog, capsys
    ):
        outside = _BOUNDED_TODAY - timedelta(days=_WINDOW_DAYS + 1)
        _complete_day(catalog, outside)

        call_command("materialize_daily_statistics", "--date", outside.isoformat())

        assert DailyStatisticsReport.objects.filter(local_date=outside).count() == 1
        assert f"date={outside.isoformat()} status=ready" in capsys.readouterr().out

    @override_settings(STATISTICS_ACTIVATION_DATE=_BOUNDED_TODAY - timedelta(days=2))
    def test_activation_later_than_the_window_still_wins(self, catalog, capsys):
        activation = _BOUNDED_TODAY - timedelta(days=2)
        before_activation = _BOUNDED_TODAY - timedelta(days=4)
        _complete_day(catalog, activation)
        _complete_day(catalog, before_activation)

        _finalize(today=_BOUNDED_TODAY)

        out = capsys.readouterr().out
        assert DailyStatisticsReport.objects.filter(local_date=activation).count() == 1
        assert not DailyStatisticsReport.objects.filter(
            local_date=before_activation
        ).exists()
        assert f"date={before_activation.isoformat()}" not in out
        assert "totals dates=2 materialized=1 reused=0 incomplete=1 failed=0" in out

    @override_settings(
        STATISTICS_ACTIVATION_DATE=ACTIVATION,
        STATISTICS_FINALIZATION_LOOKBACK_DAYS=0,
    )
    def test_non_positive_lookback_refuses_the_run_without_processing(
        self, catalog, capsys
    ):
        _complete_day(catalog, _BOUNDED_TODAY - timedelta(days=1))

        with pytest.raises(
            CommandError, match="STATISTICS_FINALIZATION_LOOKBACK_DAYS"
        ):
            _finalize(today=_BOUNDED_TODAY)

        assert DailyStatisticsReport.objects.count() == 0
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# R4 - concurrent coordination
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestConcurrentClose:
    """R4: two concurrent closes of one date publish one ready revision."""

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_concurrent_closes_publish_one_ready_revision(self, catalog):
        _complete_day(catalog, DAY)
        outcomes: list[DailyStatisticsCloseOutcome] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def close_in_thread() -> None:
            try:
                connections.close_all()
                barrier.wait(timeout=30)
                outcomes.append(
                    close_daily_statistics(
                        local_date=DAY, activation_date=ACTIVATION
                    )
                )
            except BaseException as error:  # noqa: BLE001 - surfaced below
                errors.append(error)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=close_in_thread) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert [thread.is_alive() for thread in threads] == [False, False]
        assert errors == []
        assert len(outcomes) == 2
        assert len({outcome.report.pk for outcome in outcomes if outcome.report}) == 1
        assert sum(1 for outcome in outcomes if outcome.created) == 1

        report = DailyStatisticsReport.objects.get(local_date=DAY)
        assert report.revision == 1
        assert (
            DailyStatisticsReport.objects.filter(
                status=DailyStatisticsReportStatus.READY
            ).count()
            == 1
        )
        assert DailyStatisticsReport.objects.count() == 1
        assert report.patients.count() == len(CLOSING_RECORDS)


# ---------------------------------------------------------------------------
# R5 - atomic failure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFailedClose:
    """R5: a failed close keeps the ready revision and fails safely."""

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_failed_rebuild_keeps_the_ready_revision(self, catalog):
        closing = _full_day(catalog)
        first = materialize_daily_statistics(
            local_date=DAY, activation_date=ACTIVATION
        )
        counts = (
            DailyStatisticsReport.objects.count(),
            first.report.sectors.count(),
            first.report.patients.count(),
        )
        _late_patient(closing, "333")

        with patch(
            "apps.statistics_reports.materialization._create_events",
            side_effect=DailyStatisticsMaterializationError(
                "synthetic build failure"
            ),
        ):
            with pytest.raises(CommandError, match="synthetic build failure"):
                call_command(
                    "materialize_daily_statistics", "--date", DAY.isoformat()
                )

        assert (
            DailyStatisticsReport.objects.count(),
            first.report.sectors.count(),
            first.report.patients.count(),
        ) == counts
        kept = DailyStatisticsReport.objects.get(pk=first.report.pk)
        assert kept.status == DailyStatisticsReportStatus.READY
        assert kept.revision == 1
        assert "333" not in list(kept.patients.values_list("record", flat=True))

    @override_settings(STATISTICS_ACTIVATION_DATE=PREVIOUS_DAY)
    def test_unexpected_failure_is_reported_by_class_without_identity(
        self, catalog, capsys
    ):
        _complete_day(catalog, PREVIOUS_DAY)
        _complete_day(catalog, DAY)

        with patch(
            "apps.statistics_reports.materialization._create_events",
            side_effect=RuntimeError("PACIENTE GERAL UM 111"),
        ):
            with pytest.raises(CommandError, match="finalization failed for 2 of 2"):
                _finalize(today=DAY + timedelta(days=1))

        out, err = capsys.readouterr()
        assert (
            f"date={PREVIOUS_DAY.isoformat()} status=failed error=RuntimeError"
            in out
        )
        assert f"date={DAY.isoformat()} status=failed error=RuntimeError" in out
        assert "totals dates=2 materialized=0 reused=0 incomplete=0 failed=2" in out
        assert DailyStatisticsReport.objects.count() == 0
        assert "PACIENTE" not in out
        assert "PACIENTE" not in err


# ---------------------------------------------------------------------------
# R7 - identity-free operational output
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOperationalOutput:
    """R7: the operator output never carries clinical identity."""

    @override_settings(STATISTICS_ACTIVATION_DATE=ACTIVATION)
    def test_output_carries_only_technical_ids_dates_and_counts(
        self, catalog, capsys, caplog
    ):
        closing = _full_day(catalog)
        _late_patient(closing, "333")

        call_command("materialize_daily_statistics", "--date", DAY.isoformat())

        out, err = capsys.readouterr()
        assert _READY_LINE.fullmatch(_line_of(out, DAY))
        assert f" patients={len(CLOSING_RECORDS) + 1} " in out
        for captured in (out, err):
            assert "PACIENTE" not in captured
            assert "GERAL UM" not in captured
            assert "=333" not in captured
        for record in caplog.records:
            assert "PACIENTE" not in record.getMessage()
