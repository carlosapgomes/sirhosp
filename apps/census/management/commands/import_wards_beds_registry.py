from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.census.models import Bed, Ward
from apps.census.services import parse_wards_beds_pdf_text


class Command(BaseCommand):
    help = (
        "Importa o cadastro de unidades e leitos a partir do PDF "
        "'Cadastro de leitos por Clínica / Unidade' do sistema fonte."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=str,
            required=True,
            help="Caminho do arquivo PDF de leitos cadastrados.",
        )
        parser.add_argument(
            "--text-mode",
            action="store_true",
            default=False,
            help="Lê o arquivo como texto puro (para testes).",
        )
        parser.add_argument(
            "--filter-name",
            type=str,
            default="",
            help=(
                "Importa apenas unidades cujo nome contém este texto "
                "(ex: 'HGRS' para filtrar só o hospital HGRS)."
            ),
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"])

        if options["text_mode"]:
            pdf_text = input_path.read_text(encoding="utf-8")
        else:
            try:
                import fitz

                doc = fitz.open(str(input_path))
                pdf_text = "\n".join(page.get_text() for page in doc)
                doc.close()
            except ImportError:
                self.stderr.write(
                    self.style.ERROR(
                        "PyMuPDF (fitz) não está instalado. "
                        "Instale com: uv add pymupdf"
                    )
                )
                return
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(f"Erro ao ler PDF: {exc}")
                )
                return

        units_data = parse_wards_beds_pdf_text(pdf_text)

        if not units_data:
            self.stderr.write(
                self.style.ERROR(
                    "Nenhuma unidade encontrada no PDF. "
                    "Verifique o formato do arquivo."
                )
            )
            return

        filter_name = options["filter_name"]
        if filter_name:
            units_data = [
                u for u in units_data
                if filter_name.lower() in u["name"].lower()
            ]
            if not units_data:
                self.stderr.write(
                    self.style.ERROR(
                        f"Nenhuma unidade com '{filter_name}' no nome."
                    )
                )
                return

        wards_created = 0
        wards_updated = 0
        beds_created = 0
        beds_updated = 0

        with transaction.atomic():
            for unit_data in units_data:
                ward, w_created = Ward.objects.update_or_create(
                    source_code=unit_data["source_code"],
                    defaults={"name": unit_data["name"]},
                )
                if w_created:
                    wards_created += 1
                else:
                    wards_updated += 1

                for bed_data in unit_data["beds"]:
                    bed, b_created = Bed.objects.update_or_create(
                        ward=ward,
                        code=bed_data["code"],
                        defaults={
                            "status": bed_data["status"],
                            "accommodation": bed_data["accommodation"],
                            "is_active": bed_data["is_active"],
                        },
                    )
                    if b_created:
                        beds_created += 1
                    else:
                        beds_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Importação concluída:\n"
                f"  Unidades: {wards_created} criadas, "
                f"{wards_updated} atualizadas\n"
                f"  Leitos: {beds_created} criados, "
                f"{beds_updated} atualizados\n"
                f"  Total de unidades: {len(units_data)}\n"
                f"  Total de leitos: {beds_created + beds_updated}"
            )
        )
