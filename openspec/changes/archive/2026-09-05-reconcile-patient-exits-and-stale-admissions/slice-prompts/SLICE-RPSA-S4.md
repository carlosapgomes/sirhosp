# Slice RPSA-S4 — Source-confirmed merge and rollback

## Mission

Implement only deterministic Admission merge/rollback after source
confirmation. Keep the oldest row, transfer every inventoried supported
relation, preserve aliases, mark the newer row merged and retain immutable
operation audit. Do not merge from local similarity alone and do not execute
historical backfill. This slice also closes the manager-policy gate: the
call-site classification must be recorded before any `merged_into` writer
ships.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design (decisions 3-5), tasks, ADR-0009
3. `specs/admission-duplicate-resolution/spec.md` and the modified
   `specs/patient-admission-mirror/spec.md`
4. RPSA-S1 report/diff (relation inventory, managers, alias constraints),
   RPSA-S2 and RPSA-S3 reports (commits `c47fb03`..`ce5ce03`)
5. `apps/patients/models.py` (managers, `merged_into`, alias model,
   `EXIT_*`/status constants), `apps/patients/services.py`
   (`resolve_admission_identity`, `ensure_admission_alias`, `merge_patients`)
   and `apps/patients/reconciliation.py`
6. `apps/admissions/models.py` and the admissions snapshot upsert path
   (`apps/ingestion/services.py`, resolver usage around line 946)
7. Every model reported by Django as a reverse Admission relation (the
   runtime inventory test below pins the current set)
8. `apps/patients/admin.py` (current `PatientAdmin` pattern)
9. `tests/integration/test_admission_identity_schema.py` (pinned runtime
   inventory)

## Ground truth (established; do not reinvent)

- Runtime reverse-accessor inventory at HEAD (pinned by
  `test_admission_identity_schema.py`): `events`, `summary_state`,
  `summary_versions`, `summary_runs`, `pipeline_runs`, `movements`,
  `evolution_extraction_coverage`, `merged_from`, `source_aliases`,
  `discharge_evidence`, `death_evidence`, `reconciliation_events`. The
  transfer registry in the new merge module must be checked against a fresh
  runtime derivation of `Admission._meta.related_objects` and must be a
  superset-compatible classification: every relation gets an explicit
  disposition — repoint-to-canonical, keep-attached-to-merged-row (audit
  visibility), or excluded-with-reason. Unknown relations are a hard error.
- Manager policy (design decision 3): default `Admission.objects` filters
  `merged_into IS NULL`; `all_objects` is unfiltered. Clinical hiding is
  intentional and correct for census, portal, summaries, health, stale
  commands and the reconciliation matcher.
- Division of duplicate handling: the pre-existing period-collapse
  consolidator in `apps/ingestion/services.py` (deletes exact-same-period
  snapshot duplicates; S1-hardened alias transfer) stays untouched — merged
  rows are invisible to it (default manager), so it can never delete or
  re-collapse them. The S4 merge handles source-confirmed duplicates that the
  consolidator does not collapse. Do not unify the two mechanisms in this
  slice.
- Eligibility (design decision 4): a fresh admissions snapshot shows exactly
  one episode for the patient and local admission date; multiple, zero or
  failed source results require review. Implement it as a pure decision over
  an injected/episodes view (synthetic in tests); the merge re-validates the
  same source fingerprint under row locks before mutating. No Playwright or
  production source call in this slice — runtime wiring arrives in RPSA-S6
  (review UI) and RPSA-S9 (backfill cohorts).
- Merge execution (design decision 4, steps 1-7): lock both rows in
  deterministic PK order; record before-state and relation ownership; repoint
  supported FKs; combine period/metadata without replacing non-empty winner
  data with empty values; move all source aliases (conflict-safe: alias keys
  are globally unique per source system, and a duplicate's own current key
  becomes an alias of the canonical row); mark the newer row
  `merged_into=canonical` — never delete; write one operation-level
  append-only audit with structural content only (relation names, counts,
  PKs; no name/prontuário).
- Operation-audit model options (both acceptable): either store admission
  PKs as plain fields/JSON (no new reverse accessors), or use FKs and add
  the new accessor(s) to the pinned inventory test (authorized exception
  below, same conscious-update pattern as RPSA-S2/S3).
- Rollback: by operation, only after validating every item post-state
  (relations still point at canonical, `merged_into` unchanged, aliases
  present); any incompatible later mutation blocks the whole rollback with
  zero partial changes; reverse items atomically in reverse order.
