"""RPAP-S5: one-shot read-only aggregate health check for the ingestion
pipeline.

Suitable for systemd timers: exits 0 when healthy and raises
``CommandError`` (exit 1) when any configured invariant or threshold
fails. Output is strictly aggregate — metric names, counts, percentages,
rounded durations, booleans and allowlisted failure reasons. No run/batch/
patient/admission/event identifier, parameter JSON, clinical text, URL or
raw error is ever printed.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.pipeline_health import (
    DEFAULT_MAX_ACTIVE_AGE_MINUTES,
    DEFAULT_MAX_FULL_SYNC_FAILURE_PERCENT,
    DEFAULT_MIN_FULL_SYNC_TERMINAL_SAMPLE,
    DEFAULT_SETTLING_MINUTES,
    DEFAULT_WINDOW_HOURS,
    HealthConfig,
    evaluate_pipeline_health,
)

_FRESHNESS_FLAGS = (
    "max_movement_age_hours",
    "max_admission_age_hours",
    "max_event_age_hours",
)


class Command(BaseCommand):
    help = (
        "One-shot read-only aggregate health check for the ingestion "
        "pipeline. Exit 0 when healthy; CommandError when invariants fail."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-hours",
            type=int,
            default=DEFAULT_WINDOW_HOURS,
            help="Evaluation window in hours (positive).",
        )
        parser.add_argument(
            "--settling-minutes",
            type=int,
            default=DEFAULT_SETTLING_MINUTES,
            help="Minutes to wait before flagging a missing full-sync "
            "follow-up (non-negative).",
        )
        parser.add_argument(
            "--max-active-age-minutes",
            type=int,
            default=DEFAULT_MAX_ACTIVE_AGE_MINUTES,
            help="Maximum age of the oldest queued/running supported run "
            "(positive).",
        )
        parser.add_argument(
            "--max-full-sync-failure-percent",
            type=float,
            default=DEFAULT_MAX_FULL_SYNC_FAILURE_PERCENT,
            help="Maximum full-sync terminal failure percentage (0..100).",
        )
        parser.add_argument(
            "--min-full-sync-terminal-sample",
            type=int,
            default=DEFAULT_MIN_FULL_SYNC_TERMINAL_SAMPLE,
            help="Minimum terminal full-sync sample before the failure rate "
            "alarms (positive).",
        )
        parser.add_argument(
            "--max-movement-age-hours",
            type=int,
            default=None,
            help="Optional maximum age in hours of the latest "
            "PatientMovement; omitted disables the alarm (informational).",
        )
        parser.add_argument(
            "--max-admission-age-hours",
            type=int,
            default=None,
            help="Optional maximum age in hours of the latest Admission "
            "update; omitted disables the alarm (informational).",
        )
        parser.add_argument(
            "--max-event-age-hours",
            type=int,
            default=None,
            help="Optional maximum age in hours of the latest "
            "ClinicalEvent; omitted disables the alarm (informational).",
        )

    def handle(self, *args, **options):
        config = self._config_from(options)
        result = evaluate_pipeline_health(config)
        self._render(result)
        if not result.healthy:
            violations = ",".join(
                f"{violation.code}={violation.count}"
                for violation in result.violations
            )
            raise CommandError(
                f"ingestion pipeline health: unhealthy violations={violations}"
            )

    # ------------------------------------------------------------------
    # Validation (R1): every invalid argument fails before any query.
    # ------------------------------------------------------------------

    def _config_from(self, options) -> HealthConfig:
        window_hours = options["window_hours"]
        settling_minutes = options["settling_minutes"]
        max_active_age_minutes = options["max_active_age_minutes"]
        max_failure_percent = options["max_full_sync_failure_percent"]
        min_sample = options["min_full_sync_terminal_sample"]

        if window_hours <= 0:
            raise CommandError("--window-hours must be positive")
        if settling_minutes < 0:
            raise CommandError("--settling-minutes must be non-negative")
        if max_active_age_minutes <= 0:
            raise CommandError("--max-active-age-minutes must be positive")
        if not 0 <= max_failure_percent <= 100:
            raise CommandError(
                "--max-full-sync-failure-percent must be between 0 and 100"
            )
        if min_sample <= 0:
            raise CommandError("--min-full-sync-terminal-sample must be positive")
        for flag in _FRESHNESS_FLAGS:
            value = options[flag]
            if value is not None and value <= 0:
                raise CommandError(f"--{flag.replace('_', '-')} must be positive")

        return HealthConfig(
            window_hours=window_hours,
            settling_minutes=settling_minutes,
            max_active_age_minutes=max_active_age_minutes,
            max_full_sync_failure_percent=float(max_failure_percent),
            min_full_sync_terminal_sample=min_sample,
            max_movement_age_hours=options["max_movement_age_hours"],
            max_admission_age_hours=options["max_admission_age_hours"],
            max_event_age_hours=options["max_event_age_hours"],
        )

    # ------------------------------------------------------------------
    # Rendering (R5): fixed labels, counts, percentages, booleans only.
    # ------------------------------------------------------------------

    def _render(self, result) -> None:
        healthy = "true" if result.healthy else "false"
        self.stdout.write(
            f"ingestion pipeline health: healthy={healthy} "
            f"window_hours={result.window_hours}"
        )
        invariants = result.invariants
        self.stdout.write(
            "batch_invariants: "
            f"empty_success={invariants.empty_success_count} "
            f"missing_full_sync={invariants.missing_full_sync_count} "
            f"duplicate_demographics={invariants.duplicate_demographics_count} "
            f"recognized_recent_encounter="
            f"{invariants.recognized_recent_encounter_count}"
        )
        queue = result.queue
        self.stdout.write(
            "queue: "
            f"active={queue.active_count} "
            f"oldest_age_minutes={queue.oldest_age_minutes}"
        )
        full_sync = result.full_sync
        percent = (
            "none"
            if full_sync.failure_percent is None
            else f"{full_sync.failure_percent:.1f}"
        )
        self.stdout.write(
            "full_sync: "
            f"terminal={full_sync.terminal_count} "
            f"succeeded={full_sync.succeeded_count} "
            f"failed={full_sync.failed_count} "
            f"events_created={full_sync.events_created} "
            f"failure_percent={percent}"
        )
        reasons = (
            "none"
            if not full_sync.failure_reasons
            else ",".join(
                f"{reason}={count}" for reason, count in full_sync.failure_reasons
            )
        )
        self.stdout.write(f"full_sync_failure_reasons: {reasons}")
        freshness = result.freshness
        self.stdout.write(
            "freshness: "
            f"movement_present={_bool_text(freshness.movement_present)} "
            f"movement_age_minutes={_int_text(freshness.movement_age_minutes)} "
            f"admission_present={_bool_text(freshness.admission_present)} "
            f"admission_age_minutes={_int_text(freshness.admission_age_minutes)} "
            f"event_present={_bool_text(freshness.event_present)} "
            f"event_age_minutes={_int_text(freshness.event_age_minutes)}"
        )
        if not result.healthy:
            violations = ",".join(
                f"{violation.code}={violation.count}"
                for violation in result.violations
            )
            self.stdout.write(f"violations: {violations}")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _int_text(value: int | None) -> str:
    return "none" if value is None else str(value)
