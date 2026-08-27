"""Management command: recover admissions for the latest complete census."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.census.admissions_recovery import (
    MAX_RECOVERY_LIMIT,
    CensusAdmissionsRecoveryError,
    apply_current_census_admissions_recovery,
    plan_current_census_admissions_recovery,
)

_BLOCKED_MESSAGES: dict[str, str] = {
    "missing_snapshot": "recovery blocked: no census snapshot available",
    "incomplete_snapshot": (
        "recovery blocked: latest census snapshot is incomplete "
        "(insufficient sector coverage)"
    ),
    "ambiguous_provenance": (
        "recovery blocked: latest census snapshot does not resolve to a "
        "single census ingestion run"
    ),
    "unresolved_census_run": (
        "recovery blocked: latest census snapshot does not resolve to a "
        "successful census run"
    ),
}


class Command(BaseCommand):
    """Recover admissions for unique occupied patients of the latest census.

    Dry-run is the default and never mutates any table. ``--apply`` is
    explicit and requires ``--limit`` (integer 1..100) to enqueue at most N
    ``admissions_only`` runs in a single recovery batch; running without an
    explicit apply choice is implicitly prohibited. Output is strictly
    aggregate (counts and fixed labels) and never prints patient data.
    """

    help = (
        "Recover admissions for unique occupied patients of the latest "
        "complete census. dry-run by default (prints aggregate counts, "
        "mutates nothing); --apply requires --limit (integer 1..100) to "
        "enqueue at most N admissions_only runs in a single recovery batch."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Explicitly apply recovery: requires --limit and creates one "
                "recovery batch with at most N admissions_only runs."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Bounded number of admissions_only runs to enqueue on apply "
                f"(integer 1..{MAX_RECOVERY_LIMIT}); in dry-run, previews "
                "the applicable cap."
            ),
        )

    def handle(self, *args, **options):
        apply_mode: bool = bool(options["apply"])
        limit: int | None = options["limit"]

        if limit is not None and not (1 <= limit <= MAX_RECOVERY_LIMIT):
            raise CommandError(
                f"--limit must be an integer between 1 and "
                f"{MAX_RECOVERY_LIMIT}"
            )

        if apply_mode:
            if limit is None:
                raise CommandError(
                    "--apply requires --limit "
                    f"(integer 1..{MAX_RECOVERY_LIMIT})"
                )
            try:
                result = apply_current_census_admissions_recovery(limit=limit)
                plan = result.plan
            except CensusAdmissionsRecoveryError as exc:
                # The domain reason is a fixed sanitized category; the
                # original exception context must not chain into output.
                raise CommandError(_BLOCKED_MESSAGES[exc.reason]) from None
        else:
            try:
                result = None
                plan = plan_current_census_admissions_recovery(limit=limit)
            except CensusAdmissionsRecoveryError as exc:
                raise CommandError(_BLOCKED_MESSAGES[exc.reason]) from None

        mode_label = "apply" if apply_mode else "dry-run"
        self.stdout.write(
            f"current-census admissions recovery {mode_label}:"
        )
        self.stdout.write(f"  candidates: {plan.candidates}")
        self.stdout.write(f"  eligible: {plan.eligible}")
        self.stdout.write(f"  limit_applicable: {plan.limit_applicable}")
        self.stdout.write(f"  excluded_active: {plan.excluded_active}")
        self.stdout.write(
            f"  excluded_recovered: {plan.excluded_recovered}"
        )
        self.stdout.write(
            f"  excluded_no_identifier: {plan.excluded_no_identifier}"
        )

        if apply_mode:
            assert result is not None
            if result.batch_id is None:
                self.stdout.write(
                    "apply complete: no eligible candidates, no batch created"
                )
            else:
                self.stdout.write(
                    f"apply complete: recovery batch created with "
                    f"{result.runs_created} runs"
                )
        else:
            self.stdout.write("dry-run complete: no mutations applied")
