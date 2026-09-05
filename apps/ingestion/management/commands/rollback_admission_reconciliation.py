"""Operation-level and batch rollback for reconciliation backfills (RPSA-S9).

Accepts exactly one of ``--batch <uuid>`` or ``--operation <uuid>`` (the
two selectors are mutually exclusive and any ambiguous or empty
resolution is rejected). Batch rollback is two-phase: every grouped
item's recorded post-state is validated read-only first, then all items
are reversed in reverse ``item_order`` inside ONE transaction — any
conflict aborts with zero writes and an identity-free error. Batch UUIDs
live only in the backfill payload linkage, so a batch selector never
resolves an operation UUID and vice versa. Output carries counts and
UUIDs only, never patient identity.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.patients.admission_merge import MergeRollbackBlocked
from apps.patients.backfill import (
    BackfillRollbackAmbiguous,
    BackfillRollbackConflict,
    BackfillRollbackNotFound,
    rollback_backfill_batch,
    rollback_single_operation,
)
from apps.patients.reconciliation import ReconciliationRollbackBlocked


class Command(BaseCommand):
    help = (
        "Reverse one backfill batch (atomic, reverse order, after full "
        "post-state validation) or exactly one online operation by UUID."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--batch",
            type=str,
            default=None,
            help="Backfill batch UUID recorded in the audit payload linkage.",
        )
        parser.add_argument(
            "--operation",
            type=str,
            default=None,
            help="Single operation UUID (reconciliation event or merge operation).",
        )

    def handle(self, *args, **options) -> None:
        batch_raw = (options["batch"] or "").strip()
        operation_raw = (options["operation"] or "").strip()
        if batch_raw and operation_raw:
            raise CommandError(
                "Use either --batch or --operation, never both selectors."
            )
        if not batch_raw and not operation_raw:
            raise CommandError(
                "Specify exactly one of --batch or --operation."
            )
        try:
            if batch_raw:
                self._rollback_batch(batch_raw)
            else:
                self._rollback_operation(operation_raw)
        except (
            BackfillRollbackAmbiguous,
            BackfillRollbackConflict,
            BackfillRollbackNotFound,
            ReconciliationRollbackBlocked,
            MergeRollbackBlocked,
        ) as exc:
            raise CommandError(str(exc)) from exc

    def _rollback_batch(self, raw: str) -> None:
        try:
            batch_uuid = uuid.UUID(raw)
        except ValueError:
            raise CommandError("--batch must be a valid UUID.") from None
        result = rollback_backfill_batch(batch_uuid=batch_uuid)
        self.stdout.write(
            f"rolled back batch_uuid={result.batch_uuid} "
            f"items={result.reversed_items} "
            f"reconciliation_events={result.reversed['reconciliation_event']} "
            f"merge_operations={result.reversed['merge_operation']}"
        )

    def _rollback_operation(self, raw: str) -> None:
        try:
            operation_uuid = uuid.UUID(raw)
        except ValueError:
            raise CommandError("--operation must be a valid UUID.") from None
        result = rollback_single_operation(operation_uuid=operation_uuid)
        self.stdout.write(
            f"rolled back operation_uuid={operation_uuid} kind={result.kind}"
        )
