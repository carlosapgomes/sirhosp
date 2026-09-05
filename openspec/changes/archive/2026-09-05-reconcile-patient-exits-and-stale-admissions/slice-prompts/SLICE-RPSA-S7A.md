# Slice RPSA-S7A — Credential-safe historical subprocess transport

## Mission

Remove source username and password from process argv for the four historical
extractors used by scheduled recovery. Pass them only through a scoped child
environment, preserve extraction behavior and never echo credentials. This
slice also lands the three RPSA-S7 deferred P2s (failure-stage metadata,
confirmation-timeout observability, recovery mock shape). Do not change
scheduling, reconciliation, source navigation or production.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. `specs/historical-extraction-services/spec.md` (requirement "Historical
   extractor subprocess credentials are not argv values": three scenarios —
   starts automation, credential is missing, process inspection occurs)
4. RPSA-S7 report/diff and its acceptance notes in
   `/tmp/sirhosp-slice-RPSA-S7-report.md` (deferred P2s landing here)
5. `apps/ingestion/extractors/subprocess_utils.py` (`run_subprocess`
   forwards `**kwargs` to `Popen`, so `env=` works unchanged)
6. The four service subprocess builders:
   `apps/admissions/services.py` (~line 143), `apps/discharges/
   extraction_service.py` (~line 313, `run_discharge_extraction`),
   `apps/deaths/services.py` (~line 163), `apps/census/services.py`
   (~line 1011, official census)
7. `apps/ingestion/historical_extraction.py` (`resolve_source_credentials`:
   settings `SOURCE_SYSTEM_URL/USERNAME/PASSWORD` first, same-named env
   fallback)
8. The four `automation/source_system/{admissions,discharges,deaths,
   official_census}/extract_*.py` argument parsers
9. Existing credential-argv tests that will be updated (authorized
   exceptions below): `tests/unit/test_historical_extraction_helpers.py`,
   `tests/unit/test_legacy_session_bootstrap.py`,
   `tests/unit/test_persistent_worker_command.py`

## Ground truth (established; do not reinvent)

- Scoped child environment keys are exactly `SOURCE_SYSTEM_USERNAME` and
  `SOURCE_SYSTEM_PASSWORD` (the same names `resolve_source_credentials`
  already uses for settings/env). Build the child env from
  `os.environ.copy()` overriding only those two keys; never mutate the
  parent environment; pass it as `env=` to `run_subprocess` (its
  `**kwargs` already reach `Popen` — `subprocess_utils.py` MUST NOT
  change; if it seems to need a change, stop `INCOMPLETO`).
- Service wrappers MUST NOT place credential values in argv: remove
  `--username <value>` / `--password <value>` from all four builders;
  `--source-url`, date, headless, output-dir and reference-date
  arguments remain unchanged in argv.
