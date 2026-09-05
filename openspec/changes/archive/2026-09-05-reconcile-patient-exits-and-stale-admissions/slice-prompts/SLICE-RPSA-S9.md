# Slice RPSA-S9 — Bounded dry-run backfill and operation rollback

## Mission

Implement only deterministic historical planning/apply/rollback commands
that reuse online reconciliation and merge services. Dry-run is default.
Production apply is forbidden during this slice and remains separately
authorized. This slice also lands the RPSA-S8 deferred P2 (episode-level
counting fixture).

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. Delta spec `specs/admission-reconciliation-backfill/spec.md` (all six
   ADDED requirements — default non-mutation, approved cohorts only,
   deterministic order, reversibility with operation/batch UUIDs,
   separately authorized production execution, summary refresh later)
4. RPSA-S2, S3 and S4 reports; RPSA-S8 report (P2 routing note)
5. `apps/patients/models.py` — `ReconciliationEvent` (append-only,
   `operation_uuid` unique, `status` in the 8 DB-constrained
   `RECONCILIATION_STATUSES`, `prior/new_discharge_date`,
   `details_json`) and `AdmissionMergeOperation` (append-only,
   `before_state`, `relation_manifest`, sanctioned `rolled_back_at`
   transition)
6. `apps/patients/reconciliation.py` (`decide_discharge_match`,
   `apply_discharge_exit`), `apps/patients/admission_merge.py`
   (`decide_merge_eligibility`, `merge_admissions`,
   `rollback_admission_merge`, `MergeRollbackBlocked`),
   `apps/discharges/services.py:reconcile_discharge_record`,
   `apps/deaths/services.py:reconcile_death_record`
7. Evidence models (`DischargeRecord.saida_em`, `DeathRecord` datetime)
   and management-command conventions (option validation before
   mutation; see `sync_missing_discharges` for style)
8. Existing safe-output/transaction test patterns in
   `tests/unit/test_admission_merge_service.py` (if present) and the
   S8 aggregate tests

## Ground truth (established; do not reinvent)

- **No migration, no new column, no new status value** (the 8
  reconciliation statuses are DB-constrained; adding one needs a
  migration that this slice forbids). Batch linkage and rollback
  provenance live in existing JSON payloads, append-only:
  - each backfill item records
    `ReconciliationEvent.details_json["backfill"] = {"batch_uuid": ...,
    "item_order": N}` or, for merges,
    `AdmissionMergeOperation.relation_manifest["backfill"]` with the
    same shape;
  - never update an existing payload row.
- **Reconciliation item rollback is an inverse append-only operation**:
  a new `ReconciliationEvent` with status `reconciled` (its documented
  meaning — "closed **or corrected** — one uniquely matched admission"),
  `prior_discharge_date`/`new_discharge_date` swapped relative to the
  original, and `details_json` carrying `rollback_of: <operation_uuid>`
  plus the batch linkage. Add a `reverse_reconciliation(event)` helper
  in `apps/patients/reconciliation.py` that validates the post-state
  (`admission.discharge_date == event.new_discharge_date`) before
  applying, mirroring the merge-rollback discipline.
- **Merge item rollback** reuses `rollback_admission_merge` as-is
  (it already validates state and sets the sanctioned `rolled_back_at`).
- **Rollback command** accepts `--batch <uuid>` or `--operation <uuid>`
  (mutually exclusive; reject any UUID that resolves ambiguously or to
  nothing). Batch rollback is two-phase: validate every grouped item's
  post-state (read-only), then reverse all items in reverse
  `item_order` inside ONE transaction; any conflict means zero writes
  and an aggregate error message without patient identity. Single
  operation rollback reverses exactly one item and is never confused
  with a batch (distinct namespaces: batch UUIDs live only in
  `backfill` payloads).
- **Canary without new persistence**: count prior backfill batches by
  distinct `batch_uuid` across the two payload locations; with zero
  prior batches the apply cap is 50, otherwise 100. Apply always
  requires `--apply`, a positive `--limit` within the cap, a non-empty
  `--label` and a non-empty `--backup-ref`; anything else fails before
  mutation.
