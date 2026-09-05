"""Rebuild ``DailyDischargeCount`` from canonical effective hospital exits.

RPSA-S8: the aggregate is derived solely from canonical admissions
(``merged_into`` is null via the default manager) with ``discharge_date``
set whose latest reconciled ``ReconciliationEvent`` has exit type
``hospital_discharge`` (the ``saida_em`` provenance written by RPSA-S2).
Death exits and merged duplicates are excluded. Grouping uses the explicit
``America/Bahia`` local date — never an inherited default timezone.

Apply is the command default; ``--dry-run`` is the explicit opt-in that
reports before/after aggregates without mutating anything. The
post-extraction automatic refresh (RPSA-S7) calls this command with no
arguments and must keep applying. On apply, every affected date is
upserted with ``raw_data=[]`` so legacy patient-bearing rows leave
aggregate storage. Output is aggregate-only: dates and totals, never
patient identity.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db.models import CharField, Count, OuterRef, Subquery
from django.db.models.functions import TruncDate

from apps.discharges.models import DailyDischargeCount
from apps.patients.models import (
    EXIT_HOSPITAL_DISCHARGE,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    ReconciliationEvent,
)

BAHIA_TZ = ZoneInfo("America/Bahia")


def _canonical_exit_day_counts() -> dict:
    """Return ``{bahia_local_date: canonical_exit_count}`` in one query.

    The default manager already excludes admissions merged into another
    canonical row. The correlated subquery reads the latest reconciled
    audit event per admission; admissions without reconciled
    ``hospital_discharge`` provenance are not counted.
    """
    latest_reconciled_exit_type = (
        ReconciliationEvent.objects.filter(
            admission=OuterRef("pk"),
            status=RECONCILIATION_STATUS_RECONCILED,
        )
        .order_by("-created_at", "-pk")
        .values("exit_type")[:1]
    )
    rows = (
        Admission.objects.filter(discharge_date__isnull=False)
        .annotate(
            latest_exit_type=Subquery(
                latest_reconciled_exit_type,
                output_field=CharField(),
            )
        )
        .filter(latest_exit_type=EXIT_HOSPITAL_DISCHARGE)
        .annotate(exit_day=TruncDate("discharge_date", tzinfo=BAHIA_TZ))
        .values("exit_day")
        .annotate(total=Count("pk"))
        .order_by("exit_day")
    )
    return {row["exit_day"]: row["total"] for row in rows}


class Command(BaseCommand):
    help = (
        "Rebuild DailyDischargeCount from canonical effective hospital "
        "exits grouped by America/Bahia local date. Apply is the default; "
        "--dry-run previews the before/after aggregates without mutating."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report before/after aggregates without mutating anything.",
        )

    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]

        canonical_counts = _canonical_exit_day_counts()
        existing_rows = {
            row.date: row for row in DailyDischargeCount.objects.all()
        }
        affected_dates = sorted(set(canonical_counts) | set(existing_rows))

        mode_prefix = "[dry-run] " if dry_run else ""
        total_before = 0
        total_after = 0

        for day in affected_dates:
            row = existing_rows.get(day)
            before = row.count if row is not None else 0
            after = canonical_counts.get(day, 0)
            has_raw_data = bool(row.raw_data) if row is not None else False
            total_before += before
            total_after += after
            if before == after and not has_raw_data:
                continue  # already canonical and clean: idempotent no-op
            before_label = str(before) if row is not None else "absent"
            raw_note = " [raw_data present]" if has_raw_data else ""
            self.stdout.write(
                f"{day.isoformat()}: {before_label} -> {after}{raw_note}"
            )
            if not dry_run:
                DailyDischargeCount.objects.update_or_create(
                    date=day,
                    defaults={"count": after, "raw_data": []},
                )

        if not affected_dates:
            self.stdout.write("No discharge data found.")
            return

        self.stdout.write(
            f"{mode_prefix}Affected {len(affected_dates)} date(s), "
            f"{affected_dates[0].isoformat()}..{affected_dates[-1].isoformat()}; "
            f"aggregate totals before={total_before} after={total_after}."
        )
        if dry_run:
            self.stdout.write("[dry-run] No changes applied.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Applied canonical exit counts to {len(affected_dates)} "
                    "date(s); raw_data cleared on upserted dates."
                )
            )
