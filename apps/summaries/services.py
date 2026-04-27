"""Summary services — business logic for progressive admission summaries.

APS-S2: queue_summary_run for on-demand enqueue.
"""

from __future__ import annotations

from datetime import date

from django.db import models

from apps.patients.models import Admission
from apps.summaries.models import SummaryRun

VALID_MODES = {"generate", "update", "regenerate"}


def queue_summary_run(
    *,
    admission: Admission,
    mode: str,
    requested_by: models.Model | None = None,
) -> SummaryRun:
    """Create a queued SummaryRun for an admission.

    Calculates target_end_date:
      - open admission (no discharge_date): today
      - closed admission: min(today, discharge_date)
    """
    today = date.today()

    if admission.discharge_date:
        discharge_date = admission.discharge_date.date()
        target_end_date = min(today, discharge_date)
    else:
        target_end_date = today

    run = SummaryRun.objects.create(
        admission=admission,
        requested_by=requested_by,
        mode=mode,
        target_end_date=target_end_date,
        status=SummaryRun.Status.QUEUED,
    )
    return run
