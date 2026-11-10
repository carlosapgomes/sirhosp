"""Current inpatients photo resolution (design D3, D10).

The photo always equals one completed census cycle: the latest
``census_extraction`` run with ``status = succeeded`` that holds at least one
snapshot row, ordered by the minimum row ``captured_at`` descending and then by
run primary key descending. ``finished_at`` never decides. Rows are read by
that run and ordered by ``setor``, ``setor_codigo``, ``leito``, ``prontuario``
and row primary key ascending, so two cycles are never mixed and legacy rows
without a run never surface. The served run primary key travels as
``cycle_seq`` so consumers can order and deduplicate photos without relying on
wall-clock time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from django.db.models import Min

from apps.census.models import CensusSnapshot
from apps.ingestion.models import IngestionRun

CENSUS_EXTRACTION_INTENT = "census_extraction"
SUCCEEDED_STATUS = "succeeded"


@dataclass(frozen=True, slots=True)
class CurrentPhoto:
    """One completed census cycle as served upstream.

    ``cycle_seq`` is the served run primary key: equal
    (``captured_at``, ``cycle_seq``) pairs denote the same photo, and a later
    cycle always carries the greater ``cycle_seq``.
    """

    captured_at: datetime
    cycle_seq: int
    rows: list[CensusSnapshot]


class InvalidPhotoRow(Exception):
    """A patient row violates the wire contract, so the whole photo is refused.

    Omitting the row would silently corrupt the consumer roster and inventing a
    name is forbidden, so one bad row fails the photo closed (D10).
    """


def latest_eligible_run() -> IngestionRun | None:
    """Latest succeeded census cycle holding at least one snapshot row."""
    return (
        IngestionRun.objects.filter(
            intent=CENSUS_EXTRACTION_INTENT,
            status=SUCCEEDED_STATUS,
        )
        .annotate(photo_captured_at=Min("census_snapshots__captured_at"))
        .filter(photo_captured_at__isnull=False)
        .order_by("-photo_captured_at", "-pk")
        .first()
    )


def photo_captured_at(run: IngestionRun) -> datetime:
    """Capture timestamp shared by every row of the cycle (photo identity)."""
    captured_at = run.census_snapshots.aggregate(value=Min("captured_at"))["value"]
    if captured_at is None:
        raise InvalidPhotoRow("eligible run lost its rows")
    return cast(datetime, captured_at)


def patient_rows(run: IngestionRun) -> list[CensusSnapshot]:
    """Patient rows of one cycle in wire order; a blank name refuses the photo."""
    rows = list(
        CensusSnapshot.objects.filter(ingestion_run_id=run.pk)
        .exclude(prontuario="")
        .order_by("setor", "setor_codigo", "leito", "prontuario", "pk")
    )
    for row in rows:
        if not row.nome.strip():
            raise InvalidPhotoRow("patient row without a name")
    return rows


def build_current_photo() -> CurrentPhoto | None:
    """``CurrentPhoto`` of the latest eligible cycle, or ``None`` when absent."""
    run = latest_eligible_run()
    if run is None:
        return None
    return CurrentPhoto(
        captured_at=photo_captured_at(run),
        cycle_seq=run.pk,
        rows=patient_rows(run),
    )
