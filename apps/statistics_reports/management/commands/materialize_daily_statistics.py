"""Close-of-day materialization command (DSRS-S5).

Two explicit modes, both idempotent and coordinated through PostgreSQL row
locks taken by the materializer itself:

- ``--date`` closes exactly the requested ``America/Bahia`` local date and may
  carry ``--quality-warning`` codes, a repeatable and allowlisted declaration of
  an operational degradation (a failed or unconfirmed D-1 reconciliation) that
  the adaptive orchestrator publishes with the revision;
- ``--finalize`` closes every eligible date: complete, equal to or later than
  the declared activation date, strictly before today and inside the
  configured lookback window of the most recent closed dates
  (``STATISTICS_FINALIZATION_LOOKBACK_DAYS``), so a day still being observed
  never closes itself, no earlier history is rebuilt and the automatic batch
  never grows into an unbounded historical sweep. It never carries a
  degradation warning: one observed D-1 outcome cannot be attributed to every
  date of the window, so the combination is refused before anything is built.

An incomplete day is an operational state, not a build failure: in the batch
mode it is reported with its structured reasons and the remaining eligible
dates are still processed, while an explicit ``--date`` refuses it with a
non-zero exit. Every line written to stdout/stderr carries dates, technical
run/report IDs, status, aggregate counts and enumerated quality codes only, and
a failure is reduced to a safe technical token so a raw driver or integrity
message can never print nominal clinical values. A ``--quality-warning`` value
outside the closed allowlist is refused without echoing the value, so free text
cannot be copied into the log or into the persisted revision.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.statistics_reports.materialization import (
    OPERATIONAL_QUALITY_CODE_ALLOWLIST,
    DailyStatisticsCloseOutcome,
    DailyStatisticsMaterializationError,
    close_daily_statistics,
    eligible_finalization_dates,
)
from apps.statistics_reports.origin_policy import DEFAULT_ORIGIN_POLICY
from apps.statistics_reports.selection import BAHIA_TZ


class Command(BaseCommand):
    help = (
        "Materialize the daily statistics revision of one explicit "
        "America/Bahia local date, or finalize every eligible closed date."
    )

    def add_arguments(self, parser) -> None:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--date",
            type=date.fromisoformat,
            help="America/Bahia local date (YYYY-MM-DD) to materialize.",
        )
        mode.add_argument(
            "--finalize",
            action="store_true",
            default=False,
            help=(
                "Finalize every eligible closed local date: complete, equal "
                "to or later than the activation date, before today and "
                "inside the configured lookback window."
            ),
        )
        parser.add_argument(
            "--quality-warning",
            action="append",
            dest="quality_warning",
            default=None,
            metavar="CODE",
            help=(
                "Operational quality code published with the requested "
                "--date revision; repeatable and restricted to the closed "
                f"allowlist {', '.join(OPERATIONAL_QUALITY_CODE_ALLOWLIST)}. "
                "Never accepted together with --finalize."
            ),
        )

    def handle(self, *args, **options) -> None:
        requested_date = options["date"]
        quality_warnings = tuple(options["quality_warning"] or ())
        if options["finalize"] and quality_warnings:
            # One observed D-1 outcome belongs to one date; spreading it over
            # the whole eligible window would degrade clean dates too.
            raise CommandError(
                "--quality-warning is only accepted with --date: --finalize "
                "never degrades a batch of dates."
            )
        activation_date = _activation_date()
        if requested_date is not None:
            self._materialize_requested_date(
                requested_date, activation_date, quality_warnings
            )
        else:
            self._finalize_eligible_dates(activation_date)

    def _materialize_requested_date(
        self,
        local_date: date,
        activation_date: date,
        operational_quality_codes: Sequence[str],
    ) -> None:
        """Close one explicitly requested date or refuse it safely."""
        try:
            outcome = close_daily_statistics(
                local_date=local_date,
                activation_date=activation_date,
                origin_policy=DEFAULT_ORIGIN_POLICY,
                operational_quality_codes=operational_quality_codes,
            )
        except Exception as exc:
            raise CommandError(_failure_message(local_date, exc)) from exc
        if outcome.report is None:
            raise CommandError(
                f"date={local_date.isoformat()} could not be materialized: "
                f"incomplete day ({_token(outcome.incomplete_reasons)})"
            )
        self.stdout.write(_outcome_line(outcome))

    def _finalize_eligible_dates(self, activation_date: date) -> None:
        """Close every eligible closed date, reporting each one structurally."""
        today = _bahia_today()
        lookback_days = _finalization_lookback_days()
        dates = eligible_finalization_dates(
            activation_date=activation_date,
            today=today,
            lookback_days=lookback_days,
        )
        materialized = reused = incomplete = failed = 0
        for local_date in dates:
            try:
                outcome = close_daily_statistics(
                    local_date=local_date,
                    activation_date=activation_date,
                    origin_policy=DEFAULT_ORIGIN_POLICY,
                )
            except Exception as exc:
                failed += 1
                self.stdout.write(_failure_line(local_date, exc))
                continue
            if outcome.report is None:
                incomplete += 1
            elif outcome.created:
                materialized += 1
            else:
                reused += 1
            self.stdout.write(_outcome_line(outcome))
        self.stdout.write(
            _totals_line(
                len(dates), materialized, reused, incomplete, failed
            )
        )
        if failed:
            # The structured lines above already explain every failing date.
            raise CommandError(
                f"finalization failed for {failed} of {len(dates)} "
                "eligible local date(s)"
            )


def _activation_date() -> date:
    """Declared activation date, or refuse the run when it is not configured.

    An undeclared boundary means no local date is eligible yet: the command
    fails closed instead of choosing a date and silently rebuilding history.
    """
    activation_date = getattr(settings, "STATISTICS_ACTIVATION_DATE", None)
    if activation_date is None:
        raise CommandError(
            "STATISTICS_ACTIVATION_DATE is not configured: no local date is "
            "eligible and nothing is materialized."
        )
    return activation_date


def _bahia_today() -> date:
    """Current ``America/Bahia`` local date, independent of the UTC date."""
    return timezone.now().astimezone(BAHIA_TZ).date()


def _finalization_lookback_days() -> int:
    """Positive count of closed local dates the automatic mode may consider.

    A missing or non-positive configuration is refused before any date is
    inspected or materialized, so a misconfiguration can never fall back to an
    unbounded historical sweep.
    """
    lookback_days = getattr(
        settings, "STATISTICS_FINALIZATION_LOOKBACK_DAYS", None
    )
    if not isinstance(lookback_days, int) or isinstance(lookback_days, bool):
        raise CommandError(
            "STATISTICS_FINALIZATION_LOOKBACK_DAYS must be a positive integer: "
            "no local date is eligible and nothing is materialized."
        )
    if lookback_days < 1:
        raise CommandError(
            "STATISTICS_FINALIZATION_LOOKBACK_DAYS must be positive: no local "
            "date is eligible and nothing is materialized."
        )
    return lookback_days


def _token(codes: Sequence[str]) -> str:
    """Aggregate code list of one structured field, or ``none``."""
    return ",".join(codes) if codes else "none"


def _outcome_line(outcome: DailyStatisticsCloseOutcome) -> str:
    """One technical output line of a closed or incomplete local date."""
    report = outcome.report
    if report is None:
        return " ".join(
            [
                f"date={outcome.local_date.isoformat()}",
                "status=incomplete",
                f"reasons={_token(outcome.incomplete_reasons)}",
            ]
        )
    anchor_run = report.anchor_run_id if report.anchor_run_id is not None else "none"
    return " ".join(
        [
            f"date={outcome.local_date.isoformat()}",
            f"status={report.status}",
            f"revision={report.revision}",
            f"created={str(outcome.created).lower()}",
            f"report={report.pk}",
            f"anchor_run={anchor_run}",
            f"opening_run={report.opening_run_id}",
            f"closing_run={report.closing_run_id}",
            f"sectors={report.sectors.count()}",
            f"patients={report.patients.count()}",
            f"events={report.events.count()}",
            f"quality={_token(tuple(report.quality_warnings_json))}",
        ]
    )


def _failure_line(local_date: date, error: Exception) -> str:
    """Structured failure line of one date, named only by exception class."""
    return " ".join(
        [
            f"date={local_date.isoformat()}",
            "status=failed",
            f"error={type(error).__name__}",
        ]
    )


def _failure_message(local_date: date, error: Exception) -> str:
    """Safe error message of one failed date, free of clinical values.

    Domain materialization errors are built from dates, primary keys and
    structured reason codes, so their message is safe to show. Any other
    exception is named only by its class, because a traceback, a driver error
    or an integrity detail could otherwise print nominal row values.
    """
    if isinstance(error, DailyStatisticsMaterializationError):
        detail = str(error)
    else:
        detail = type(error).__name__
    return f"date={local_date.isoformat()} could not be materialized: {detail}"


def _totals_line(
    dates: int,
    materialized: int,
    reused: int,
    incomplete: int,
    failed: int,
) -> str:
    """Aggregate closing line of one automatic finalization run."""
    return " ".join(
        [
            f"totals dates={dates}",
            f"materialized={materialized}",
            f"reused={reused}",
            f"incomplete={incomplete}",
            f"failed={failed}",
        ]
    )
