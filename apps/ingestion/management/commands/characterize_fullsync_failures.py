"""CFC-S1: one-shot read-only characterization of the fail-only full-sync
failure cohort.

Diagnostic (not a gate): exits 0 whenever the characterization completes.
Output is strictly aggregate — metric names, counts, durations, percentiles,
hours and allowlisted failure reasons. No run/patient identifier, parameter
JSON, clinical text, URL or raw error is ever printed.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.fullsync_failure_characterization import (
    DEFAULT_MAX_PER_STAGE_ROWS,
    DEFAULT_MIN_ATTEMPTS,
    DEFAULT_WINDOW_HOURS,
    CharacterizationConfig,
    CharacterizationResult,
    characterize_fullsync_failures,
)

_NONE_TEXT = "none"


class Command(BaseCommand):
    help = (
        "One-shot read-only aggregate characterization of the fail-only "
        "full-sync failure cohort. Always exits 0 when the "
        "characterization completes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--window-hours",
            type=int,
            default=DEFAULT_WINDOW_HOURS,
            help="Evaluation window in hours (positive, default 168).",
        )
        parser.add_argument(
            "--min-attempts",
            type=int,
            default=DEFAULT_MIN_ATTEMPTS,
            help="Minimum terminal attempts per patient to enter the "
            "fail-only cohort (positive, default 3).",
        )
        parser.add_argument(
            "--max-per-stage-rows",
            type=int,
            default=DEFAULT_MAX_PER_STAGE_ROWS,
            help="Safety ceiling of stage metric rows used per stage "
            "profile (positive, default 5000).",
        )

    def handle(self, *args, **options):
        config = self._config_from(options)
        result = characterize_fullsync_failures(config)
        self._render(result)

    # ------------------------------------------------------------------
    # Validation (R1): every invalid argument fails before any query.
    # ------------------------------------------------------------------

    def _config_from(self, options) -> CharacterizationConfig:
        window_hours = options["window_hours"]
        min_attempts = options["min_attempts"]
        max_per_stage_rows = options["max_per_stage_rows"]

        if window_hours <= 0:
            raise CommandError("--window-hours must be positive")
        if min_attempts <= 0:
            raise CommandError("--min-attempts must be positive")
        if max_per_stage_rows <= 0:
            raise CommandError("--max-per-stage-rows must be positive")

        return CharacterizationConfig(
            window_hours=window_hours,
            min_attempts=min_attempts,
            max_per_stage_rows=max_per_stage_rows,
        )

    # ------------------------------------------------------------------
    # Rendering (R5): fixed labels, counts, durations, percentiles,
    # hours and allowlisted reasons only.
    # ------------------------------------------------------------------

    def _render(self, result: CharacterizationResult) -> None:
        self.stdout.write(
            "fullsync_failure_characterization: "
            f"window_hours={result.window_hours} "
            f"min_attempts={result.min_attempts}"
        )
        cohort = result.cohort
        self.stdout.write(
            "cohort: "
            f"patients={cohort.cohort_patients} "
            f"failed_runs={cohort.cohort_failed_runs} "
            f"attempts_median={_float_text(cohort.attempts_median)} "
            f"attempts_max={cohort.attempts_max} "
            f"first_failure_age_hours={_int_text(cohort.first_failure_age_hours)} "
            f"last_failure_age_hours={_int_text(cohort.last_failure_age_hours)}"
        )
        self.stdout.write(
            f"cohort_failure_reasons: {_pairs_text(result.reasons.cohort)}"
        )
        self.stdout.write(
            f"contrast_failure_reasons: {_pairs_text(result.reasons.contrast)}"
        )
        self.stdout.write(f"stage_profiles: {_profiles_text(result.stage_profiles)}")
        self.stdout.write(
            f"terminal_failing_stages: {_pairs_text(result.terminal_failing_stages)}"
        )
        hours = ",".join(
            f"hour={hour}={count}" for hour, count in result.hourly.hours
        )
        self.stdout.write(f"hourly_histogram: {hours}")


def _float_text(value: float | None) -> str:
    return _NONE_TEXT if value is None else f"{value:g}"


def _int_text(value: int | None) -> str:
    return _NONE_TEXT if value is None else str(value)


def _pairs_text(pairs: tuple[tuple[str, int], ...]) -> str:
    if not pairs:
        return _NONE_TEXT
    return ",".join(f"{label}={count}" for label, count in pairs)


def _profiles_text(profiles) -> str:
    if not profiles:
        return _NONE_TEXT
    return "|".join(
        f"{profile.stage_name}:"
        f"median_seconds={profile.duration_median_seconds:.1f},"
        f"p90_seconds={profile.duration_p90_seconds:.1f},"
        f"samples={profile.samples}"
        for profile in profiles
    )
