# Slice RPSA-S1 — Layered admission identity and relation inventory

## Mission

Implement only layered Admission identity: inventory relations/query paths, add
source aliases plus nullable merge marker, and make canonical admission upsert
reuse a uniquely matched episode when the external key changes. Do not implement
merge, exit reconciliation, census cases, UI, runtime or backfill.

## Mandatory context-zero reading order

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/reconcile-patient-exits-and-stale-admissions/proposal.md`
4. `openspec/changes/reconcile-patient-exits-and-stale-admissions/design.md`
5. `openspec/changes/reconcile-patient-exits-and-stale-admissions/specs/patient-admission-mirror/spec.md`
6. `openspec/changes/reconcile-patient-exits-and-stale-admissions/specs/admission-duplicate-resolution/spec.md`
7. `openspec/changes/reconcile-patient-exits-and-stale-admissions/tasks.md`
8. `apps/patients/models.py`, `apps/patients/services.py`,
   `apps/ingestion/services.py`, `apps/census/admissions_recovery.py`
9. All files returned by `rg -l 'Admission\.objects|admissions__|admission=' apps tests -g '*.py'`

## Scope and file limit

Maximum **8 repository files changed**, including the task checkbox. Allowed:

- `apps/patients/models.py`
- `apps/patients/migrations/0002_*.py`
- `apps/ingestion/services.py`
- `apps/patients/services.py`
- `tests/unit/test_admission_identity.py`
- `tests/integration/test_admission_identity_schema.py`
- `openspec/changes/reconcile-patient-exits-and-stale-admissions/evidence/admission-relation-inventory.md`
- `openspec/changes/reconcile-patient-exits-and-stale-admissions/tasks.md`

If the migration number differs, use the next actual number. If any other file
is required, stop as `INCOMPLETO`; do not widen scope.

## Bootstrap and baseline

```bash
git status --short
git rev-parse HEAD
BASE_REF="$(git rev-parse HEAD)"
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
```

Require a clean tree before editing. Record `BASE_REF` and exact baseline output.
If dirty or baseline fails, stop `INCOMPLETO` without edits.

## Contract matrix

| Contract | Implementation target | Required test |
| --- | --- | --- |
| Current key then alias then exact start then unique Bahia local date | identity resolver in `apps/ingestion/services.py` or a small patient service | precedence and each unique match |
| Two same-day candidates fail closed | same resolver | no row changed/created; ambiguity result |
| Changed key closes one compatible open episode | canonical upsert | existing PK reused and alias persisted |
| Alias uniqueness and no self-merge | model constraint | migration/model constraint tests |
| Merged rows have explicit canonical and unfiltered access | model managers/query helpers | default versus maintenance query test |
| Every Admission relation/query path is known before merge | evidence inventory | integration assertion compares Django reverse relations with inventory |

Use `America/Bahia` explicitly for local-date matching. Preserve non-empty
ward/bed when source values are empty. No automatic merge occurs in this slice.

## TDD protocol

### RED

1. Create synthetic tests for all matrix rows before production code.
2. Run:

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
```

1. Capture failing test names and assertion excerpts in the report. A collection,
import or syntax failure is not accepted RED.

### GREEN

Implement the minimum additive schema and resolver/upsert needed to pass. Keep
matching pure where practical and transactionally enforce alias uniqueness.
Do not delete existing admissions or guess among candidates.

### REFACTOR

Remove duplicated matching branches, use named value objects/reason codes and
keep orchestration thin. Apply clean code, DRY and YAGNI; add no generalized
identity framework.

## Mandatory inspections

```bash
rg -n "merged_into|AdmissionSourceAlias|America/Bahia" apps/patients apps/ingestion tests
rg -n "\.first\(\)" apps/ingestion/services.py
rg -n "\.delete\(\)" apps/ingestion/services.py
python - <<'PY'
from pathlib import Path
p = Path('openspec/changes/reconcile-patient-exits-and-stale-admissions/evidence/admission-relation-inventory.md')
assert p.exists() and 'Admission' in p.read_text()
PY
```

Explain every `.first()` in candidate selection; none may choose an ambiguous
episode. Existing unrelated deletes are not failures, but new Admission delete
logic is forbidden.

## Gates, completion and commit

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate reconcile-patient-exits-and-stale-admissions --strict
./scripts/markdown-lint.sh
```

Then inspect `git diff --check`, `git diff --stat "$BASE_REF"` and
`git diff "$BASE_REF" -- <each changed file>`. Only after every gate passes,
mark only `RPSA-S1` complete and create one commit. Do not amend another commit.
Stop after this slice.

## Automatic `INCOMPLETO` conditions

Declare `INCOMPLETO`, leave the task unchecked and make no commit if the tree or
baseline is dirty, RED is not assertion-level, a relation cannot be safely
inventoried, migration is destructive, ambiguity mutates data, a gate fails,
the file limit is exceeded, real patient data appears, or production access is
needed.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S1-report.md` even when incomplete. Include:
summary/status; `BASE_REF` and final commit; acceptance checklist; requirement →
file → test matrix; changed-file list; before/after snippets for every changed
file; RED and GREEN evidence; full commands and exit results; inspection output;
gate output; `git diff --check`; risks, residuals and next step. Use only
synthetic values and valid Markdown. A third LLM must be able to verify every
claim from this report and the diff.
