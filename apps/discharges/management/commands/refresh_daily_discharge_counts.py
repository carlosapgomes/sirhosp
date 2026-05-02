"""Management command to refresh DailyDischargeCount from Admission data.

Groups Admission.discharge_date by day (America/Bahia timezone) and
upserts counts into DailyDischargeCount.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import TruncDate

from apps.discharges.models import DailyDischargeCount
from apps.patients.models import Admission


class Command(BaseCommand):
    help = (
        "Aggregate Admission.discharge_date by day and upsert "
        "into DailyDischargeCount."
    )

    def handle(self, *args, **options):
        # Count unique patients discharged per day, not total admission
        # records (a patient may have duplicate Admission rows due to
        # volatile admission keys from the source system).
        counts = (
            Admission.objects
            .filter(discharge_date__isnull=False)
            .annotate(day=TruncDate("discharge_date"))
            .values("day")
            .annotate(count=Count("patient_id", distinct=True))
            .order_by("day")
        )

        updated = 0
        for entry in counts:
            DailyDischargeCount.objects.update_or_create(
                date=entry["day"],
                defaults={"count": entry["count"]},
            )
            updated += 1

        if updated == 0:
            self.stdout.write("No discharge data found.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {updated} daily discharge count(s)."
                )
            )
