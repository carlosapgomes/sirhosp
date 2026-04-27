"""Worker that processes queued SummaryRuns (APS-S4).

Picks up runs in 'queued' state using select_for_update(skip_locked=True),
delegates execution to execute_summary_run(), and transitions runs to
'succeeded' on success.

Supports:
  - One-shot mode: process all queued runs once and exit.
  - Continuous loop mode: poll and process until interrupted.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.summaries.models import SummaryRun
from apps.summaries.services import execute_summary_run


class Command(BaseCommand):
    help = "Process queued summary runs (async worker without Celery)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously, processing queued runs as they appear.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=5,
            help="Seconds to sleep when no queued runs are found (default: 5).",
        )

    def handle(self, *args, **options):
        loop: bool = options["loop"]
        sleep_seconds: int = options["sleep_seconds"]

        if loop:
            self._run_loop(sleep_seconds=sleep_seconds)
        else:
            self._process_once()

    def _run_loop(self, sleep_seconds: int) -> None:
        """Continuously poll and process queued runs until interrupted."""
        import signal
        import sys

        def _signal_handler(signum, frame):
            self.stdout.write(
                "\nReceived signal, shutting down worker gracefully..."
            )
            sys.exit(0)

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        self.stdout.write(
            self.style.SUCCESS(
                f"Summary worker started in continuous mode "
                f"(sleep={sleep_seconds}s)."
            )
        )

        while True:
            try:
                runs = SummaryRun.objects.filter(status="queued")
                count = runs.count()
            except (OperationalError, ProgrammingError) as exc:
                self.stderr.write(
                    self.style.WARNING(
                        f"[{timezone.now():%H:%M:%S}] Worker startup check "
                        f"failed ({exc.__class__.__name__}): {exc}. "
                        f"Retrying in {sleep_seconds}s..."
                    )
                )
                time.sleep(sleep_seconds)
                continue

            if count == 0:
                self.stdout.write(
                    f"[{timezone.now():%H:%M:%S}] No queued runs, "
                    f"sleeping {sleep_seconds}s..."
                )
                time.sleep(sleep_seconds)
                continue

            self.stdout.write(
                f"[{timezone.now():%H:%M:%S}] Found {count} queued run(s), "
                f"processing..."
            )
            # Claim and process runs atomically (safe for multiple workers)
            while True:
                with transaction.atomic():
                    run = (
                        SummaryRun.objects.select_for_update(
                            skip_locked=True
                        )
                        .select_related("admission__patient")
                        .filter(status="queued")
                        .order_by("pk")
                        .first()
                    )
                    if run is None:
                        break
                    # Claim: transition to running (but execute_summary_run
                    # will also set running — keep the claim simple here)
                    run.status = SummaryRun.Status.RUNNING
                    run.save(update_fields=["status"])

                # Process outside the atomic block so each run is
                # independently handled.
                try:
                    execute_summary_run(run)
                    self.stdout.write(
                        f"  Run #{run.pk} succeeded "
                        f"(mode={run.mode}, "
                        f"chunks={run.total_chunks})"
                    )
                except Exception as exc:
                    self.stderr.write(f"  Run #{run.pk} failed: {exc}")
                    run.status = SummaryRun.Status.FAILED
                    run.error_message = str(exc)
                    run.finished_at = timezone.now()
                    run.save(
                        update_fields=[
                            "status",
                            "error_message",
                            "finished_at",
                        ]
                    )

    def _process_once(self) -> None:
        """Process all queued runs once and exit."""
        runs = SummaryRun.objects.filter(status="queued")
        count = runs.count()

        if count == 0:
            self.stdout.write("No queued summary runs to process.")
            return

        self.stdout.write(f"Processing {count} queued summary run(s)...")

        # Claim and process runs atomically (safe for multiple workers)
        while True:
            with transaction.atomic():
                run = (
                    SummaryRun.objects.select_for_update(
                        skip_locked=True
                    )
                    .select_related("admission__patient")
                    .filter(status="queued")
                    .order_by("pk")
                    .first()
                )
                if run is None:
                    break
                # Claim before releasing the lock
                run.status = SummaryRun.Status.RUNNING
                run.save(update_fields=["status"])

            # Process outside atomic block
            try:
                execute_summary_run(run)
                self.stdout.write(
                    f"  Run #{run.pk} succeeded "
                    f"(mode={run.mode}, chunks={run.total_chunks})"
                )
            except Exception as exc:
                self.stderr.write(f"  Run #{run.pk} failed: {exc}")
                run.status = SummaryRun.Status.FAILED
                run.error_message = str(exc)
                run.finished_at = timezone.now()
                run.save(
                    update_fields=["status", "error_message", "finished_at"]
                )

        self.stdout.write(self.style.SUCCESS("Done."))
