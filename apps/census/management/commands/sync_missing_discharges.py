from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Exists, Max, OuterRef, Subquery

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.services import queue_admissions_only_run
from apps.patients.models import Admission


class Command(BaseCommand):
    help = (
        "Enfileira atualização de admissão (admissions_only) para todos os "
        "pacientes cuja admissão mais recente não tem data de alta e que "
        "NÃO aparecem no último censo como ocupados — prováveis altas não "
        "sincronizadas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Apenas lista os pacientes, sem enfileirar.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Pacientes cuja admissão mais recente NÃO tem alta
        latest_adm = Admission.objects.filter(
            patient=OuterRef("patient")
        ).order_by("-admission_date", "-id")

        active = Admission.objects.filter(
            discharge_date__isnull=True,
        ).annotate(
            latest_discharge=Subquery(
                latest_adm.values("discharge_date")[:1]
            ),
        ).filter(
            latest_discharge__isnull=True,
        )

        # Pacientes que NÃO estão no último censo como ocupados
        latest_census_at = CensusSnapshot.objects.aggregate(
            m=Max("captured_at")
        )["m"]

        if latest_census_at is None:
            self.stderr.write(
                self.style.ERROR("Nenhum censo encontrado no banco.")
            )
            return

        in_census = Exists(
            CensusSnapshot.objects.filter(
                captured_at=latest_census_at,
                bed_status=BedStatus.OCCUPIED,
                prontuario=OuterRef("patient__patient_source_key"),
            )
        )

        missing = (
            active.select_related("patient")
            .annotate(in_census=in_census)
            .filter(in_census=False)
        )

        seen: set[int] = set()
        enqueued = 0

        for adm in missing.order_by("patient__name", "id"):
            if adm.patient_id in seen:
                continue
            seen.add(adm.patient_id)

            prontuario = adm.patient.patient_source_key
            if dry_run:
                self.stdout.write(
                    f"  {adm.patient.name} ({prontuario})"
                )
                continue

            try:
                run = queue_admissions_only_run(patient_record=prontuario)
                self.stdout.write(
                    f"  Enfileirado: {prontuario} "
                    f"(Run #{run.pk}) — {adm.patient.name}"
                )
                enqueued += 1
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"  Erro ao enfileirar {prontuario}: {exc}"
                    )
                )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{len(seen)} pacientes encontrados (dry-run)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{enqueued} pacientes enfileirados para atualização."
                )
            )