- **Cohorts, in the mandated deterministic order** (stable ordering by
  admission/evidence PK before limiting; limit applies to the merged
  plan before any write):
  1. source-confirmed duplicate pairs — `decide_merge_eligibility` +
     `merge_admissions` (reuse the online path including source
     confirmation freshness);
  2. exact hospital discharges — `DischargeRecord` with valid
     `saida_em` and exactly one canonical admission of the same patient
     with the same local admission date, replayed via
     `reconcile_discharge_record`;
  3. complete deaths — death evidence with a complete datetime and
     exactly one compatible admission, replayed via
     `reconcile_death_record`;
  4. everything else (temporal-only matches, missing/absent evidence,
     ambiguity) is NEVER auto-applied: dry-run reports aggregate counts
     by reason only.
- **Dry-run is the default**: a pure plan object (dataclass, no ORM
  writes) with per-cohort counts and operation bounds. Output contains
  cohort counts, limits, batch UUID (apply only) and item counts —
  never patient name, prontuário, source identifiers or clinical text.
- **Apply** runs one bounded transaction per batch: plan first, then
  mutate only via the online services above; on item failure the whole
  batch rolls back (DB transaction) and the error is reported without
  identity.
- **Summary/refresh pipelines are never started inside the command or
  its transaction**; affected admissions remain identifiable through
  the audit payloads for the separate bounded refresh.
- **RPSA-S8 deferred P2 lands here** (authorized exception below): one
  episode-level counting test — same patient, two canonical admissions
  exiting the same local date must count 2 in
  `refresh_daily_discharge_counts` output (a regression back to
  distinct-patient semantics yields 1 and fails).
- Synthetic fixtures only; never run either command against production;
  tests use the isolated test database.

## Scope and file limit

Maximum **9 repository files changed** — 8 core plus 1 authorized
exception:

- `apps/patients/backfill.py` (new — plan/cohort selection, pure)
- `apps/ingestion/management/commands/reconcile_admission_history.py`
  (new — dry-run/apply)
- `apps/ingestion/management/commands/rollback_admission_reconciliation.py`
  (new — batch/operation rollback)
- `apps/patients/reconciliation.py` (only `reverse_reconciliation` and
  the batch-payload recording hook; existing behavior untouched)
- `apps/patients/admission_merge.py` (only the batch-payload recording
  hook on the online merge path; rollback logic untouched)
- `tests/unit/test_admission_reconciliation_backfill.py` (new)
- `tests/integration/test_admission_reconciliation_backfill_commands.py`
  (new)
- this change's `tasks.md`

Authorized exception (controller, lands the RPSA-S8 P2):

- `tests/unit/test_daily_discharge_count.py` — exactly one new
  episode-level counting test; no other change to the file.

No migration, deploy file, production fixture, new model or new status
value is allowed. If the online audit genuinely lacks state required
for reversibility beyond what the payloads can carry, stop `INCOMPLETO`
rather than adding command-local audit tables.

## Contract matrix

| Contract | Required test |
| --- | --- |
| no flags | aggregate dry-run, zero writes (row counts identical) |
| `--apply` without limit/label/backup-ref | fails before any mutation |
| first apply limit > 50 | rejected (zero prior batches) |
| later apply limit > 100 | rejected after ≥1 recorded batch |
| deterministic cohort order | duplicates complete before discharges; deaths after; stable PK order |
| exact discharge cohort | same patient + same local admission date + valid `saida_em` only |
| complete death cohort | complete datetime + exactly one admission |
| temporal-only / absent evidence | counted for manual review only, never applied |
| apply | one operation UUID per item + one batch UUID grouping the ordered items |
| batch rollback | validates all post-states, reverses in reverse order atomically, appends rollback events |
| operation rollback | single item only; never accepted as/combined with a batch |
| rollback conflict | zero writes across the whole batch, identity-free error |
| summary processing | not invoked inside command or transaction |
| episode-level counting (S8 P2) | same patient, two canonical same-day exits → count 2 |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| dry-run default sem mutação | comando + backfill.py | unit + integration (row counts) |
| apply exige limit/label/backup | comando | unit (CommandError pré-mutação) |
| canário 50/100 por batches prévios | comando | unit (0 batches→cap 50; ≥1→cap 100) |
| ordem determinística de cohorts | backfill.py | unit (plano com múltiplas cohorts) |
| cohort exata de altas | backfill.py | unit (mesmo paciente/data local; temporal-only excluído) |
| cohort de óbitos completa | backfill.py | unit (datetime completo; >1 admission excluída) |
| ambiguities só reportadas | backfill.py + comando | unit (counts por motivo, sem apply) |
| item/batch UUID + ordem | serviços online hooks | unit + integration (payloads append-only) |
| rollback de batch atômico | comando rollback | integration (2 fases, ordem reversa, eventos inversos) |
| rollback individual distinto | comando rollback | unit ( namespaces disjuntos, erro ambiguidade) |
| conflito = zero writes | comando rollback | integration (mutação posterior bloqueia tudo) |
| sem summary no comando | comandos | inspeção rg nº3 |
| output sem identidade | ambos comandos | unit (assert stdout) |
| S8 P2 episode-level | teste diário (exceção) | unit (2 episódios → count 2) |

