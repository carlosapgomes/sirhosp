"""Ingestion service: in-memory evolution ingestion with idempotency (Slice S2)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.db import models, transaction
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.core.profession_types import to_canonical_profession_type
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient

TZ_INSTITUTIONAL = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def compute_event_identity_key(evolution: dict[str, Any]) -> str:
    """Compute a deterministic identity key for an evolution event.

    Uses admission_key + happened_at + author_name to uniquely identify
    an event occurrence within the source system.
    """
    raw = (
        f"{evolution.get('source_system', 'tasy')}"
        f"|{evolution.get('admission_key', '')}"
        f"|{evolution.get('happened_at', '')}"
        f"|{evolution.get('author_name', '')}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_content_hash(content_text: str) -> str:
    """Compute SHA-256 hash of content for revision detection."""
    return hashlib.sha256(content_text.encode("utf-8")).hexdigest()


def _parse_naive_datetime(value: str | None) -> datetime | None:
    """Parse a naive datetime string and localize to institutional TZ."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_INSTITUTIONAL)
    return dt


def _upsert_patient(evolution: dict[str, Any], run: IngestionRun) -> Patient:
    """Create or update a Patient from evolution data."""
    source_key = evolution.get("patient_source_key", "")
    source_system = evolution.get("source_system", "tasy")
    new_name = evolution.get("patient_name", "").strip()
    new_name = " ".join(new_name.split())  # collapse whitespace

    patient, created = Patient.objects.get_or_create(
        source_system=source_system,
        patient_source_key=source_key,
        defaults={
            "name": new_name,
        },
    )
    if not created and patient.name != new_name:
        old_name = patient.name
        patient.name = new_name
        patient.save(update_fields=["name", "updated_at"])
        from apps.patients.models import PatientIdentifierHistory

        PatientIdentifierHistory.objects.create(
            patient=patient,
            identifier_type="name",
            old_value=old_name,
            new_value=new_name,
            ingestion_run=run,
        )
    return patient


def _upsert_admission(
    evolution: dict[str, Any],
    patient: Patient,
) -> Admission:
    """Create or update an Admission from evolution data."""
    admission_key = evolution.get("admission_key", "")
    source_system = evolution.get("source_system", "tasy")

    admission, created = Admission.objects.get_or_create(
        source_system=source_system,
        source_admission_key=admission_key,
        defaults={
            "patient": patient,
            "ward": evolution.get("ward", ""),
            "bed": evolution.get("bed", ""),
        },
    )
    if not created:
        # Update ward/bed if changed
        changed = False
        ward = evolution.get("ward", "")
        bed = evolution.get("bed", "")
        if ward and admission.ward != ward:
            admission.ward = ward
            changed = True
        if bed and admission.bed != bed:
            admission.bed = bed
            changed = True
        if changed:
            admission.save(update_fields=["ward", "bed", "updated_at"])
    return admission


