"""RPSA-S10: daily aggregate-safe admission reconciliation integrity report.

Thin daily wrapper around the one shared read-only evaluation
(``evaluate_pipeline_health``) with the default configuration: it always
renders the reconciliation block and exits nonzero (``CommandError``) on
violations. It never enqueues work, calls the source or mutates clinical
state. Output carries only dates, ages, status-group names, counts and
bounds — never patient/admission/source identifiers, names, record
numbers or clinical text.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.management.commands.check_ingestion_pipeline_health import (
    format_violations,
    render_reconciliation_block,
)
from apps.ingestion.pipeline_health import (
    HealthConfig,
    evaluate_pipeline_health,
)


class Command(BaseCommand):
    help = (
        "Daily aggregate-safe admission reconciliation integrity report. "
        "Runs the shared pipeline-health evaluation with the default "
        "configuration; exit 0 when healthy, CommandError otherwise."
    )

    def handle(self, *args, **options):
        result = evaluate_pipeline_health(HealthConfig())
        healthy = "true" if result.healthy else "false"
        self.stdout.write(
            f"admission reconciliation integrity: healthy={healthy}"
        )
        render_reconciliation_block(self.stdout, result)
        if not result.healthy:
            raise CommandError(
                "admission reconciliation integrity: unhealthy "
                f"violations={format_violations(result)}"
            )
