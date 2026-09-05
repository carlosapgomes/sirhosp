"""Bounded dry-run backfill and authorized apply for exits (RPSA-S9).

Dry-run is the default and prints only aggregate cohort counts, manual
review reasons and plan bounds — never patient name, prontuário, source
identifiers or clinical text. Apply requires ``--apply`` plus a positive
``--limit`` within the canary cap (50 with zero prior backfill batches,
100 afterwards), a non-empty ``--label`` and a non-empty ``--backup-ref``;
every precondition is validated before any mutation. Apply executes one
bounded transaction per batch and mutates only through the online
reconciliation and merge services. Summary/refresh pipelines are never
started here; affected admissions stay identifiable through the audit
payloads for the separate bounded refresh.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.patients.backfill import (
    COHORT_DEATHS,
    COHORT_DISCHARGES,
    COHORT_DUPLICATES,
    BackfillPlan,
    apply_backfill_plan,
    build_backfill_plan,
    current_apply_cap,
)


class Command(BaseCommand):
    help = (
        "Plan (default dry-run) and, with explicit authorization flags, "
        "apply bounded historical reconciliation cohorts: source-confirmed "
        "duplicates, exact hospital discharges and complete deaths. "
        "Ambiguities are counted for manual review only."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the planned cohorts (dry-run is the default).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Positive bound applied to the merged plan (required on apply).",
        )
        parser.add_argument(
            "--label",
            type=str,
            default=None,
            help="Non-empty operation label recorded by the operator (apply).",
        )
        parser.add_argument(
            "--backup-ref",
            dest="backup_ref",
            type=str,
            default=None,
            help="Non-empty backup reference proving the pre-apply backup (apply).",
        )

    def handle(self, *args, **options) -> None:
        apply_mode: bool = options["apply"]
        limit = options["limit"]
        label = (options["label"] or "").strip()
        backup_ref = (options["backup_ref"] or "").strip()

        if limit is not None and limit <= 0:
            raise CommandError("--limit must be a positive integer.")
        if apply_mode:
            if limit is None:
                raise CommandError(
                    "--apply requires a positive --limit within the canary cap."
                )
            if not label:
                raise CommandError(
                    "--apply requires a non-empty --label identifying the operation."
                )
            if not backup_ref:
                raise CommandError(
                    "--apply requires a non-empty --backup-ref identifying the backup."
                )
            cap = current_apply_cap()
            if limit > cap:
                raise CommandError(
                    f"--limit {limit} exceeds the canary cap of {cap} for the "
                    "current backfill batch history."
                )

        plan = build_backfill_plan(limit=limit)
        self._print_plan(plan, apply=apply_mode)

        if not apply_mode:
            self.stdout.write("Nothing was mutated (dry-run default).")
            return

        try:
            result = apply_backfill_plan(plan=plan)
        except Exception as exc:
            raise CommandError(
                "Backfill apply failed; the whole batch rolled back with "
                f"zero writes: {exc}"
            ) from exc

        self.stdout.write(
            f"applied batch_uuid={result.batch_uuid} items={result.items}"
        )
        for cohort in (COHORT_DUPLICATES, COHORT_DISCHARGES, COHORT_DEATHS):
            self.stdout.write(
                f"applied cohort={cohort} count={result.applied[cohort]}"
            )

    def _print_plan(self, plan: BackfillPlan, *, apply: bool) -> None:
        mode = "apply" if apply else "dry-run"
        limit_label = str(plan.limit) if plan.limit is not None else "none"
        self.stdout.write(
            f"backfill plan: mode={mode} cap={plan.cap} limit={limit_label}"
        )
        for cohort_plan in (plan.duplicates, plan.discharges, plan.deaths):
            self.stdout.write(
                f"cohort={cohort_plan.cohort} eligible={cohort_plan.total} "
                f"bounded={len(cohort_plan.items)}"
            )
        self.stdout.write(f"manual_review items={sum(plan.manual_review.values())}")
        for reason, count in sorted(plan.manual_review.items()):
            self.stdout.write(f"manual_review reason={reason} count={count}")
        self.stdout.write(f"plan_items={len(plan.items)}")
