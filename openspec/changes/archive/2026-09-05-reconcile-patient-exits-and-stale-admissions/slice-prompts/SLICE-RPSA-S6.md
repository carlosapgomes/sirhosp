# Slice RPSA-S6 — Permission-protected review and ephemeral CSV

## Mission

Implement only authorized reconciliation review (queue + detail), streamed
CSV export and the remaining safe-admin registrations. Patient name and
record number may appear in the protected UI and streamed CSV, never in
logs or persisted export files. This slice also lands the two RPSA-S5
deferred display-semantics fixes so the queue shows truthful case state.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. `specs/stale-admission-detection/spec.md` (review-permission and CSV
   scenarios) and `specs/admission-duplicate-resolution/spec.md`
   (merged-record admin visibility scenario)
4. RPSA-S2/S4/S5 reports (commits up to `4a04c57`); the S5 acceptance
   notes in `/tmp/sirhosp-slice-RPSA-S5-report.md` (deferred P2 items
   this slice lands)
5. `apps/services_portal/urls.py`, `views.py` (auth conventions:
   `@login_required`, manual-auth portal entry), existing list templates
   and pagination/filter patterns
6. `apps/patients/models.py` (`StaleAdmissionCase`, `ReconciliationEvent`,
   `Admission` managers), `apps/census/stale_admissions.py` (case
   lifecycle, resolution reasons), `apps/discharges/models.py`,
   `apps/deaths/models.py` (evidence linkage fields)
7. `apps/patients/admin.py` (post-RPSA-S4: `AdmissionAdmin` unfiltered and
   read-only `AdmissionMergeOperationAdmin` already exist — do not redo
   them)
8. Existing HTTP auth/permission tests (`tests/integration/`
   `test_portal_entry_auth.py`, `test_search_http_auth.py`) for client,
   login and assertion conventions

## Ground truth (established; do not reinvent)

- The dedicated permission exists: codename `review_reconciliation_cases`
  ("Can review reconciliation cases"), content type `StaleAdmissionCase`,
  created by RPSA-S5 migration `0005_staleadmissioncase`. Reference it as
  `"patients.review_reconciliation_cases"`. Protect the new routes with
  the portal's existing convention (`@login_required` plus a permission
  check raising `PermissionDenied` → 403). Anonymous requests keep the
  existing login-redirect behavior; authenticated users without the
  permission get 403 with no disclosure of case existence or identity.
