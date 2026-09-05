# Slice RPSA-FINAL — Independent release-readiness verification

## Mission

Verify the completed change independently. Do not repair implementation in this
slice. If any contract, artifact, inspection or gate fails, report `INCOMPLETO`
and leave the final task unchecked. Production access, timer activation and
backfill apply remain forbidden.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. ADR-0009
3. This change's proposal, complete design, every delta spec and tasks
4. Every `SLICE-RPSA-*.md` prompt and `/tmp/sirhosp-slice-RPSA-*-report.md`
5. Commit diff for every completed implementation slice
6. All implementation and tests named in traceability matrices
7. Entire production runbook and versioned systemd files

## Scope and file limit

Maximum **1 repository file changed**:

- `openspec/changes/reconcile-patient-exits-and-stale-admissions/tasks.md`

Only the `RPSA-FINAL` checkbox may change, and only after complete success. Any
implementation or documentation correction requirement means `INCOMPLETO` and a
new corrective slice proposal, not an edit here.

## Bootstrap and baseline

```bash
git status --short
git rev-parse HEAD
BASE_REF="$(git rev-parse HEAD)"   # expected 63b3323; reference baseline 3538 unit / 656 integration
openspec status --change reconcile-patient-exits-and-stale-admissions --json
```

Require a clean tree and all RPSA-S1 through RPSA-S12 tasks, including
RPSA-S7A, checked (13 of 14 boxes). Record the exact commit range and
reports available.

## Independent verification matrix

Build a report table for every normative `#### Scenario` containing capability,
requirement, scenario, implementing file, automated test or deployment
inspection, result and evidence command. A scenario with no direct evidence is
a failure. Map each proof to its owning suite instead of rediscovering it:

| Proof | Owning evidence (verify, quote, and run the focused command) |
| --- | --- |
| zero-residual saida_em → open admission | S2/S4 reconciliation suites (discharges/deaths services tests) |
| zero unresolved source-confirmed pair | S9 backfill suites (merge cohort apply) |
| never-close set (ambiguous/census-absence/alta_em-only/date-only death) | S2/S3/S5 negative tests |
| merged persist + atomic rollback | S4 merge rollback + S9 batch rollback suites |
| unconfirmed zero stays failed | S7 zero-confirmation suite |
| review/CSV permissions + log safety | S6 portal suites + output-safety tests across slices |
| credentials out of argv/output | S7A transport suite (all four extractors) |
| health durable/read-only/violations | S10 suites + daily command tests |
| PDF command fails pre-side-effect, no caller | S3 orphan-command guard + FINAL inspection nº4 |
| 05:00 Bahia D-1 four extractors | S12 deploy-contract tests + unit files |
| runner never under normal `up` | S11 deploy-contract YAML tests |
| assets same-tag, disabled, no production apply | S12 workflow/asset tests + repo history (no enable/backfill commands) |

Explicitly prove with synthetic isolated-test data:

- zero uniquely matched valid `saida_em` evidence remains linked to an open
  canonical admission after reconciliation;
- zero source-confirmed one-episode duplicate pair remains unresolved after a
  bounded apply in the test database;
- ambiguous same-day episodes, census absence, `alta_em` alone and date-only
  deaths never close an admission;
- merged rows persist and rollback is atomic;
- unconfirmed zero remains failed;
- review/CSV permissions and log identity safety hold;
- all four historical extractors keep credential values out of argv and output;
- health reads durable confirmed-zero metadata, is read-only and catches
  configured violations;
- `process_discharge_pdf` fails before file access or any side effect and has no
  executable runtime caller;
- the `05:00:00 America/Bahia` systemd recovery selects D-1 and explicitly runs
  `discharges`, `admissions`, `deaths` and `official_census`;
- the profile-gated hospital runner cannot start under normal Compose `up`;
- units resolve the hospital Compose runtime, retry only code 75 within bounds,
  ship as same-tag release assets, remain disabled and production apply was not
  run.

## Verification form of RED → GREEN → REFACTOR

- **RED:** any failing scenario, inspection or gate proves the change is not
  releasable and requires `INCOMPLETO`; capture the assertion-level evidence.
- **GREEN:** all scenarios, invariants and gates pass independently on the
  committed implementation.
