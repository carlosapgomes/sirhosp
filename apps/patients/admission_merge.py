"""Source-confirmed Admission merge and rollback (RPSA-S4).

Deterministic merge/rollback after source confirmation only: a fresh
admissions snapshot must show exactly one episode for the patient and
local admission date before any merge is eligible, and the same
confirmation fingerprint is re-validated under row locks before any
mutation. The oldest primary key always wins; the newer row is marked
``merged_into`` and never deleted; every inventoried reverse relation of
``Admission`` receives an explicit disposition from the transfer
registry; one append-only operation audit records the structural
before/after state required for rollback — never patient identity.

Runtime wiring (review UI, backfill cohorts) arrives in later slices;
nothing here calls the production source.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from datetime import timezone as dt_timezone
from typing import Optional

from django.db import transaction

from apps.patients.models import (
    Admission,
    AdmissionMergeOperation,
    AdmissionSourceAlias,
)
from apps.patients.services import ensure_admission_alias

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Disposition and decision taxonomies
# ---------------------------------------------------------------------------

RELATION_DISPOSITION_REPOINT = "repoint-to-canonical"
"""Relation rows follow the canonical episode (transfer on merge)."""

RELATION_DISPOSITION_KEEP = "keep-attached-to-merged-row"
"""Relation rows stay on the merged row for audit visibility
(``all_objects``); they are never deleted and never repointed."""

ELIGIBLE = "eligible"
REVIEW_REQUIRED = "review_required"

REVIEW_SOURCE_FAILED = "source_failed"
REVIEW_ZERO_EPISODES = "zero_episodes"
REVIEW_MULTIPLE_EPISODES = "multiple_episodes"

# The patient record number (``source_patient_reference``) is deliberately
# absent: identity is never merged, snapshotted or restored — every row
# keeps its own value and the audit payload stays structural-only.
_MERGED_FIELD_NAMES = (
    "admission_date",
    "discharge_date",
    "ward",
    "bed",
)


class AdmissionMergeError(Exception):
    """Base class of the source-confirmed merge domain errors."""


class UnhandledAdmissionRelation(AdmissionMergeError):
    """The runtime Admission inventory contains an unclassified relation."""


class MergeNotEligible(AdmissionMergeError):
    """The injected source confirmation does not authorize a merge."""


class StaleSourceConfirmation(AdmissionMergeError):
    """The fingerprint does not match the confirmation being applied."""


class AdmissionMergeStateError(AdmissionMergeError):
    """The admission pair cannot be merged in its current state."""


class MergeRollbackBlocked(AdmissionMergeError):
    """Post-merge state diverged from the recorded operation boundary."""


# ---------------------------------------------------------------------------
# Source-confirmation value objects (injected; never a production call)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceEpisode:
    """One episode as shown by the fresh admissions snapshot."""

    source_admission_key: str
    admission_start: Optional[datetime]
    admission_end: Optional[datetime]


@dataclass(frozen=True)
class AdmissionSourceConfirmation:
    """Fresh admissions-snapshot view for one patient and one local date.

    ``patient_record`` scopes the confirmation to the patient; it is
    never logged and never written to the audit payload.
    """

    patient_record: str
    local_admission_date: date
    captured_at: Optional[datetime]
    failed: bool
    episodes: tuple[SourceEpisode, ...]


@dataclass(frozen=True)
class MergeEligibility:
    """Pure eligibility decision over the injected confirmation."""

    decision: str
    reason_code: str
    episode_count: int
    fingerprint: str


@dataclass(frozen=True)
class RelationDisposition:
    """Explicit merge disposition of one reverse relation."""

    accessor: str
    disposition: str
    reason: str
    field_name: str
    one_to_one: bool


@dataclass(frozen=True)
class AdmissionMergeResult:
    """Structural outcome of one merge execution."""

    operation_uuid: uuid.UUID
    canonical_admission_id: int
    merged_admission_id: int
    relation_manifest: dict


@dataclass(frozen=True)
class MergeRollbackResult:
    """Structural outcome of one rollback execution."""

    operation_uuid: uuid.UUID
    reverted_relations: dict


# ---------------------------------------------------------------------------
# Transfer registry (checked against the fresh runtime derivation)
# ---------------------------------------------------------------------------

_RELATION_DISPOSITIONS: dict[str, tuple[str, str]] = {
    "events": (
        RELATION_DISPOSITION_REPOINT,
        "Clinical episode content follows the canonical row.",
    ),
    "summary_state": (
        RELATION_DISPOSITION_REPOINT,
        "Summary memory follows the episode; OneToOne conflict-safe: when "
        "the canonical slot is occupied the duplicate's state stays "
        "attached (recorded in the manifest), never deleted.",
    ),
    "summary_versions": (
        RELATION_DISPOSITION_REPOINT,
        "Summary history follows the canonical episode.",
    ),
    "summary_runs": (
        RELATION_DISPOSITION_REPOINT,
        "Summary runs follow the canonical episode.",
    ),
    "pipeline_runs": (
        RELATION_DISPOSITION_REPOINT,
        "Pipeline runs follow the canonical episode.",
    ),
    "movements": (
        RELATION_DISPOSITION_REPOINT,
        "Patient movements follow the canonical episode.",
    ),
    "evolution_extraction_coverage": (
        RELATION_DISPOSITION_REPOINT,
        "Extraction coverage follows the canonical episode.",
    ),
    "source_aliases": (
        RELATION_DISPOSITION_REPOINT,
        "Every observed external key must resolve the canonical row; the "
        "duplicate's own current key becomes an alias (conflict-safe).",
    ),
    "discharge_evidence": (
        RELATION_DISPOSITION_REPOINT,
        "Effective-exit evidence must link the canonical episode.",
    ),
    "death_evidence": (
        RELATION_DISPOSITION_REPOINT,
        "Death evidence must link the canonical episode.",
    ),
    "merged_from": (
        RELATION_DISPOSITION_KEEP,
        "Merge-chain bookkeeping: rows merged into the duplicate keep "
        "pointing at their immediate winner.",
    ),
    "reconciliation_events": (
        RELATION_DISPOSITION_KEEP,
        "Append-only audit stays attached to the row it was written "
        "against; visible via ``all_objects``.",
    ),
}


def _runtime_relations() -> dict:
    return {
        relation.get_accessor_name(): relation
        for relation in Admission._meta.related_objects
    }


def _disposition_for(accessor: str) -> tuple[str, str]:
    try:
        return _RELATION_DISPOSITIONS[accessor]
    except KeyError:
        raise UnhandledAdmissionRelation(
            "Admission has a reverse relation without an explicit merge "
            "disposition; refusing to merge (hard inventory gate)."
        ) from None


def build_relation_registry() -> dict[str, RelationDisposition]:
    """Classify every runtime reverse relation of ``Admission``.

    Derived fresh from ``Admission._meta.related_objects`` on every call;
    any relation without an explicit disposition is a hard error.
    """
    registry: dict[str, RelationDisposition] = {}
    for accessor, relation in _runtime_relations().items():
        disposition, reason = _disposition_for(accessor)
        registry[accessor] = RelationDisposition(
            accessor=accessor,
            disposition=disposition,
            reason=reason,
            field_name=relation.field.name,
            one_to_one=relation.one_to_one,
        )
    return registry


# ---------------------------------------------------------------------------
# Eligibility (pure decision) and fingerprint
# ---------------------------------------------------------------------------


def source_confirmation_fingerprint(
    confirmation: AdmissionSourceConfirmation,
) -> str:
    """SHA-256 digest over the structural content of the confirmation.

    Episode admission keys participate only inside the digest; no raw
    identifier is ever stored or logged.
    """
    episodes = sorted(
        (
            episode.source_admission_key,
            (
                episode.admission_start.isoformat()
                if episode.admission_start is not None
                else ""
            ),
            (
                episode.admission_end.isoformat()
                if episode.admission_end is not None
                else ""
            ),
        )
        for episode in confirmation.episodes
    )
    payload = json.dumps(
        {
            "local_admission_date": confirmation.local_admission_date.isoformat(),
            "failed": confirmation.failed,
            "episodes": episodes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decide_merge_eligibility(
    *, confirmation: AdmissionSourceConfirmation
) -> MergeEligibility:
    """Decide merge eligibility from one fresh source confirmation.

    Exactly one episode authorizes the merge; zero, multiple or failed
    source results require review (fail closed).
    """
    fingerprint = source_confirmation_fingerprint(confirmation)
    episode_count = len(confirmation.episodes)
    if confirmation.failed:
        return MergeEligibility(
            decision=REVIEW_REQUIRED,
            reason_code=REVIEW_SOURCE_FAILED,
            episode_count=episode_count,
            fingerprint=fingerprint,
        )
    if episode_count == 0:
        return MergeEligibility(
            decision=REVIEW_REQUIRED,
            reason_code=REVIEW_ZERO_EPISODES,
            episode_count=episode_count,
            fingerprint=fingerprint,
        )
    if episode_count > 1:
        return MergeEligibility(
            decision=REVIEW_REQUIRED,
            reason_code=REVIEW_MULTIPLE_EPISODES,
            episode_count=episode_count,
            fingerprint=fingerprint,
        )
    return MergeEligibility(
        decision=ELIGIBLE,
        reason_code="",
        episode_count=episode_count,
        fingerprint=fingerprint,
    )


# ---------------------------------------------------------------------------
# Merge execution and rollback
# ---------------------------------------------------------------------------


_NOT_ELIGIBLE_MESSAGE = (
    "Source confirmation is not eligible: exactly one fresh episode is "
    "required; the case requires review."
)
_STALE_CONFIRMATION_MESSAGE = (
    "Source confirmation fingerprint does not match the eligibility "
    "decision; refusing to merge a stale confirmation."
)
_ADMISSION_MISSING_MESSAGE = (
    "One or both admissions no longer exist; refusing to merge."
)
_ALREADY_MERGED_MESSAGE = (
    "One of the admissions is already merged; refusing to merge again."
)
_DIFFERENT_PATIENT_MESSAGE = (
    "Admissions belong to different patients; refusing to merge."
)




# ---------------------------------------------------------------------------
# Internal helpers (structural only; no identity in payloads or logs)
# ---------------------------------------------------------------------------


def _iso(value: Optional[datetime]) -> Optional[str]:
    """UTC-normalized ISO-8601 so before/after snapshots compare stably."""
    if value is None:
        return None
    return value.astimezone(dt_timezone.utc).isoformat()


def _field_snapshot(admission: Admission) -> dict:
    """Structural before/after snapshot of the combinable fields.

    Patient identity (the record number) is never included.
    """
    return {
        "admission_date": _iso(admission.admission_date),
        "discharge_date": _iso(admission.discharge_date),
        "ward": admission.ward,
        "bed": admission.bed,
    }


def _restore_fields(admission: Admission, snapshot: dict) -> None:
    from django.utils.dateparse import parse_datetime

    admission.admission_date = (
        parse_datetime(snapshot["admission_date"])
        if snapshot["admission_date"] is not None
        else None
    )
    admission.discharge_date = (
        parse_datetime(snapshot["discharge_date"])
        if snapshot["discharge_date"] is not None
        else None
    )
    admission.ward = snapshot["ward"]
    admission.bed = snapshot["bed"]


def _lock_pair(pk_a: int, pk_b: int) -> list[Admission]:
    """Lock both rows in deterministic primary-key order (older first)."""
    rows = list(
        Admission.all_objects.select_for_update()
        .filter(pk__in=[pk_a, pk_b])
        .order_by("pk")
    )
    return rows


def _transfer_relation(
    *,
    disposition: RelationDisposition,
    canonical: Admission,
    merged: Admission,
) -> dict:
    """Repoint one relation from the merged row to the canonical row.

    OneToOne relations are conflict-safe: when the canonical slot is
    already occupied, the duplicate's row stays attached (audit
    visibility) and the manifest records it as kept.
    """
    model = _related_model_for(disposition)
    filter_kwarg = {disposition.field_name: merged.pk}
    attached_ids = list(
        _related_rows(disposition, **filter_kwarg).values_list("pk", flat=True)
    )
    moved_ids: list[int] = list(attached_ids)
    kept_ids: list[int] = []
    if (
        disposition.one_to_one
        and _related_rows(
            disposition, **{disposition.field_name: canonical.pk}
        ).exists()
    ):
        kept_ids = moved_ids
        moved_ids = []
    if moved_ids:
        model._base_manager.filter(pk__in=moved_ids).update(
            **{disposition.field_name: canonical.pk}
        )
    return {
        "disposition": RELATION_DISPOSITION_REPOINT,
        "moved": len(moved_ids),
        "kept": len(kept_ids),
        "moved_ids": moved_ids,
        "kept_ids": kept_ids,
    }


def _related_model_for(disposition: RelationDisposition):
    for relation in Admission._meta.related_objects:
        if relation.get_accessor_name() == disposition.accessor:
            return relation.related_model
    raise UnhandledAdmissionRelation(  # pragma: no cover - guarded upstream
        "Relation disappeared from the runtime inventory during merge."
    )


def _related_rows(disposition: RelationDisposition, **filters):
    """Query one related model through its unfiltered base manager.

    Merge/rollback is maintenance access: the self-referential
    ``merged_from`` relation must observe merged (hidden) rows, and the
    other models share their default manager with the base one.
    """
    return _related_model_for(disposition)._base_manager.filter(**filters)


def _record_kept_relation(
    *,
    disposition: RelationDisposition,
    merged: Admission,
) -> dict:
    """Record ownership of a keep-attached relation (no mutation)."""
    attached_ids = list(
        _related_rows(
            disposition, **{disposition.field_name: merged.pk}
        ).values_list("pk", flat=True)
    )
    return {
        "disposition": RELATION_DISPOSITION_KEEP,
        "attached": len(attached_ids),
        "attached_ids": attached_ids,
    }


def _move_aliases(
    *,
    canonical: Admission,
    merged: Admission,
) -> dict:
    """Move all source aliases to the canonical row (merge step 5).

    The duplicate's own current key becomes an alias of the canonical row
    (conflict-safe ``get_or_create``: alias keys are globally unique per
    source system). When the key is already aliased elsewhere the call
    never corrupts that mapping; the manifest records the outcome.
    """
    alias_qs = AdmissionSourceAlias.objects.filter(admission=merged)
    moved_ids = list(alias_qs.values_list("pk", flat=True))
    if moved_ids:
        alias_qs.update(admission=canonical)
    created_alias_id: Optional[int] = None
    if ensure_admission_alias(
        admission=canonical,
        source_system=merged.source_system,
        alias_key=merged.source_admission_key,
    ):
        created_alias_id = (
            AdmissionSourceAlias.objects.filter(
                source_system=merged.source_system,
                alias_key=merged.source_admission_key,
                admission=canonical,
            )
            .latest("pk")
            .pk
        )
    return {
        "disposition": RELATION_DISPOSITION_REPOINT,
        "moved": len(moved_ids),
        "moved_ids": moved_ids,
        "created_alias_id": created_alias_id,
        "kept": 0,
        "kept_ids": [],
    }


def _combine_period_and_metadata(
    *,
    canonical: Admission,
    merged: Admission,
    confirmation: AdmissionSourceConfirmation,
) -> None:
    """Combine the authoritative period and metadata onto the winner.

    The confirmed episode's start/exit values are authoritative; empty
    confirmation values never replace non-empty winner data, and the
    duplicate's non-empty metadata fills gaps on the canonical row.
    """
    episode = confirmation.episodes[0]
    if episode.admission_start is not None:
        canonical.admission_date = episode.admission_start
    elif canonical.admission_date is None:
        canonical.admission_date = merged.admission_date
    if episode.admission_end is not None:
        canonical.discharge_date = episode.admission_end
    elif canonical.discharge_date is None:
        canonical.discharge_date = merged.discharge_date
    canonical.ward = canonical.ward or merged.ward
    canonical.bed = canonical.bed or merged.bed


# ---------------------------------------------------------------------------
# Merge execution (design decision 4, steps 1-7)
# ---------------------------------------------------------------------------


def merge_admissions(
    *,
    first: Admission,
    second: Admission,
    confirmation: AdmissionSourceConfirmation,
    expected_fingerprint: str,
) -> AdmissionMergeResult:
    """Merge two admissions of one episode after source confirmation.

    Steps (design decision 4): re-validate eligibility and the source
    fingerprint; lock both rows in deterministic primary-key order;
    validate the pair; record before-state and relation ownership;
    repoint every inventoried supported relation per its registry
    disposition; combine the authoritative period and metadata without
    replacing non-empty winner data with empty values; move all source
    aliases; mark the newer row ``merged_into`` (never delete); write
    exactly one append-only operation audit. Eligibility and the source
    fingerprint are re-validated under row locks, before any mutation;
    all mutations happen inside a single atomic block and any failure
    leaves both rows untouched.
    """
    with transaction.atomic():
        rows = _lock_pair(first.pk, second.pk)
        if len(rows) != 2:
            raise AdmissionMergeStateError(_ADMISSION_MISSING_MESSAGE)
        # Re-validation of the same source confirmation under row locks
        # (design decision 4, step 1): a stale confirmation can never
        # mutate either row.
        eligibility = decide_merge_eligibility(confirmation=confirmation)
        if eligibility.decision != ELIGIBLE:
            raise MergeNotEligible(_NOT_ELIGIBLE_MESSAGE)
        if eligibility.fingerprint != expected_fingerprint:
            raise StaleSourceConfirmation(_STALE_CONFIRMATION_MESSAGE)
        canonical, merged = rows[0], rows[1]  # ascending pk: oldest wins
        if canonical.patient_id != merged.patient_id:
            raise AdmissionMergeStateError(_DIFFERENT_PATIENT_MESSAGE)
        if (
            canonical.merged_into_id is not None
            or merged.merged_into_id is not None
        ):
            raise AdmissionMergeStateError(_ALREADY_MERGED_MESSAGE)

        registry = build_relation_registry()
        before_state = {
            "canonical": _field_snapshot(canonical),
            "merged": _field_snapshot(merged),
        }

        manifest: dict[str, dict] = {}
        for accessor in sorted(registry):
            disposition = registry[accessor]
            if accessor == "source_aliases":
                manifest[accessor] = _move_aliases(
                    canonical=canonical, merged=merged
                )
            elif disposition.disposition == RELATION_DISPOSITION_REPOINT:
                manifest[accessor] = _transfer_relation(
                    disposition=disposition, canonical=canonical, merged=merged
                )
            else:
                manifest[accessor] = _record_kept_relation(
                    disposition=disposition, merged=merged
                )

        _combine_period_and_metadata(
            canonical=canonical,
            merged=merged,
            confirmation=confirmation,
        )
        before_state["canonical_after"] = _field_snapshot(canonical)
        canonical.save(
            update_fields=[*_MERGED_FIELD_NAMES, "updated_at"],
        )

        merged.merged_into = canonical
        merged.save(update_fields=["merged_into", "updated_at"])

        operation = AdmissionMergeOperation.objects.create(
            canonical_admission_id=canonical.pk,
            merged_admission_id=merged.pk,
            patient_id=canonical.patient_id,
            source_fingerprint=eligibility.fingerprint,
            source_episode_count=eligibility.episode_count,
            confirmed_local_date=confirmation.local_admission_date,
            source_confirmed_at=confirmation.captured_at,
            before_state=before_state,
            relation_manifest=manifest,
        )

    logger.info(
        "admission merge applied: canonical_id=%s merged_id=%s operation=%s "
        "relations=%s",
        canonical.pk,
        merged.pk,
        operation.operation_uuid,
        len(manifest),
    )
    return AdmissionMergeResult(
        operation_uuid=operation.operation_uuid,
        canonical_admission_id=canonical.pk,
        merged_admission_id=merged.pk,
        relation_manifest=manifest,
    )


# ---------------------------------------------------------------------------
# Rollback (all-or-nothing, strict post-state precondition)
# ---------------------------------------------------------------------------


def _validate_rollback_preconditions(
    *,
    operation: AdmissionMergeOperation,
    canonical: Admission,
    merged: Admission,
    registry: dict[str, RelationDisposition],
) -> None:
    """Verify the full post-merge boundary before any mutation.

    Any incompatible later mutation raises :class:`MergeRollbackBlocked`;
    callers run this inside an atomic block so zero partial changes are
    ever written.
    """
    before_state = operation.before_state
    manifest = operation.relation_manifest

    if merged.merged_into_id != canonical.pk:
        raise MergeRollbackBlocked(
            "merged_into no longer points at the canonical admission."
        )
    if _field_snapshot(merged) != before_state["merged"]:
        raise MergeRollbackBlocked(
            "The merged admission's fields changed after the merge."
        )
    if _field_snapshot(canonical) != before_state["canonical_after"]:
        raise MergeRollbackBlocked(
            "The canonical admission's fields changed after the merge."
        )

    for accessor, entry in manifest.items():
        disposition = registry[accessor]
        if disposition.disposition != RELATION_DISPOSITION_REPOINT:
            continue
        if accessor == "source_aliases":
            moved_ids = list(entry["moved_ids"])
            still_canonical = set(
                AdmissionSourceAlias.objects.filter(
                    pk__in=moved_ids, admission=canonical
                ).values_list("pk", flat=True)
            )
            if still_canonical != set(moved_ids):
                raise MergeRollbackBlocked(
                    "A moved alias no longer points at the canonical row."
                )
            created_alias_id = entry["created_alias_id"]
            if created_alias_id is not None and not (
                AdmissionSourceAlias.objects.filter(
                    pk=created_alias_id, admission=canonical
                ).exists()
            ):
                raise MergeRollbackBlocked(
                    "The operation-created alias is no longer intact."
                )
            if AdmissionSourceAlias.objects.filter(admission=merged).exists():
                raise MergeRollbackBlocked(
                    "A new alias was attached to the merged row after the merge."
                )
            continue
        moved_ids = list(entry["moved_ids"])
        field_name = disposition.field_name
        still_canonical = set(
            _related_rows(
                disposition, pk__in=moved_ids, **{field_name: canonical}
            ).values_list("pk", flat=True)
        )
        if still_canonical != set(moved_ids):
            raise MergeRollbackBlocked(
                "A transferred relation no longer points at the canonical row."
            )
        kept_ids = set(entry["kept_ids"])
        attached_now = set(
            _related_rows(
                disposition, **{field_name: merged}
            ).values_list("pk", flat=True)
        )
        if attached_now != kept_ids:
            raise MergeRollbackBlocked(
                "The merged row gained or lost relations after the merge."
            )


def rollback_admission_merge(
    *, operation: AdmissionMergeOperation
) -> MergeRollbackResult:
    """Reverse one merge by operation, atomically or not at all.

    Every item post-state is validated first (transferred relations still
    point at the canonical row, ``merged_into`` unchanged, aliases
    present, fields unchanged); any incompatible later mutation blocks
    the whole rollback with zero partial changes. Items are reversed in
    reverse order: ``merged_into``, aliases, relations, fields.
    """
    from django.utils import timezone

    if operation.rolled_back_at is not None:
        raise MergeRollbackBlocked(
            "This merge operation has already been rolled back."
        )

    with transaction.atomic():
        rows = _lock_pair(
            operation.canonical_admission_id, operation.merged_admission_id
        )
        if len(rows) != 2 or rows[0].pk != operation.canonical_admission_id:
            raise MergeRollbackBlocked(
                "The merged or canonical admission no longer matches the "
                "recorded operation."
            )
        canonical, merged = rows[0], rows[1]
        registry = build_relation_registry()
        _validate_rollback_preconditions(
            operation=operation,
            canonical=canonical,
            merged=merged,
            registry=registry,
        )

        manifest = operation.relation_manifest

        # 1. Un-mark the merged row (reverse of the last write).
        merged.merged_into = None
        merged.save(update_fields=["merged_into", "updated_at"])

        # 2. Aliases back to the merged row. A fallback alias created by
        #    the operation (duplicate's own key) is never deleted: the
        #    module writes no deletes at all, and resolution remains
        #    correct because the current-key layer shadows it.
        reverted: dict[str, int] = {}
        alias_entry = manifest["source_aliases"]
        moved_alias_ids = list(alias_entry["moved_ids"])
        if moved_alias_ids:
            AdmissionSourceAlias.objects.filter(pk__in=moved_alias_ids).update(
                admission=merged
            )
        reverted["source_aliases"] = len(moved_alias_ids)

        # 3. Relations back, in reverse registry order.
        for accessor in sorted(manifest, reverse=True):
            disposition = registry[accessor]
            if disposition.disposition != RELATION_DISPOSITION_REPOINT:
                continue
            if accessor == "source_aliases":
                continue
            model = _related_model_for(disposition)
            moved_ids = list(manifest[accessor]["moved_ids"])
            if moved_ids:
                model._base_manager.filter(pk__in=moved_ids).update(
                    **{disposition.field_name: merged}
                )
            reverted[accessor] = len(moved_ids)

        # 4. Restore the canonical row's pre-merge fields.
        _restore_fields(canonical, operation.before_state["canonical"])
        canonical.save(update_fields=[*_MERGED_FIELD_NAMES, "updated_at"])

        # 5. Single sanctioned audit state transition: the rollback mark.
        operation.rolled_back_at = timezone.now()
        operation.save(update_fields=["rolled_back_at"])

    logger.info(
        "admission merge rolled back: canonical_id=%s merged_id=%s "
        "operation=%s reverted_relations=%s",
        canonical.pk,
        merged.pk,
        operation.operation_uuid,
        len(reverted),
    )
    return MergeRollbackResult(
        operation_uuid=operation.operation_uuid,
        reverted_relations=reverted,
    )
