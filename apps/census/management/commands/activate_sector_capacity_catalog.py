from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.census.capacity_catalog import (
    CatalogConflictError,
    CatalogError,
    activate_sector_capacity_catalog,
)


class Command(BaseCommand):
    help = (
        "Valida um catálogo completo de capacidades de setores e o publica "
        "para uma data efetiva estritamente futura em America/Bahia. "
        "Use --dry-run para validar e exibir totais sem persistir nada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=str,
            required=True,
            help="Caminho do arquivo JSON do catálogo.",
        )
        parser.add_argument(
            "--effective-from",
            type=str,
            required=True,
            help=(
                "Data efetiva futura YYYY-MM-DD (estritamente após hoje "
                "em America/Bahia)."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Valida e exibe totais sem persistir nada.",
        )

    def handle(self, *args, **options):
        try:
            result = activate_sector_capacity_catalog(
                input_path=Path(options["input"]),
                effective_from=options["effective_from"],
                dry_run=options["dry_run"],
            )
        except CatalogConflictError as exc:
            raise CommandError(f"Conflito de catálogo: {exc}") from exc
        except CatalogError as exc:
            raise CommandError(f"Catálogo inválido: {exc}") from exc

        if options["dry_run"]:
            action = "validado (dry-run)"
        elif result.created:
            action = "publicado"
        else:
            action = "já publicado (idempotente)"

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo {action} para {result.effective_from}\n"
                f"  SHA-256: {result.document_sha256}\n"
                f"  grupos oficiais: {result.group_count}\n"
                f"  associações: {result.member_count}\n"
                f"  códigos-fonte distintos: {result.code_count}\n"
                f"  grupos com capacidade: {result.capacity_group_count}\n"
                f"  grupos standard: {result.standard_group_count}\n"
                f"  grupos unrated: {result.unrated_group_count}\n"
                f"  capacidade conhecida: {result.known_capacity}\n"
                f"  capacidade calculável: {result.calculable_capacity}"
            )
        )