## Bootstrap and baseline

```bash
git status --short          # must be clean
git rev-parse HEAD          # record BASE_REF (expected fbf59bf)
./scripts/test-in-container.sh check
```

Reference baseline at `fbf59bf`: 3419 unit / 604 integration (post-S8).
Do not re-run full suites as a pre-baseline; report deltas against these
numbers. Escalate via contact_supervisor on any baseline mismatch.

## TDD RED → GREEN → REFACTOR

RED first, focused (synthetic fixtures; cohorts built with S2/S4-style
factories):

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_admission_reconciliation_backfill.py \
  tests/unit/test_daily_discharge_count.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_admission_reconciliation_backfill_commands.py"
```

Expected assertion-level failures: `call_command` with unknown command
names (both commands do not exist yet) raising `CommandError`;
`--apply` without `--limit` failing to raise; a 51-item apply against a
zero-batch database not raising; the dry-run call mutating rows
(`assert Admission.objects.count()` unchanged fails); the plan API not
importable; rollback-by-batch unknown; episode-level test counting 1
under current helpers only if written against the S8 command — RED must
quote each failing assertion.

GREEN: implement the pure plan, the two-phase bounded apply
transaction, payload-recording hooks, `reverse_reconciliation`, the
rollback command, and the one daily-count test addition with the
smallest change. Refactor only shared option validation and result
aggregation; do not build a workflow engine. Clean code, DRY, YAGNI.

## Mandatory inspections

```bash
rg -n -- "--apply|--limit|--label|--backup-ref|--batch|--operation" apps/ingestion/management/commands/reconcile_admission_history.py apps/ingestion/management/commands/rollback_admission_reconciliation.py
rg -n "\.update\(|\.save\(|\.delete\(" apps/patients/backfill.py
rg -n "process_summary|summary_run|refresh_admission|call_command" apps/ingestion/management/commands/reconcile_admission_history.py apps/ingestion/management/commands/rollback_admission_reconciliation.py apps/patients/backfill.py
rg -n "batch_uuid|rollback_of|item_order" apps/patients/reconciliation.py apps/patients/admission_merge.py apps/ingestion/management/commands
rg -n "name|nome|prontuario|patient_source_key|raw_" apps/patients/backfill.py apps/ingestion/management/commands/reconcile_admission_history.py apps/ingestion/management/commands/rollback_admission_reconciliation.py
rg -n "RECONCILIATION_STATUS|status=" apps/patients/reconciliation.py | head -20
```

Interpretation: flags exist only in the two commands; `backfill.py`
itself performs no ORM writes (mutations happen only through the online
  services); no summary/pipeline/call_command invocation in the new
code; batch/rollback provenance present exactly in the payload hooks;
no identity fields read into command output; no new reconciliation
status value is introduced anywhere.

## Gates and completion

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate reconcile-patient-exits-and-stale-admissions --strict
./scripts/markdown-lint.sh
git diff --check
uv run --no-sync python manage.py makemigrations --check
```

Inspect every diff against `BASE_REF`. Mark only RPSA-S9, create one
commit and stop. Never run either command against production; tests use
the isolated test database only.

## Automatic `INCOMPLETO`

Leave the task unchecked and make no commit if tree/baseline/dependency
fails, RED is not assertion-level, dry-run writes anything, apply lacks
any precondition, the canary caps can be bypassed, selection uses fuzzy
temporal fallback or absent evidence, any mutation bypasses the online
services, a new model/column/status/migration appears, batch and item
identifiers are conflated, rollback can partially apply or writes
before validating all post-states, identity leaks into output, summary
processing starts inside the command, production is touched, a gate
fails or more than 9 files are needed.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S9-report.md` with status, base/commit,
acceptance and requirement→file→test matrices, every changed file with
before/after snippets, RED/GREEN (quoted assertions), cohort ordering
and command matrix, before/after row counts for dry-run/apply/rollback
in the test DB, batch/operation UUID evidence from payloads, identity
safety inspections, the episode-level test proof, all commands/gates,
diff check, risks and next step. Valid Markdown and synthetic data
only.
