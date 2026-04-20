from django.core.management.base import BaseCommand

from apps.ingestion.services import ingest_evolution


class Command(BaseCommand):
    help = "Run on-demand ingestion of clinical evolutions (Slice S2)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--patient-source-key",
            type=str,
            required=True,
            help="External patient identifier to ingest.",
        )
        parser.add_argument(
            "--admission-key",
            type=str,
            required=True,
            help="External admission key to ingest.",
        )
        parser.add_argument(
            "--content-text",
            type=str,
            default="Test evolution content.",
            help="Clinical content text for the evolution.",
        )
        parser.add_argument(
            "--author-name",
            type=str,
            default="DR. TEST",
            help="Author name for the evolution.",
        )
        parser.add_argument(
            "--happened-at",
            type=str,
            default="2026-04-19 08:00:00",
            help="When the event happened (naive datetime).",
        )
        parser.add_argument(
            "--profession-type",
            type=str,
            default="medica",
            help="Profession type of the author.",
        )

    def handle(self, *args, **options):
        evo = {
            "patient_source_key": options["patient_source_key"],
            "patient_name": options["patient_source_key"],  # minimal
            "admission_key": options["admission_key"],
            "source_system": "tasy",
            "happened_at": options["happened_at"],
            "signed_at": None,
            "author_name": options["author_name"],
            "profession_type": options["profession_type"],
            "content_text": options["content_text"],
            "signature_line": "",
        }

        result = ingest_evolution(
            [evo],
            parameters={
                "patient_source_key": options["patient_source_key"],
                "admission_key": options["admission_key"],
            },
        )

        run = result["run"]
        self.stdout.write(
            f"Run #{run.pk} [{run.status}] "
            f"processed={run.events_processed} "
            f"created={run.events_created} "
            f"skipped={run.events_skipped} "
            f"revised={run.events_revised}"
        )
        if run.error_message:
            self.stderr.write(f"Error: {run.error_message}")