- Pre-classified call-site verdicts (record the full table with evidence in
  the classification artifact; escalate any disagreement):
  - clinical, keep default manager: `apps/census/services.py` (295, 780),
    `apps/census/management/commands/*` stale/sync commands,
    `apps/services_portal/views.py:893`,
    `apps/discharges/management/commands/refresh_daily_discharge_counts.py`,
    `apps/summaries/services.py`, `apps/ingestion/patient_flow_findings.py`,
    `apps/ingestion/pipeline_health.py:371`, `apps/ingestion/views.py`
    (display-only), `apps/patients/services.py` (73, 257, 265),
    `apps/patients/reconciliation.py` matcher layers (296, 338) and the
    apply lock (388 — a target merged between decide and apply raises
    `DoesNotExist` loudly, the stage fails and the next cycle re-resolves
    via alias; pin this as expected behavior, never "fix" it silently);
  - maintenance, use `all_objects`: the new merge/rollback module, Django
    admin (both canonical and merged rows), rollback lookups;
  - verify-with-test (no edit unless the test fails):
    `apps/ingestion/services.py` admissions upsert paths must resolve a
    merged row's key to the canonical winner through
    `resolve_admission_identity` and never create a second row; the
    persistent-session `.first()` lookup (line ~2039) must be None-guarded.
- The legacy discharge `process_discharges` path and the consolidator are
  out of scope beyond the verification test above.

## Scope and file limit

Maximum **11 repository files changed** — 8 core, 1 authorized exception,
2 conditional exceptions:

Core:

- `apps/patients/models.py`
- next `apps/patients/migrations/0004_*.py`
- `apps/patients/admission_merge.py` (new)
- `apps/patients/services.py` (only if a patients-local flip/helper is
  genuinely needed; may end untouched)
- `apps/patients/admin.py`
- `tests/unit/test_admission_merge.py` (new)
- `tests/integration/test_admission_merge.py` (new)
- this change's `tasks.md`

Authorized exception:

- `tests/integration/test_admission_identity_schema.py` — add the new
  accessor(s) of the operation model to the pinned inventory (one line each,
  plus its comment), preserving every unrelated assertion.

Conditional exceptions (edit only after the mandated verification test
fails there, with evidence, and after escalating via `contact_supervisor`):

- `apps/ingestion/services.py` (minimal resolver/no-recreation fix on the
  admissions upsert path)
- `tests/unit/test_ingestion_service.py` (corresponding minimal test edits)

The classification artifact lives at
`evidence/admission-manager-call-site-classification.md` inside this
change's directory (untracked) and is a required deliverable. Any other
file means `INCOMPLETO`.

## Contract matrix

| Contract | Required test |
| --- | --- |
| fresh source snapshot shows exactly one episode | eligible decision |
| multiple/zero/failed source result | no merge and review reason |
| oldest PK is canonical | reversed input order still keeps oldest |
| fingerprint re-validated under lock | stale confirmation blocks mutation |
| current inventory classification | registry equals fresh runtime derivation; superset of S1 incl. discharge/death evidence FKs |
| every default-manager/reverse call site classified | evidence file with verdict + rationale for each |
| all supported relations transfer per disposition | parameterized assertion per relation |
| one-to-one/kept-attached relations stay on merged row | visible via `all_objects`, never deleted |
| aliases move without loss/conflict | old and new keys resolve canonical row |
| snapshot upsert with a merged row's key | resolves to the winner; never creates a second row |
| apply lock on a row merged mid-flight | loud `DoesNotExist`; no mutation; pinned as expected |
| merged row persists with `merged_into` | no Admission delete; maintenance lookup succeeds |
| normal clinical query hides merged row | patient listing/count shows canonical once |
| admin exposes both rows and operation | admin queryset uses unfiltered access |
| one operation stores before/after plus relation manifest | immutable audit assertion |
| rollback restores atomically | fields/relations/aliases restored |
| incompatible later mutation blocks rollback | zero partial changes |
| audit/logs carry no identity | structural payload assertions |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| eligibilidade pura + fingerprint | `apps/patients/admission_merge.py` | unit: episódio único/múltiplo/zero; stale fingerprint |
| execução do merge (passos 1-7) | `admission_merge.py`, migration `0004_*` | unit/integration: transferências por relação, aliases, `merged_into` |
| inventário × registro | `admission_merge.py` + teste de schema | integration: registro == derivacao runtime |
| classificação de call sites | `evidence/admission-manager-call-site-classification.md` | check: tabela cobre todos os sites do `rg` |
| upsert não recria duplicata merged | — (teste pode viver em `test_admission_merge.py`) | integration: chave merged → vencedor |
| apply-lock fail-loud | `admission_merge.py` (teste) | unit: `DoesNotExist`, nenhuma mutação |
| admin sem filtro + operação read-only | `apps/patients/admin.py` | integration: linhas canonical+merged visíveis |
| rollback atômico e bloqueado | `admission_merge.py` | unit/integration: restauração; pós-estado incompatível → zero writes |
| imutabilidade da auditoria | `admission_merge.py`/models | unit: sem update/delete de operação |