- **REFACTOR:** prohibited in this verification-only slice. If refactoring or
  correction is needed, propose a bounded corrective slice and stop.

## Mandatory inspections

```bash
rg -n "alta_em.*discharge_date|discharge_date.*alta_em" apps tests
rg -n "discharge_date\s*=|update\(.*discharge_date" apps/census apps/discharges/management/commands/process_discharge_pdf.py
rg -n "open\(|read_|extract_patients|process_discharges|\.create\(|\.update\(" apps/discharges/management/commands/process_discharge_pdf.py
rg -n "process_discharge_pdf" deploy compose*.yml apps -g '!apps/discharges/management/commands/process_discharge_pdf.py'
rg -n "time\.min|time\.max|midnight|noon|23:59" apps/deaths
rg -n "Admission.*delete\(|\.delete\(\)" apps/patients/admission_merge.py
rg -n "Celery|Redis|celery|redis" apps deploy compose*.yml pyproject.toml
rg -n "prontuario|patient_source_key|nome|name" apps/ingestion/pipeline_health.py apps/*/management/commands deploy
rg -n "05:00:00|America/Bahia|discharges|admissions|deaths|official_census" deploy/systemd/sirhosp-historical-recovery.* apps/ingestion/management/commands/run_exit_reconciliation_runtime.py
rg -n -U '"--(username|password)"[[:space:]]*,[[:space:]]*(creds\.|username|password)' apps
rg -n "historical_recovery|profiles|EX_TEMPFAIL|75|release.*asset" compose.hospital.yml deploy .github/workflows tests
rg -n "/opt/sirhosp|/srv/apps/prisma|compose\.hospital\.yml" deploy
rg -n "backfill.*--apply|enable --now" deploy docs openspec/changes/reconcile-patient-exits-and-stale-admissions
```

Classify each hit; any unsafe executable path is failure. Documentation may show
approved commands only when surrounded by explicit authorization safeguards.

## Full gates

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
SIRHOSP_VERSION=verify-tag DJANGO_SECRET_KEY=verify DJANGO_ALLOWED_HOSTS=localhost \
POSTGRES_PASSWORD=verify SOURCE_SYSTEM_URL=https://verify.invalid \
SOURCE_SYSTEM_USERNAME=verify SOURCE_SYSTEM_PASSWORD=verify \
docker compose -f compose.hospital.yml --profile recovery config --quiet
openspec validate reconcile-patient-exits-and-stale-admissions --strict
./scripts/markdown-lint.sh
git diff --check
```

Shell variables take precedence over `--env-file`, so the synthetic
prefix is deterministic regardless of local `.env`; never print the
rendered configuration. If Docker is genuinely unavailable in the
environment, document it and fall back to the S11/S12 YAML contract
tests as the authoritative proof — an environmental limitation is not
a contract failure, but it must be explicit in the report.

Re-run systemd syntax and production Compose `config --quiet` checks from
RPSA-S11. Do not print rendered environment or credentials.

## Completion

Only when every scenario maps to passing evidence, all explicit proofs and gates
pass, and no unresolved risk violates acceptance, mark RPSA-FINAL and create one
verification commit. Stop; do not archive the change automatically.

## Automatic `INCOMPLETO`

Leave task unchecked and make no commit if the tree is dirty, any earlier task or
report is absent, any scenario lacks evidence, either zero-residual invariant
fails, inspection finds unsafe behavior, a gate or hospital Compose resolution
fails, credentials remain in extractor argv, real patient data or credentials
appear, production was accessed, a timer/backfill was activated, or
any file besides the task checkbox needs change.

## Required report

Write `/tmp/sirhosp-slice-RPSA-FINAL-report.md` in valid Markdown with final
status, `BASE_REF`/commit, complete scenario traceability table, slice report and
commit inventory, a CONSOLIDATED DEFERRED-P2 APPENDIX (per-slice record-only
notes with their routing, informing the archive decision), synthetic invariant
queries/results, classified inspection hits, all command/gate outputs, proof of
no production/timer/backfill action, risks and archive recommendation. A third
LLM must be able to reject or accept the change using only this report,
referenced reports and repository diff.
