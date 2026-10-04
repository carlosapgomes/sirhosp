"""Guarded JSON adapter for the fixed verification-account pair."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.verification import (
    GenerationMismatch,
    OwnershipCollision,
    close_owned_pair,
    open_owned_pair,
    prepare_owned_pair,
    read_owned_pair_state,
    recover_owned_pair,
)

IDENTITY_SQL = """
SELECT CASE WHEN has_function_privilege(current_user, 'pg_control_system()', 'EXECUTE')
            THEN (SELECT system_identifier::text FROM pg_control_system()) ELSE NULL END,
       oid::text, datdba::text, encoding::text, datcollate,
       current_setting('server_version_num'), host(inet_server_addr()), inet_server_port()
FROM pg_database WHERE datname = current_database()
"""


def database_identity() -> tuple[str, str | None, int | None]:
    if connection.vendor != "postgresql":
        raise CommandError("BLOCKED: PostgreSQL is required")
    with connection.cursor() as cursor:
        cursor.execute(IDENTITY_SQL)
        row = cursor.fetchone()
    if row is None:
        raise CommandError("BLOCKED: Database identity unavailable")
    parts = list(row[:2]) if row[0] else list(row)
    fingerprint = hashlib.sha256(
        b"vfy-db-v1\n" + json.dumps(parts, separators=(",", ":")).encode()
    ).hexdigest()
    return fingerprint, row[6], row[7]


def database_fingerprint() -> str:
    return database_identity()[0]


def migrations_clean() -> bool:
    executor = MigrationExecutor(connection)
    return not executor.migration_plan(executor.loader.graph.leaf_nodes())


class Command(BaseCommand):
    help = (
        "Fixed owned verification accounts. Explicit dev context and live DB fingerprint required."
    )
    requires_system_checks: list[str] = []

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "action",
            nargs="?",
            choices=["preflight", "owned-status", "prepare", "open", "close", "recover"],
        )
        parser.add_argument("--dev-context-confirm", action="store_true")
        parser.add_argument("--target")
        parser.add_argument("--expect-db-fingerprint")
        parser.add_argument("--run-id")
        parser.add_argument("--expect-state")

    def handle(self, *args: Any, **options: Any) -> None:
        action = options["action"]
        if not action or not options["dev_context_confirm"] or options["target"] != "dev":
            raise CommandError("BLOCKED: Explicit confirmed dev context is required")
        expected = options["expect_db_fingerprint"]
        if not expected:
            raise CommandError("BLOCKED: Expected database fingerprint is required")
        try:
            fingerprint, address, port = database_identity()
            if expected != fingerprint:
                raise CommandError("BLOCKED: Database fingerprint mismatch")
            if action in {"preflight", "owned-status"}:
                result = {
                    "fingerprint": fingerprint,
                    "server_address": address,
                    "server_port": port,
                    "pair": asdict(read_owned_pair_state()),
                    "debug": settings.DEBUG,
                }
                if action == "preflight":
                    result["migrations_clean"] = migrations_clean()
            else:
                run_id = options["run_id"] or ""
                snapshot = options["expect_state"] or ""
                if action in {"prepare", "open"}:
                    if settings.DEBUG is not False:
                        raise CommandError("BLOCKED: Opening requires DEBUG false")
                    if not migrations_clean():
                        raise CommandError("BLOCKED: Pending migrations; no automatic repair")
                    operation = prepare_owned_pair if action == "prepare" else open_owned_pair
                    result = asdict(operation(run_id=run_id, expect_state=snapshot))
                elif action == "recover":
                    result = asdict(recover_owned_pair(run_id=run_id, expect_state=snapshot))
                else:
                    result = asdict(close_owned_pair(run_id=run_id))
        except (OwnershipCollision, GenerationMismatch) as exc:
            raise CommandError(f"BLOCKED: {exc}") from None
        except DatabaseError:
            raise CommandError("FAIL: Authentication database operation failed") from None
        self.stdout.write(json.dumps(result, separators=(",", ":")))