## RED

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_admission_merge.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_admission_merge.py"
```

- Falha esperada (unit): `ModuleNotFoundError`/`AttributeError` em
  `apps.patients.admission_merge` demonstra o serviço ausente; depois de
  criar o módulo vazio, as falhas devem ser de asserção (eligibilidade,
  oldest-PK, transferências, rollback).
- Falha esperada (integração): admin não expõe linhas merged; upsert com
  chave merged ainda cria segunda linha; registro ≠ inventário runtime.
- Falhas devem demonstrar comportamento ausente (asserção ou atributo),
  nunca erro de sintaxe/import nos arquivos de teste.
- Baseline de referência no HEAD (`ce5ce03`): 3278 unit / 542 integration.
  Qualquer falha não relacionada aos novos testes deve ser escalada via
  `contact_supervisor`.

## GREEN / verificação local

- Os mesmos comandos focados do RED passam (exit 0).
- `./scripts/test-in-container.sh unit` e `integration` verdes; desvios de
  contagem além dos novos testes e das exceções autorizadas devem ser
  explicados no relatório.
- `./scripts/test-in-container.sh lint` e `typecheck` sem erro.
- No container: `uv run --no-sync python manage.py makemigrations --check`.

## Mandatory inspections

```bash
rg -n "merged_into\s*=" apps --glob '!**/migrations/**'
rg -n "all_objects" apps --glob '!**/migrations/**'
rg -n "Admission.*delete\(|\.delete\(\)" apps/patients/admission_merge.py
rg -n "select_for_update|transaction\.atomic" apps/patients/admission_merge.py
rg -n "name|nome|prontuario" apps/patients/admission_merge.py \
  apps/patients/models.py
rg -ln "Admission\.objects|admission_set|\.admissions\b" apps \
  --glob '*.py' --glob '!**/migrations/**'
test -f openspec/changes/reconcile-patient-exits-and-stale-admissions/\
evidence/admission-manager-call-site-classification.md
```

Interpretation: `merged_into` writers may exist only in the merge module
(and the migration); every `all_objects` use maps to a maintenance verdict
in the classification artifact; the final `rg -ln` list must be a subset of
the classified sites. Field names may appear in queries, but no log/audit
value may carry identity. Any delete in the merge module, missing
classification artifact, or unclassified site fails the slice.

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
```

Review all diffs against `BASE_REF`. Mark only RPSA-S4, create one commit
and stop. Never call production source or run merge/backfill against
production.

## Required report

Create `/tmp/sirhosp-slice-RPSA-S4-report.md` with status, base/commit,
relation registry comparison (runtime derivation vs S1 inventory),
classification table summary (verdict + rationale per site), acceptance and
requirement→file→test matrices, every changed file with before/after
snippets, RED/GREEN with quoted assertions, transaction/rollback evidence,
commands, inspections, all gates, diff check, risks and next step. Valid
Markdown and synthetic data only; make it independently verifiable.

## Automatic `INCOMPLETO`

Leave the task unchecked and commit nothing if baseline/tree is invalid,
RPSA-S3 is incomplete, RED is not assertion-level (after module creation),
source confirmation is not proven fresh/unique or the fingerprint is not
revalidated under lock, the classification artifact is missing or does not
cover every `rg`-listed site, the current registry omits an S1 relation or
either evidence FK, any relation lacks a disposition, the newest row is
chosen as canonical, a row is deleted, rollback can partially mutate,
identity enters logs/audit payloads, a conditional exception is edited
without a failing verification test and escalation, a gate fails or more
than 11 files are needed.