- Queue contents (one coherent review surface): open
  `StaleAdmissionCase` rows (plus recently resolved ones when the status
  filter asks for them) UNION `DischargeRecord`/`DeathRecord` evidence
  rows whose `reconciliation_status` is one of `pending`, `ambiguous` or
  `conflict` (the spec's review set). `patient_not_found` and
  `admission_not_found` rows are NOT queue items — extraction already
  enqueues bounded sync for them. Filters: status, source type and age;
  pagination follows the portal's existing pattern.
- Detail view: one case or one evidence row, its structural audit trail
  (`ReconciliationEvent` rows: statuses, exit types, reason codes,
  before/after datetimes — never clinical text), the patient name and
  record number (authorized here), and merged/canonical state when the
  linked admission is involved (via `merged_into`/`merged_from`,
  `all_objects` for maintenance display).
- CSV export: same permission, same filtered queryset, streamed through a
  generator with `csv.writer`, `Content-Disposition: attachment` and
  no-cache headers; no temp file, storage backend or cached body. Export
  logging records actor-independent aggregate outcome metadata only
  (row count, filter summary, success/failure) — never name, record
  number or CSV body. View code itself must not log identity.
- Admin scope for this slice: register `ReconciliationEvent` and
  `StaleAdmissionCase` as read-only (no add/change/delete) in
  `apps/patients/admin.py`; create `apps/discharges/admin.py` with a
  `DischargeRecord` admin and `apps/deaths/admin.py` with a `DeathRecord`
  admin showing linkage/status read-only (admin is staff-only; identity
  columns are authorized there). Do not modify the existing
  `AdmissionAdmin`/`AdmissionMergeOperationAdmin`/`PatientAdmin` beyond
  what these registrations require.
- RPSA-S5 deferred display fixes (land here, with tests first):
  1. In `apps/census/stale_admissions.py`, the reappearance resolution
     must not relabel evidence-resolved cases: skip the reappearance
     branch when `case.admission.discharge_date` is set (or order the
     exit-confirmed resolution before it), so a case closed by canonical
     exit evidence reads `exit_confirmed`, not `reappeared`.
  2. The settled/exit-confirmed evaluation must filter
     `admission__merged_into__isnull=True` (mirroring the open-case
     query), freezing merged+closed cases per the merge KEEP rationale.
- No model/schema change and no migration belong to this slice; admin and
  view code only (`makemigrations --check` must stay clean).
- Synthetic identities in tests only; never real patient data.

## Scope and file limit

Maximum **11 repository files changed** — 9 core, 2 authorized exceptions:

Core:

- `apps/services_portal/urls.py`
- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/reconciliation_queue.html`
  (new)
- `apps/services_portal/templates/services_portal/reconciliation_detail.html`
  (new)
- `apps/patients/admin.py`
- `apps/discharges/admin.py` (new)
- `apps/deaths/admin.py` (new)
- `tests/integration/test_reconciliation_review_http.py` (new)
- this change's `tasks.md`

Authorized exceptions (RPSA-S5 deferred display fixes, landed with tests
first; minimal edits preserving unrelated assertions):

- `apps/census/stale_admissions.py` (the two fixes above)
- `tests/unit/test_stale_admission_detection.py` (regression tests for
  both fixes)

No frontend framework, no persisted files, no new service module; views
compose existing model querysets directly. Any other file means
`INCOMPLETO`.

## Contract matrix

| Contract | Required HTTP/admin assertion |
| --- | --- |
| anonymous request | existing login behavior; no identity in body |
| authenticated without permission | 403; no case disclosure |
| dedicated permission holder | queue/detail include synthetic name and record number |
| queue covers cases + pending/ambiguous/conflict evidence | union correctness; not-found rows excluded |
| filters/pagination | only requested status/type/age subset displayed |
| CSV permission | same authorization as queue |
| CSV response | streamed content, correct escaping, no server-side file |
| export logging | aggregate outcome only; no body/name/record number |
| view logging | no identity in any logger call |
| evidence admins | new registrations show linkage/status read-only |
| audit/case admin | read-only; no add/change/delete actions |
| merged/canonical detail state | correct labels via `merged_into`/`merged_from` |
| reappearance no longer mislabels | evidence-resolved case reads `exit_confirmed` |
| merged+closed case frozen by settled step | stays unresolved-by-this-path |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| rotas protegidas | `urls.py`, `views.py` | integration: anônimo → login; sem permissão → 403; com permissão → 200 |
| fila (união + filtros + paginação) | `views.py`, template | integration: composição, filtros, subset paginado |
| detalhe (audit + identidade + merged) | `views.py`, template | integration: eventos estruturais, nome/prontuário, rótulos merged |
| CSV efêmero | `views.py` | integration: streaming/escaping/headers; zero arquivo em disco |
| logs seguros | `views.py` | integration: captura de logs sem identidade/corpo |
| admins de evidência/auditoria | `patients/discharges/deaths admin` | integration: registro read-only, linkage visível |
| fix reappearance-mislabel | `apps/census/stale_admissions.py` | unit: caso exit-resolvido + reaparição → `exit_confirmed` |
| fix freeze merged+closed | `apps/census/stale_admissions.py` | unit: caso em linha merged+fechada permanece |

## RED

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_reconciliation_review_http.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_stale_admission_detection.py -k 'exit_confirmed or \
  merged'"
```

- Falha esperada (integração): rotas inexistentes (404/NoReverseMatch),
  CSV ausente, admins não registrados — falhas de asserção sobre
  comportamento esperado.
- Falha esperada (unit): os dois fixes S5 — caso exit-resolvido rotulado
  `reappeared`; caso merged+fechado resolvido pelo passo `settled`.
- Baseline de referência no HEAD (`4a04c57`): 3346 unit / 565
  integration. Qualquer falha não relacionada deve ser escalada via
  `contact_supervisor`.

## GREEN / verificação local

- Os mesmos comandos focados do RED passam (exit 0).
- `./scripts/test-in-container.sh unit` e `integration` verdes; desvios de
  contagem além dos novos testes devem ser explicados no relatório.
- `./scripts/test-in-container.sh lint` e `typecheck` sem erro.
- No container: `uv run --no-sync python manage.py makemigrations --check`
  (nenhuma migração esperada) e `check --deploy` não é exigido.

## Mandatory inspections

```bash
rg -n "review_reconciliation_cases|PermissionDenied" \
  apps/services_portal tests/integration/test_reconciliation_review_http.py
rg -n "NamedTemporaryFile|TemporaryDirectory|open\(|FileResponse|\.write\(" \
  apps/services_portal/views.py
rg -n "logger\.|print\(" apps/services_portal/views.py \
  apps/patients/admin.py apps/discharges/admin.py apps/deaths/admin.py
rg -n "has_add_permission|has_change_permission|has_delete_permission" \
  apps/patients/admin.py apps/discharges/admin.py apps/deaths/admin.py
rg -n "nome|prontuario|patient_source_key" apps/services_portal/views.py
rg -n "exit_confirmed|merged_into__isnull" apps/census/stale_admissions.py
```

Interpretation: identity references are allowed only for protected
rendering/CSV lookup (never in logger/print arguments or persisted
files); the two S5 fixes are present and tested; evidence/audit admins
are read-only. Any unauthorized file creation, identity-bearing log,
editable audit admin or missing fix fails the slice.

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

Review complete diff against `BASE_REF`. Mark only RPSA-S6 and create one
commit after all gates pass, then stop. Never use real patient fixtures
or production.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S6-report.md` with status, base/commit,
acceptance and requirement→file→test matrices, changed files and
before/after snippets, RED/GREEN, anonymous/unauthorized/authorized
response evidence, proof no export file remains (temp-dir inspection),
log-capture proof, both S5-fix regression evidence, inspections, all
gates, diff check, risks and next step. Valid Markdown and synthetic
identities only.

## Automatic `INCOMPLETO`

No checkbox/commit if dependencies/tree/baseline fail, RED is not
assertion-level, the permission does not exist at HEAD, an unauthorized
response leaks case existence or identity, CSV is written/cached on disk,
the audit/case admin is editable, logs expose identity/body, either S5
display fix is missing or untested, a migration appears, a file outside
the 11-file list is touched, a gate fails or scope exceeds the list.
