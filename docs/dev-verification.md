# Dev verification sessions

## Purpose

Use this runbook to open and close ephemeral portal accounts on dev.
The controller owns one session per target and revokes both accounts on close.
Do not use this flow on production. R8 operational proof stays BLOCKED until the operator authorizes a dev window and confirms a fictitious dataset.

## Accounts and ownership

The flow touches only `verify_user` and `verify_admin`.
Both use fixed reserved emails under `verification.invalid`.
A reserved name without the owned email blocks the run atomically.
Human accounts stay untouched.
Only these two owned rows carry a visible non-secret stamp in `first_name`.
An active run shows `vfyA` plus the run id. A revoked run shows `vfyR` plus the run id.
Usernames and emails stay fixed. Do not assert a human readable name for these rows.

## Prerequisites

Complete these checks before open.

- Target is dev and the checkout is the dev checkout.
- The operator confirms the dataset is fictitious.
- DEBUG is false for open. Close works with DEBUG true.
- No pending migrations for open. Close works with drift in unrelated apps.
- Workers are stopped for open. Close works with workers active.
- The database fingerprint matches the live dev cluster.

Close and recovery need only target identity, ownership, an execution path, and a reachable auth database.

## Commands

Run every command from the repo root.

Check the target without writes.

```bash
uv run python scripts/verify_portal.py doctor --target dev --confirm-fictitious
```

Open one session. The assisted CLI prints one JSON object on stdout with the run id, target, and each password exactly once, after every guard, activation, durable checkpoint, and the final timer recheck have succeeded. No other command or failure path prints credentials. Keep passwords in memory. Never store passwords in state, reports, argv, or logs. Programmatic callers receive the credentials in memory without printing.

```bash
uv run python scripts/verify_portal.py open --target dev --confirm-fictitious
```

Show the non-secret record.

```bash
uv run python scripts/verify_portal.py status --target dev
```

Close the current session. Repeat close is safe.

```bash
uv run python scripts/verify_portal.py close --target dev
```

Close a named run. A stale run id returns SKIPPED and changes nothing.

```bash
uv run python scripts/verify_portal.py close --target dev --run-id <run-id>
```

Recover owned rows after an orphan or an interrupted prepare. Recovery never reactivates accounts.

```bash
uv run python scripts/verify_portal.py close --target dev --recover
```

Revoke first and then stop only dev web and db. Volumes, workers, and edge stay preserved.
The explicit stop is honored whenever the target identity and the owned-pair revocation are confirmed, including when the record is already CLOSED or absent and during recovery.
A failed stop returns FAIL with the truthful state preserved (CLOSED stays CLOSED; a recovery stop failure keeps a recoverable CLOSING record).
No stop happens before verified revocation, for a foreign pair, or on a denied close.

```bash
uv run python scripts/verify_portal.py close --target dev --stop
```

Start only dev db and web when the operator asks for it.

```bash
uv run python scripts/verify_portal.py open --target dev --confirm-fictitious --start
```

## Exit codes

- PASS returns 0.
- FAIL returns 1.
- BLOCKED returns 2.
- SKIPPED returns 3 for a stale run id only.

Do not report CLOSED unless revocation is verified and the record is durable.
Timer cancel failure stays visible as incomplete cleanup. It never reports PASS.

## State, lock, and timer

The controller stores a non-secret record under `~/.local/state/sirhosp-verification`.
The record holds state, target, run id, deadline, timer unit, and pair ids or the expected snapshot.
It never holds a password, cookie, session token, or password hash.
Writes use atomic replace.
Every persisted record is validated on load for exact shape, field types, target match, run-id and snapshot format, an aware deadline, a timer unit paired with its own run id, and two distinct positive integer pair ids for ACTIVE.
A malformed or coerced record is never presented as a valid state or treated as a stale run.
Ordinary status, open, and close fail closed as BLOCKED with a recovery demand.
The deadline callback instead returns FAIL with exit code 1 and the same recovery demand, never a quiet skip.

