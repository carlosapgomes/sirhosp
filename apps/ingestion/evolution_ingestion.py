"""Shared evolution ingestion service (PSW-S7).

Extracts the current worker's ``_ingest_evolutions`` behavior into a shared
service that both the current and persistent-session workers can call.

Preserves:
- Patient upsert behavior via ``_upsert_patient``.
- Deterministic admission resolution by ``admission_key`` and ``happened_at``.
- Fallback admission upsert when resolution fails.
- ``_persist_event`` behavior (dedup, revision detection).
- created/skipped/revised counters.
- Transaction boundaries (one per evolution).
- Timezone handling for naive ``happened_at`` values.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.ingestion.models import IngestionRun
from apps.ingestion.services import (
    _persist_event,
    _upsert_admission,
    _upsert_patient,
    resolve_admission_for_event,
)
from apps.patients.models import Patient

TZ_INSTITUTIONAL = ZoneInfo("America/Sao_Paulo")


def ingest_evolutions(
    evolutions: list[dict[str, Any]],
    run: IngestionRun,
    patient: Patient,
) -> tuple[int, int, int]:
    """Ingest a list of evolution dicts, returning (created, skipped, revised).

    For each evolution, admission is resolved via ``admission_key`` direct hit
    or by period-based fallback. Uses ``transaction.atomic`` per evolution to
    ensure consistency.

    Args:
        evolutions: List of evolution dicts as returned by the extractor.
        run: The ``IngestionRun`` this ingestion belongs to.
        patient: The ``Patient`` instance (already upserted in previous steps).

    Returns:
        A tuple ``(created, skipped, revised)`` with event counters.
    """
    created = 0
    skipped = 0
    revised = 0

    for evo in evolutions:
        with transaction.atomic():
            # Ensure patient exists (already upserted in admissions step)
            _patient = _upsert_patient(evo, run)

            # Resolve admission deterministically (Slice S2 fallback)
            admission_key = evo.get("admission_key", "")
            happened_at_str = evo.get("happened_at", "")
            if happened_at_str:
                happened_at = datetime.fromisoformat(happened_at_str)
                if happened_at.tzinfo is None:
                    happened_at = happened_at.replace(
                        tzinfo=TZ_INSTITUTIONAL
                    )
            else:
                happened_at = timezone.now()

            try:
                admission = resolve_admission_for_event(
                    admission_key=admission_key,
                    happened_at=happened_at,
                    patient=patient,
                )
            except Exception:
                # Fallback: upsert from evolution data (legacy behaviour)
                admission = _upsert_admission(evo, patient)

            _event, action = _persist_event(evo, patient, admission, run)

            if action == "created":
                created += 1
            elif action == "skipped":
                skipped += 1
            elif action == "revised":
                revised += 1

    return created, skipped, revised
