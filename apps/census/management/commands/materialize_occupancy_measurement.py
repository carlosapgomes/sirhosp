from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.census.occupancy import (
    OccupancyMaterializationError,
    materialize_occupancy_measurement,
)


class Command(BaseCommand):
    help = (
        "Materialize one immutable occupancy-v1 measurement for one explicit "
        "completed census extraction run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            type=int,
            required=True,
            help="Completed census_extraction IngestionRun ID.",
        )

    def handle(self, *args, **options):
        try:
            result = materialize_occupancy_measurement(run_id=options["run_id"])
        except OccupancyMaterializationError as exc:
            raise CommandError(str(exc)) from exc

        if result.measurement is None:
            self.stdout.write("pre_activation: no occupancy measurement created")
            return

        self.stdout.write(
            f"{result.status}: occupancy measurement "
            f"{result.measurement.pk} for run {options['run_id']}"
        )
