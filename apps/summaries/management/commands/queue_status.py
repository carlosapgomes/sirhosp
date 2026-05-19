"""Show queue status across all async workers (ingestion + summaries).

Usage:
    python manage.py queue_status
    python manage.py queue_status --watch  # refresh every 5s
"""

import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show queued/running/succeeded/failed counts for all async queues."

    def add_arguments(self, parser):
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Refresh every 5 seconds until interrupted.",
        )

    def handle(self, *args, **options):
        watch: bool = options["watch"]

        if watch:
            self._watch_loop()
        else:
            self._print_once()

    def _print_once(self) -> None:
        self._print_status()

    def _watch_loop(self) -> None:
        self.stdout.write("Queue monitor — Ctrl+C to stop\n")
        try:
            while True:
                self._print_status()
                time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write("\nStopped.")

    def _print_status(self) -> None:
        from django.db.models import Count

        from apps.ingestion.models import IngestionRun
        from apps.summaries.models import SummaryRun

        # Clear screen for watch mode
        print("\033[2J\033[H", end="")

        self.stdout.write(self.style.SUCCESS("=" * 55))
        self.stdout.write(
            self.style.SUCCESS("  QUEUE STATUS")
        )
        self.stdout.write(self.style.SUCCESS("=" * 55))

        # --- Ingestion queue ---
        self.stdout.write("\n  📥 INGESTÃO")
        self.stdout.write("  " + "-" * 30)
        for status in ["queued", "running", "succeeded", "partial", "failed"]:
            count = IngestionRun.objects.filter(status=status).count()
            icon = {
                "queued": "⏳",
                "running": "🔄",
                "succeeded": "✅",
                "partial": "⚠️",
                "failed": "❌",
            }.get(status, "•")
            self.stdout.write(f"    {icon} {status:11s}: {count:>6}")

        # Breakdown by intent (queued only)
        queued_ingestion = (
            IngestionRun.objects.filter(status="queued")
            .values("intent")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        if queued_ingestion:
            self.stdout.write("    ── queued por tipo:")
            for row in queued_ingestion:
                self.stdout.write(
                    f"       {row['intent']:25s}: {row['n']:>4}"
                )

        # --- Summary queue ---
        self.stdout.write("\n  📝 SUMÁRIOS")
        self.stdout.write("  " + "-" * 30)
        for status in ["queued", "running", "succeeded", "partial", "failed"]:
            count = SummaryRun.objects.filter(status=status).count()
            icon = {
                "queued": "⏳",
                "running": "🔄",
                "succeeded": "✅",
                "partial": "⚠️",
                "failed": "❌",
            }.get(status, "•")
            self.stdout.write(f"    {icon} {status:11s}: {count:>6}")

        # Breakdown by pipeline_type (queued only)
        queued_summaries = (
            SummaryRun.objects.filter(status="queued")
            .values("pipeline_type")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        if queued_summaries:
            self.stdout.write("    ── queued por pipeline:")
            for row in queued_summaries:
                self.stdout.write(
                    f"       {row['pipeline_type']:25s}: {row['n']:>4}"
                )

        self.stdout.write("")