Explicit recovery over an unreadable record does not trust the file.
The cleanup identity comes from the non-secret stamps of the verified owned pair in the database, which must show one coherent generation.
Recovery revokes that stamped generation first, writes the durable CLOSING checkpoint, cancels exactly that run's owned timer and service units, and only then records CLOSED and reports PASS.
When the stamps are absent, malformed, mixed, or disagree with a supplied run id, recovery returns FAIL without revoking, without stopping any timer, and without overwriting the record; the pending cleanup stays unknown and requires manual recovery.
A syntactically valid run id alone is never accepted as the cleanup identity.

One stable lock file guards each target. The lock is never stolen or unlinked.
Process death releases the lock through the kernel. There is no PID file and no heartbeat.

Open persists OPENING, arms and confirms a transient user systemd timer, prepares inactive rows, activates the exact prepared pair, persists ACTIVE, rechecks timer and deadline, and then emits credentials once.
Timer arming uses a unit name with the run id and a default 60 minute deadline.
If arming fails, open writes nothing to accounts and returns BLOCKED.
After interruption, credentials are lost. Close the run and open a new one. Never retransmit.

Close and recovery order is fixed: verified revocation first, then a durable CLOSING checkpoint, then timer cancellation, then the optional stop of web followed by db, and only then the durable CLOSED record.
A failure at any point keeps the truthful intermediate state visible (CLOSING or the previous CLOSED) and never reports PASS.
An inconclusive timer cancellation is reported as an unknown cleanup outcome, not as retention or completion.

The deadline callback waits for the lock, reloads state, checks the run id, and revokes only its own generation.
It never stops its own timer unit before verified revocation and durable closure, and it never stops web or db.
The timer is a transient user unit: a reboot or a stopped user manager removes it, so the durable record can survive as OPENING, ACTIVE, or CLOSING with no live timer.
After a reboot, run status and then close or recovery before a new open; the controller cannot prove the timer state across a reboot.
Do not claim the portal was inaccessible during a Docker restart.

## Recovery and containment

An orphaned active pair blocks open. Run close with recover, confirm revocation, and then open again.
Recovery uses a compare and swap on the observed snapshot. A late old prepare cannot activate after recovery.
Close never creates rows. It revokes present owned rows for its own generation and counts absent rows as already revoked.
A mixed generation blocks the whole close with zero writes.

If revocation fails, the controller keeps CLOSING, returns FAIL, and tells you to contain web before stopping db.
Do not stop db before verified revocation.
If the auth database is unreachable, keep web contained and retry close. Never report PASS.

## Stopped web path

Use the normal web exec path while web runs.
When web is stopped, the controller has no implemented way to prove the dev identity safely, so the one-shot probe path is deliberately BLOCKED with `aliases or database route unproved`.
This probe is not implemented in S1: no fixed container name, alias, route, or fingerprint proof is performed, and none of those properties should be assumed.
Open refuses to start web by itself when identity is unproved, and close or recovery that needs the database identity fails without mutation while web is stopped, because the identity collection cannot run.
Recovery that needs the auth database therefore requires web running again (started by the operator through the normal dev Compose), after which the usual close and recovery fences apply.
It never reports CLOSED on this path.

## Direct Django command

The Django command uses the same fence. It needs explicit dev context and the live fingerprint on every call.
There are no username, password, or reset arguments.

```bash
python manage.py verification_session preflight --dev-context-confirm --target dev --expect-db-fingerprint <fp>
python manage.py verification_session owned-status --dev-context-confirm --target dev --expect-db-fingerprint <fp>
python manage.py verification_session close --dev-context-confirm --target dev --expect-db-fingerprint <fp> --run-id <run-id>
python manage.py verification_session recover --dev-context-confirm --target dev --expect-db-fingerprint <fp> --run-id <run-id> --expect-state <snapshot>
```

## Limits

- One active session per target.
- No human account changes.
- No production target.
- No model, migration, auth backend, settings, template, Compose, or dependency changes in this slice.
- No browser driver in S1. S1 proves auth with the Django test client and reserves the repeatable Playwright driver for S2.
- The automated integration tests run the Django test client against real PostgreSQL in the isolated `sirhosp-test` project with synthetic data. They are tests, not the R8 operational proof: R8 requires the authorized runbook demonstration (doctor, open, real form login, close, and the revoked-session request) on the confirmed dev target, which stays BLOCKED until the operator authorizes a dev window and confirms a fictitious dataset.
- The fingerprint check stops accidents. It is not an authorization boundary against an operator with direct database access.
