# Slice DCOS-S1 Prompt: Dedicated Orchestrator Runtime Wiring

## Handoff for a zero-context implementer

You are implementing only Slice DCOS-S1 of OpenSpec change
`dedicated-census-orchestrator-service` in the SIRHOSP repository.

The operational problem: production ingestion workers already use tmpfs, but
the first phase of the adaptive census cycle (`extract_census`) currently runs
through the `web` service when operators invoke `run_adaptive_census_cycles`.
The `web` service has no tmpfs and also serves the Django portal. This slice
creates the dedicated production runtime for the continuous census
orchestrator.

Read these files completely before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/dedicated-census-orchestrator-service/proposal.md`
- `openspec/changes/dedicated-census-orchestrator-service/design.md`
- `openspec/changes/dedicated-census-orchestrator-service/specs/production-census-orchestrator-runtime/spec.md`
- `openspec/changes/dedicated-census-orchestrator-service/specs/adaptive-census-orchestration/spec.md`
- `openspec/changes/dedicated-census-orchestrator-service/tasks.md`

## Scope

Implement only the production runtime wiring.

Allowed repository files for this slice:

- `compose.prod.yml`
- `deploy/systemd/sirhosp-census-orchestrator.service`
- one focused unit test file under `tests/unit/`
- `openspec/changes/dedicated-census-orchestrator-service/tasks.md`, only if
  you mark completed DCOS-S1 tasks after evidence exists

Do not modify Python orchestration code, scraping code, database models,
`Dockerfile`, `compose.yml`, `compose.dev.yml`, `deploy/README.md`, `README.md`
or `AGENTS.md` in this slice.

If you need to exceed this scope, stop and report the blocker.

## Implementation intent

Add a production Compose service named `census_orchestrator`.

Expected runtime shape:

```yaml
census_orchestrator:
  profiles: ["orchestrator"]
  build:
    context: .
    dockerfile: Dockerfile
    target: prod
  container_name: sirhosp-census-orchestrator
  init: true
  command:
    - uv
    - run
    - --no-sync
    - python
    - manage.py
    - run_adaptive_census_cycles
    - --loop
```

The service must include the Django/PostgreSQL/source-system/proxy environment
needed to run the command, `depends_on` for `db`, and networks equivalent to the
worker for source-system access.

Add volatile runtime settings with orchestrator-specific variables:

```yaml
shm_size: "${CENSUS_ORCHESTRATOR_SHM_SIZE:-512m}"
tmpfs:
  - "/tmp:size=${CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE:-1g},mode=1777"
  - "/var/tmp:size=${CENSUS_ORCHESTRATOR_TMPFS_VAR_TMP_SIZE:-128m},mode=1777"
  - "/home/10001/.cache:size=${CENSUS_ORCHESTRATOR_TMPFS_CACHE_SIZE:-256m},uid=10001,gid=10001,mode=700"
  - "/home/10001/.config:size=${CENSUS_ORCHESTRATOR_TMPFS_CONFIG_SIZE:-64m},uid=10001,gid=10001,mode=700"
```

Add these environment variables to the same service:

```text
TMPDIR=/tmp
TEMP=/tmp
TMP=/tmp
XDG_CACHE_HOME=/tmp/xdg-cache
XDG_CONFIG_HOME=/tmp/xdg-config
```

Add bounded Docker log rotation to the same service:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

Update `deploy/systemd/sirhosp-census-orchestrator.service` so it starts and
stops the dedicated service. It must not call `docker compose exec -T web`.
A foreground `docker compose ... --profile orchestrator up census_orchestrator`
style command is preferred for `ExecStart`, with a matching `ExecStop`.

Keep the YAML explicit and boring. Avoid anchors or clever abstractions unless
there is already a project pattern requiring them.

## Engineering methodology

Use TDD, clean code, DRY and YAGNI:

1. **Red:** add focused characterization tests that fail against the current
   repository because `census_orchestrator` does not exist and systemd still
   executes the loop through `web`.
2. **Green:** make the minimal Compose and systemd changes to satisfy the tests
   and specs.
3. **Refactor:** simplify test helpers and YAML comments if needed, without
   expanding scope.

The tests may read `compose.prod.yml` and the systemd unit as text, matching the
existing style in `tests/unit/test_prod_worker_runtime_io.py`. Do not add a YAML
parser dependency.

## Required validation

Run at least:

```bash
./scripts/test-in-container.sh unit
```

Render production Compose with synthetic secrets and do not print secrets in
the report:

```bash
DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=localhost POSTGRES_PASSWORD=x \
  docker compose -f compose.yml -f compose.prod.yml --profile orchestrator \
  config >/tmp/sirhosp-dcos-s1-compose-config.yml
```

Inspect only the `census_orchestrator` section in the generated temp file.
If time and environment allow, also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If a command cannot run, document the reason clearly.

## Acceptance criteria

- The focused tests fail before implementation and pass after implementation.
- `compose.prod.yml` defines `census_orchestrator` without changing the worker
  tmpfs contract.
- The dedicated service runs `run_adaptive_census_cycles --loop`.
- The dedicated service has bounded tmpfs mounts for `/tmp`, `/var/tmp`,
  `/home/10001/.cache` and `/home/10001/.config`.
- The dedicated service has `shm_size` with
  `CENSUS_ORCHESTRATOR_SHM_SIZE` override support.
- The dedicated service defines `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` and
  `XDG_CONFIG_HOME` for volatile runtime paths.
- The dedicated service has bounded Docker log rotation.
- The systemd unit starts/stops `census_orchestrator` and no longer uses
  `docker compose exec -T web` for the loop.
- No credentials, patient data, PDFs, dumps or debug artifacts are committed.
- Markdown files touched by this slice pass markdown lint.

## Required report

Create `/tmp/sirhosp-slice-DCOS-S1-report.md` with:

- summary of the slice;
- checklist of acceptance criteria;
- files changed;
- before/after snippets for every changed repository file;
- red/green/refactor evidence;
- commands executed and results;
- rendered Compose validation summary without secrets;
- risks, pending work and suggested next step.

Do not include real credentials or patient data in the report.
