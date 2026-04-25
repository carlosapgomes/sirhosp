from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.census.models import CensusSnapshot
from apps.census.services import parse_census_csv
from apps.ingestion.models import IngestionRun


class Command(BaseCommand):
    help = "Run census extraction script and persist snapshot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--headless",
            action="store_true",
            default=True,
            help="Run Playwright in headless mode (default: True).",
        )
        parser.add_argument(
            "--no-headless",
            dest="headless",
            action="store_false",
            help="Run Playwright with visible browser.",
        )
        parser.add_argument(
            "--max-setores",
            type=int,
            default=0,
            help="Limit sectors (0 = all).",
        )

    def handle(self, *args, **options):
        headless: bool = options["headless"]
        max_setores: int = options["max_setores"]

        # Path to the extract_census.py script
        script_path = (
            Path(__file__).resolve().parents[4]
            / "automation"
            / "source_system"
            / "current_inpatients"
            / "extract_census.py"
        )

        if not script_path.exists():
            self.stderr.write(f"Script not found: {script_path}")
            sys.exit(1)

        # Create temp directory for output
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Build subprocess command
            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir",
                str(tmpdir_path),
            ]
            if headless:
                cmd.append("--headless")
            if max_setores > 0:
                cmd.extend(["--max-setores", str(max_setores)])

            self.stdout.write("Running census extraction...")
            self.stdout.write(f"  Script: {script_path}")

            # Create IngestionRun to track this execution
            run = IngestionRun.objects.create(
                status="running",
                intent="census_extraction",
                started_at=timezone.now(),
            )

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=1800,  # 30 minutes max
                )
            except subprocess.TimeoutExpired as exc:
                run.status = "failed"
                run.error_message = f"Timeout: {exc}"
                run.finished_at = timezone.now()
                run.save()
                self.stderr.write(f"Census extraction timed out: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                run.status = "failed"
                run.error_message = (
                    f"Exit code {result.returncode}: {result.stderr[:500]}"
                )
                run.finished_at = timezone.now()
                run.save()
                self.stderr.write(result.stderr)
                sys.exit(1)

            # Find the CSV file in output dir
            csv_files = list(tmpdir_path.glob("censo-*.csv"))
            if not csv_files:
                # Try to find any CSV
                csv_files = list(tmpdir_path.glob("*.csv"))

            if not csv_files:
                run.status = "failed"
                run.error_message = "No CSV output found after extraction."
                run.finished_at = timezone.now()
                run.save()
                self.stderr.write("No CSV output found.")
                sys.exit(1)

            csv_path = csv_files[0]
            self.stdout.write(f"  CSV output: {csv_path}")

            # Parse CSV and classify bed status
            parsed_rows = parse_census_csv(csv_path)
            self.stdout.write(f"  Rows parsed: {len(parsed_rows)}")

            # Bulk create CensusSnapshot rows
            captured_at = timezone.now()
            snapshots = [
                CensusSnapshot(
                    captured_at=captured_at,
                    ingestion_run=run,
                    setor=row["setor"],
                    leito=row["leito"],
                    prontuario=row["prontuario"],
                    nome=row["nome"],
                    especialidade=row["especialidade"],
                    bed_status=row["bed_status"],
                )
                for row in parsed_rows
            ]

            CensusSnapshot.objects.bulk_create(snapshots)
            self.stdout.write(f"  Snapshots persisted: {len(snapshots)}")

            # Update run status
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Census extraction complete. "
                    f"{len(snapshots)} rows persisted."
                )
            )