- Automation entry points: resolve credentials from the scoped
  environment first (`SOURCE_SYSTEM_USERNAME`/`SOURCE_SYSTEM_PASSWORD`).
  The existing `--username`/`--password` CLI flags MAY remain as an
  optional manual fallback ONLY when the environment values are absent
  (document this precedence in each entry point's help text); when both
  are absent, exit non-zero with a FIXED message that names neither the
  missing field nor any credential value (spec scenario "Credential is
  missing").
- Never echo credentials: no credential value in any exception message,
  stdout, stderr, log line or `details_json`/`error_message` produced by
  the services or entry points (spec scenario "Process inspection
  occurs" — argv must stay clean for `ps` inspection).
- RPSA-S7 deferred P2s landing here (tests first, minimal edits):
  1. In `apps/discharges/extraction_service.py`, the
     `discharge_persistence` FAILURE stage metric must include
     `attempt_count` and `zero_confirmed` in `details_json` alongside
     the error (metadata already durable elsewhere; this closes the
     literal gap).
  2. In the same file, a confirmation attempt that times out must mark
     the run failed with `timed_out=True` (propagate
     `failure["timed_out"]` exactly like the first-attempt timeout path),
     keeping `confirmation_failure_reason="timeout"` structured and
     credential-safe.
  3. In `tests/unit/test_historical_recovery.py`, align
     `_unconfirmed_zero_result()` with the real unconfirmed-zero shape
     (`metrics={}`), keeping the passthrough assertions meaningful.
- No secrets manager, no new dependency, no settings rename. Reuse
  `resolve_source_credentials` as-is; the scoped env is constructed at
  the subprocess call site from its returned values.
- Synthetic sentinel credentials in tests only (e.g.
  `user-sentinel`/`pass-sentinel`); never real credentials; no calls to
  the real source system or production.

## Scope and file limit

Maximum **15 repository files changed** — 10 core plus 5 authorized
exceptions:

Core (10):

- `apps/admissions/services.py`
- `apps/discharges/extraction_service.py`
- `apps/deaths/services.py`
- `apps/census/services.py`
- `automation/source_system/admissions/extract_admissions.py`
- `automation/source_system/discharges/extract_discharges.py`
- `automation/source_system/deaths/extract_deaths.py`
- `automation/source_system/official_census/extract_official_census.py`
- `tests/unit/test_historical_extractor_credential_transport.py` (new)
- this change's `tasks.md`

Authorized exceptions (fixture/deferred-P2 updates, minimal edits
preserving unrelated assertions):

- `tests/unit/test_historical_extraction_helpers.py` — only
  credential-transport assertions (argv → scoped env expectations)
- `tests/unit/test_legacy_session_bootstrap.py` — same minimal scope
- `tests/unit/test_persistent_worker_command.py` — same minimal scope
- `tests/unit/test_historical_recovery.py` — only
  `_unconfirmed_zero_result()` shape alignment (S7 P2 #3)
- `tests/unit/test_discharge_zero_confirmation.py` — strictly additive
  2 tests for S7 P2s #1/#2 (failure-stage metadata; confirmation
  timeout `timed_out=True`); do not modify existing tests in the module
  (controller amendment, 2026-09-04: the original 14-file enumeration
  omitted the module its own RED/inspection sections reference)

`subprocess_utils.py` is NOT in the list (its `**kwargs` contract
already accepts a child `env` mapping); any other file means
`INCOMPLETO`. Authorized exceptions are permission, not obligation —
untouched exception files must be reported as such.

## Contract matrix

| Extractor | Required assertion |
| --- | --- |
| admissions | username/password absent from argv; present only in child env |
| discharges | username/password absent from argv; present only in child env |
| deaths | username/password absent from argv; present only in child env |
| official census | username/password absent from argv; present only in child env |
| all entry points | env-first resolution; CLI fallback only when env absent; missing both → fixed non-echoing message, non-zero exit |
| error/timeout paths | no credential value in exception, stdout, stderr, logs or metadata |
| compatibility | date/headless/output/source-URL/reference-date argv unchanged; extraction results unchanged |
| parent env | never mutated (`os.environ` intact after service calls) |
| S7 P2 #1 | failure-stage `discharge_persistence` details_json carries attempt_count/zero_confirmed |
| S7 P2 #2 | confirmation timeout sets `timed_out=True` on the run |
| S7 P2 #3 | recovery mock matches real unconfirmed-zero shape |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| argv limpo nos 4 serviços | 4 arquivos de serviço | unit novo: captura de cmd mockado sem sentinel; sentinel só no env |
| scoped child env | 4 arquivos de serviço | unit novo: `env` contém as 2 chaves override; resto = cópia do ambiente |
| entry points env-first + fallback | 4 scripts automation | unit novo: env presente vence flag; sem ambos → mensagem fixa/exit≠0 sem eco |
| não ecoar credenciais | serviços + scripts | unit novo: sentinel ausente de stdout/stderr/exception/logs |
| comportamento inalterado | 4 serviços | suites existentes verdes (compat argv não-credencial) |
| fixtures atualizadas | 3 testes existentes (exceção) | mesmas suites verdes com asserções env-based |
| S7 P2 #1/#2 | `extraction_service.py` | unit: details_json do stage falho; run.timed_out=True |
| S7 P2 #3 | `test_historical_recovery.py` (exceção) | teste ajustado passa e continua pinando passthrough |

## RED

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_historical_extractor_credential_transport.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_discharge_zero_confirmation.py \
  tests/unit/test_historical_recovery.py"
```

- Falha esperada (unit novo): sentinel AINDA presente no argv capturado
  dos 4 serviços (asserção falha hoje); env sem as chaves; entry points
  aceitando `--username` como única fonte.
- Falha esperada (unit existentes ajustados para os P2s S7): stage de
  persistência-falha sem `attempt_count`; `timed_out` False na
  confirmação expirada; mock com shape antigo.
- Baseline de referência no HEAD (`212b759`): 3380 unit / 595
  integration. Qualquer falha não relacionada deve ser escalada via
  `contact_supervisor`.

## GREEN / verificação local

- Os mesmos comandos focados do RED passam (exit 0).
- `./scripts/test-in-container.sh unit` e `integration` verdes; desvios
  além dos novos/ajustados explicados no relatório.
- `./scripts/test-in-container.sh lint` e `typecheck` sem erro.
- `uv run --no-sync python manage.py makemigrations --check` limpo
  (nenhuma migração esperada).

## Mandatory inspections

```bash
rg -n -U '"--(username|password)"[[:space:]]*,[[:space:]]*(creds\.|username|password)' \
  apps/admissions/services.py apps/discharges/extraction_service.py \
  apps/deaths/services.py apps/census/services.py
rg -n "SOURCE_SYSTEM_USERNAME|SOURCE_SYSTEM_PASSWORD|env=" \
  apps/admissions/services.py apps/discharges/extraction_service.py \
  apps/deaths/services.py apps/census/services.py automation/source_system
rg -n "print\(.*(username|password)|logger\..*(username|password)" \
  apps automation/source_system tests
rg -n "attempt_count|zero_confirmed|timed_out" \
  apps/discharges/extraction_service.py tests/unit/test_discharge_zero_confirmation.py
```

Interpretation: the first rg must return nothing (no credential argv
builders remain); the second shows the scoped env at the four call sites
plus env-first reads in the four entry points; the third must return
nothing credential-bearing; the fourth confirms the S7 P2s landed with
tests. Sentinel values must appear only inside the scoped child `env` of
captured mock calls — never in argv, results, errors or outputs.

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

Inspect every diff against `BASE_REF`. Mark only RPSA-S7A, create one
commit and stop. Do not call the real source or production, and do not
activate timers.

## Automatic `INCOMPLETO`

Leave the task unchecked and make no commit if tree/baseline/dependency
fails, RED is not assertion-level, any historical service keeps
credential values in argv, the parent environment is mutated, a
credential can enter output/errors/logs/metadata, an entry point echoes
the missing field name or a credential value, extraction behavior
regresses, `subprocess_utils.py` or any file outside the 14-file list
changes, a new dependency or migration appears, any S7 deferred P2 lands
without its test, or any gate fails.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S7A-report.md` even if incomplete.
Include status, `BASE_REF`/commit, acceptance and requirement→file→test
matrices, every changed file with before/after snippets, RED/GREEN,
captured argv/environment evidence for all four extractors using
synthetic sentinels (cmd list + env dict per extractor), the three S7-P2
before/after proofs, output-safety inspections, all commands/gates, diff
check, risks and next step. Use valid Markdown and no real credentials
or patient data.