def _persist_event(
    evolution: dict[str, Any],
    patient: Patient,
    admission: Admission,
    run: IngestionRun,
) -> tuple[ClinicalEvent | None, str]:
    """Persist a single clinical event with dedup.

    Returns (event_or_none, action) where action is
    'created', 'skipped', or 'revised'.
    """
    identity_key = compute_event_identity_key(evolution)
    content_text = evolution.get("content_text", "")
    content_hash = compute_content_hash(content_text)

    happened_at = _parse_naive_datetime(evolution.get("happened_at"))
    signed_at = _parse_naive_datetime(evolution.get("signed_at"))
    profession_type = to_canonical_profession_type(
        evolution.get("profession_type", "")
    )

    # Check for existing event with same identity key
    existing = ClinicalEvent.objects.filter(event_identity_key=identity_key).first()

    if existing is not None:
        if existing.content_hash == content_hash:
            # Exact duplicate — skip
            return None, "skipped"
        else:
            # Content changed — create revision
            event = ClinicalEvent.objects.create(
                admission=admission,
                patient=patient,
                ingestion_run=run,
                event_identity_key=identity_key,
                content_hash=content_hash,
                happened_at=happened_at or existing.happened_at,
                signed_at=signed_at,
                author_name=evolution.get("author_name", ""),
                profession_type=profession_type,
                content_text=content_text,
                signature_line=evolution.get("signature_line", ""),
                raw_payload_json=evolution,
            )
            return event, "revised"

    # New event
    event = ClinicalEvent.objects.create(
        admission=admission,
        patient=patient,
        ingestion_run=run,
        event_identity_key=identity_key,
        content_hash=content_hash,
        happened_at=happened_at or timezone.now(),
        signed_at=signed_at,
        author_name=evolution.get("author_name", ""),
        profession_type=profession_type,
        content_text=content_text,
        signature_line=evolution.get("signature_line", ""),
        raw_payload_json=evolution,
    )
    return event, "created"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def queue_ingestion_run(
    *,
    patient_record: str,
    start_date: str,
    end_date: str,
) -> IngestionRun:
    """Create an IngestionRun in queued state for async processing.

    Args:
        patient_record: Patient record identifier (prontuário).
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format.

    Returns:
        IngestionRun instance with status=queued.
    """
    return IngestionRun.objects.create(
        status="queued",
        parameters_json={
            "patient_record": patient_record,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


def ingest_evolution(
    evolutions: list[dict[str, Any]],
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest a batch of evolution dicts into the canonical model.

    Returns dict with:
        run: IngestionRun instance
        events_created: list of newly created ClinicalEvent
        created: count of created events
        skipped: count of skipped (duplicate) events
        revised: count of revised events
    """
    run = IngestionRun.objects.create(
        status="running",
        parameters_json=parameters or {},
    )

    events_created: list[ClinicalEvent] = []
    created = 0
    skipped = 0
    revised = 0

    try:
        for evo in evolutions:
            with transaction.atomic():
                patient = _upsert_patient(evo, run)
                admission = _upsert_admission(evo, patient)
                event, action = _persist_event(evo, patient, admission, run)

                if action == "created":
                    assert event is not None
                    events_created.append(event)
                    created += 1
                elif action == "skipped":
                    skipped += 1
                elif action == "revised":
                    assert event is not None
                    events_created.append(event)
                    revised += 1

        run.events_processed = len(evolutions)
        run.events_created = created
        run.events_skipped = skipped
        run.events_revised = revised
        run.status = "succeeded"
        run.finished_at = timezone.now()
        run.save()

    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save()

    return {
        "run": run,
        "events_created": events_created,
        "created": created,
        "skipped": skipped,
        "revised": revised,
    }


# ---------------------------------------------------------------------------
# S2 - Upsert de snapshot de internações com período
# ---------------------------------------------------------------------------


def upsert_admission_snapshot(
    patient: Patient,
    admissions_snapshot: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert a list of admission snapshots for a patient.

    Accepts admission period fields (`admission_start`, `admission_end`)
    when available.

    Policy for ward/bed:
    - Non-empty values always update.
    - Empty values never overwrite existing non-empty values.

    Args:
        patient: Patient instance to link admissions to.
        admissions_snapshot: List of admission dicts with fields:
            - admission_key: External admission identifier (required).
            - admission_start: Admission start datetime string (required).
            - admission_end: Admission end datetime string (optional, may be None).
            - ward: Ward name (optional, may be empty string).
            - bed: Bed identifier (optional, may be empty string).

    Returns:
        dict with "created" (int) and "updated" (int) counts.
    """
    created = 0
    updated = 0

    for item in admissions_snapshot:
        admission_key = item.get("admission_key", "")
        source_system = item.get("source_system", "tasy")

        admission_date = _parse_naive_datetime(item.get("admission_start"))
        discharge_date = _parse_naive_datetime(item.get("admission_end"))
        ward = item.get("ward", "") or ""
        bed = item.get("bed", "") or ""

        defaults: dict[str, Any] = {
            "patient": patient,
            "admission_date": admission_date,
            "discharge_date": discharge_date,
            "ward": ward,
            "bed": bed,
        }

        admission, was_created = Admission.objects.get_or_create(
            source_system=source_system,
            source_admission_key=admission_key,
            defaults=defaults,
        )

        if was_created:
            created += 1
        else:
            # Update mutable fields only when new values are non-empty
            changed = False

            if admission_date is not None and admission.admission_date != admission_date:
                admission.admission_date = admission_date
                changed = True
            if discharge_date is not None and admission.discharge_date != discharge_date:
                admission.discharge_date = discharge_date
                changed = True
            # ward/bed: only update with non-empty values
            if ward and admission.ward != ward:
                admission.ward = ward
                changed = True
            if bed and admission.bed != bed:
                admission.bed = bed
                changed = True

            if changed:
                admission.save(
                    update_fields=[
                        "admission_date",
                        "discharge_date",
                        "ward",
                        "bed",
                        "updated_at",
                    ]
                )
                updated += 1

    return {"created": created, "updated": updated}


# ---------------------------------------------------------------------------
# S2 - Fallback determinístico de associação evento -> internação
# ---------------------------------------------------------------------------


def resolve_admission_for_event(
    *,  # keyword-only
    admission_key: str,
    happened_at: datetime,
    patient: Patient | None,
) -> Admission:
    """Resolve the correct Admission for a clinical event.

    Resolution order:
    1. Direct match by admission_key (if valid/non-empty).
    2. Fallback by period: happened_at within [admission_date, discharge_date].
       If multiple matches, pick the admission with the latest admission_date.
    3. No period match: pick the nearest previous admission_date.
       If none exists, pick the nearest posterior admission_date.
    4. Final tiebreaker: source_admission_key ascending (lexicographic).

    Args:
        admission_key: The admission_key from the event (may be empty/invalid).
        happened_at: The datetime when the event occurred.
        patient: Patient instance to scope the search (required).

    Returns:
        The matched Admission instance.

    Raises:
        ValueError: If patient is None.
        Admission.DoesNotExist: If the patient has no admissions at all.
    """
    if patient is None:
        raise ValueError("patient is required to resolve admission")

    # 1. Direct match by admission_key
    if admission_key and admission_key.strip():
        admission = Admission.objects.filter(
            patient=patient,
            source_admission_key=admission_key.strip(),
        ).first()
        if admission is not None:
            return admission

    # 2. Fallback by period:
    # admission_date <= happened_at AND (discharge_date is null OR discharge_date >= happened_at)
    period_matches = list(
        Admission.objects.filter(patient=patient)
        .filter(
            models.Q(admission_date__lte=happened_at)
            & (
                models.Q(discharge_date__isnull=True)
                | models.Q(discharge_date__gte=happened_at)
            )
        )
        .order_by("-admission_date", "source_admission_key")
    )

    if period_matches:
        # Already sorted by -admission_date, then source_admission_key ascending
        return period_matches[0]

    # 3a. No period match: nearest previous (admission_date < happened_at)
    previous_admissions = list(
        Admission.objects.filter(patient=patient, admission_date__lt=happened_at)
        .order_by("-admission_date", "source_admission_key")
    )
    if previous_admissions:
        return previous_admissions[0]

    # 3b. No previous: nearest posterior (admission_date > happened_at)
    posterior_admissions = list(
        Admission.objects.filter(patient=patient, admission_date__gt=happened_at)
        .order_by("admission_date", "source_admission_key")
    )
    if posterior_admissions:
        return posterior_admissions[0]

    # 4. Final fallback: any admission (sorted by source_admission_key ascending)
    fallback = Admission.objects.filter(patient=patient).order_by(
        "source_admission_key"
    ).first()
    if fallback is not None:
        return fallback

    # No admissions at all for this patient
    raise Admission.DoesNotExist(
        f"No admission found for patient {patient.patient_source_key}"
    )
