from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.ingestion.services import queue_admissions_only_run


class Command(BaseCommand):
    help = (
        "Lê o CSV gerado por report_suspected_stale_inpatients e "
        "enfileira um IngestionRun do tipo admissions_only para cada "
        "paciente. O worker process_ingestion_runs --loop processa "
        "essas runs e atualiza os dados de admissão (incluindo "
        "discharge_date) a partir do sistema fonte."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=str,
            default="/tmp/suspected_stale_inpatients.csv",
            help="Caminho do CSV de entrada (default: /tmp/suspected_stale_inpatients.csv).",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])

        if not input_path.is_file():
            self.stderr.write(
                self.style.ERROR(
                    f"Arquivo não encontrado: {input_path}\n"
                    f"Execute report_suspected_stale_inpatients primeiro."
                )
            )
            return

        with input_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            self.stdout.write("CSV vazio — nenhum paciente para atualizar.")
            return

        enqueued = 0
        seen: set[str] = set()

        for row in rows:
            prontuario = row.get("prontuario", "").strip()
            if not prontuario:
                continue
            if prontuario in seen:
                continue
            seen.add(prontuario)

            try:
                run = queue_admissions_only_run(patient_record=prontuario)
                self.stdout.write(
                    f"  Enfileirado: {prontuario} "
                    f"(Run #{run.pk}, intent=admissions_only)"
                )
                enqueued += 1
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"  Erro ao enfileirar {prontuario}: {exc}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"{enqueued} pacientes enfileirados para atualização de admissão.\n"
                f"O worker process_ingestion_runs --loop irá processá-los.\n"
                f"Após o processamento, execute report_suspected_stale_inpatients "
                f"novamente para gerar o CSV atualizado."
            )
        )
