from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.census.services import process_census_snapshot


class Command(BaseCommand):
    help = "Process latest census snapshot: create/update Patients and enqueue admission sync runs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            type=int,
            default=None,
            help="Process a specific ingestion run ID (default: most recent).",
        )

    def handle(self, *args, **options):
        run_id: int | None = options["run_id"]

        result = process_census_snapshot(run_id=run_id)

        self.stdout.write(
            self.style.SUCCESS(
                f"Census snapshot processed:\n"
                f"  Batch ID:                   {result['batch_id']}\n"
                f"  Patients total:             {result['patients_total']}\n"
                f"  Patients new:               {result['patients_new']}\n"
                f"  Patients updated:           {result['patients_updated']}\n"
                f"  Admissions runs enqueued:   {result['runs_enqueued']}\n"
                f"  Demographics runs enqueued: {result['demographics_runs_enqueued']}\n"
                f"  Skipped (no pront):         {result['patients_skipped']}"
            )
        )
