from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Exists, Max, OuterRef, Subquery
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.clinical_docs.models import ClinicalEvent
from apps.patients.models import Admission


class Command(BaseCommand):
    help = (
        "Gera CSV de admissões ativas (sem alta) cujo paciente não possui "
        "nenhuma evolução registrada nas últimas N horas (default: 72h)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=72,
            help="Horas sem evolução para considerar suspeito (default: 72).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="/tmp/suspected_stale_inpatients.csv",
            help="Caminho do arquivo CSV de saída (default: /tmp/).",
        )
        parser.add_argument(
            "--include-census-present",
            action="store_true",
            default=False,
            help=(
                "Inclui também pacientes que ainda aparecem no último "
                "censo como ocupados (mostra todos: dentro e fora)."
            ),
        )
        parser.add_argument(
            "--only-census-present",
            action="store_true",
            default=False,
            help=(
                "Lista APENAS pacientes que estão no censo mas sem "
                "evolução há N horas — relatório para enviar à TI do hospital."
            ),
        )

    def handle(self, *args, **options):
        now = timezone.now()
        stale_hours = options["hours"]
        cutoff = now - timedelta(hours=stale_hours)
        include_census = options["include_census_present"]

        # 1) Para cada paciente, identificar a admissão mais recente
        latest_admission_qs = Admission.objects.filter(
            patient=OuterRef("patient")
        ).order_by("-admission_date", "-id")

        latest_discharge = Subquery(
            latest_admission_qs.values("discharge_date")[:1]
        )

        # 2) Admissões ativas cuja admissão mais recente do paciente
        #    também é sem alta (evita falsos positivos com admissões
        #    antigas órfãs de discharge_date)
        active = Admission.objects.filter(
            discharge_date__isnull=True,
        ).annotate(
            latest_patient_discharge=latest_discharge,
        ).filter(
            latest_patient_discharge__isnull=True,
        )

        # 3) Existe alguma evolução nesta admissão nos últimos 72h?
        recent_event_exists = Exists(
            ClinicalEvent.objects.filter(
                admission=OuterRef("pk"),
                happened_at__gte=cutoff,
            )
        )

        # 4) Última evolução desta admissão (para informação contextual)
        last_event_qs = ClinicalEvent.objects.filter(
            admission=OuterRef("pk")
        ).order_by("-happened_at")

        # 5) Dados do censo mais recente (setor/leito/especialidade atuais)
        latest_census_at = CensusSnapshot.objects.aggregate(
            m=Max("captured_at")
        )["m"]

        census_qs = CensusSnapshot.objects.none()
        in_census_exists = Exists(
            CensusSnapshot.objects.none()
        )
        if latest_census_at is not None:
            census_qs = CensusSnapshot.objects.filter(
                captured_at=latest_census_at,
                bed_status=BedStatus.OCCUPIED,
                prontuario=OuterRef("patient__patient_source_key"),
            )
            in_census_exists = Exists(
                CensusSnapshot.objects.filter(
                    captured_at=latest_census_at,
                    bed_status=BedStatus.OCCUPIED,
                    prontuario=OuterRef("patient__patient_source_key"),
                )
            )

        # Monta queryset final: ativas SEM evento recente
        suspects = (
            active.select_related("patient")
            .annotate(
                has_recent_event=recent_event_exists,
                in_census=in_census_exists,
                last_happened_at=Subquery(
                    last_event_qs.values("happened_at")[:1]
                ),
                last_profession_type=Subquery(
                    last_event_qs.values("profession_type")[:1]
                ),
                census_setor=Subquery(census_qs.values("setor")[:1]),
                census_leito=Subquery(census_qs.values("leito")[:1]),
                census_especialidade=Subquery(
                    census_qs.values("especialidade")[:1]
                ),
            )
            .filter(has_recent_event=False)
        )

        # 6) Filtro por presença no censo
        if options["only_census_present"]:
            suspects = suspects.filter(in_census=True)
        elif not include_census:
            suspects = suspects.filter(in_census=False)

        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "nome",
                    "prontuario",
                    "data_internacao",
                    "setor",
                    "leito",
                    "especialidade",
                    "esta_no_censo",
                    "ultima_evolucao_em",
                    "horas_desde_ultima_evolucao",
                    "profissao_ultima_evolucao",
                    "status_suspeita",
                ],
            )
            writer.writeheader()

            count = 0
            seen_patients: set[int] = set()
            for adm in suspects.order_by("patient__name", "id"):
                if adm.patient_id in seen_patients:
                    continue
                seen_patients.add(adm.patient_id)
                last = adm.last_happened_at
                if last is None:
                    hours_since = ""
                    status = f"SEM_EVOLUCAO_{stale_hours}H"
                    last_str = ""
                else:
                    hours_since = int((now - last).total_seconds() // 3600)
                    status = f"STALE_{stale_hours}H"
                    last_str = last.isoformat()

                data_internacao = (
                    adm.admission_date.strftime("%d/%m/%Y")
                    if adm.admission_date
                    else ""
                )
                writer.writerow(
                    {
                        "nome": adm.patient.name,
                        "prontuario": adm.patient.patient_source_key,
                        "data_internacao": data_internacao,
                        "setor": adm.census_setor or adm.ward,
                        "leito": adm.census_leito or adm.bed,
                        "especialidade": adm.census_especialidade or "",
                        "esta_no_censo": "sim" if adm.in_census else "não",
                        "ultima_evolucao_em": last_str,
                        "horas_desde_ultima_evolucao": hours_since,
                        "profissao_ultima_evolucao": (
                            adm.last_profession_type or ""
                        ),
                        "status_suspeita": status,
                    }
                )
                count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Relatório gerado com {count} pacientes: {output_path}"
            )
        )
