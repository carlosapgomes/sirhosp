# Slice DHRR-S1 Prompt: Dedicated Historical Recovery Runtime Wiring

## Handoff for a zero-context implementer

You are implementing only Slice DHRR-S1 of OpenSpec change
`dedicated-historical-recovery-runtime` in the SIRHOSP repository.

The operational problem: `recover_historical_data` runs Playwright/Chromium
scraping for historical discharges, admissions, deaths and official census.
Operators need to run this as manual batches without putting browser
temporaries, downloads and caches in the portal `web` runtime or on Docker
overlay/NVMe when tmpfs can absorb ephemeral writes.

The desired outcome for this slice is a dedicated production Compose
service/runtime named `historical_recovery`. It is batch-only and operator-run;
it is not a daemon, not a timer and not a new Python orchestration layer.

Read these files completely before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/dedicated-historical-recovery-runtime/proposal.md`
- `openspec/changes/dedicated-historical-recovery-runtime/design.md`
- `openspec/changes/dedicated-historical-recovery-runtime/specs/production-historical-recovery-runtime/spec.md`
- `openspec/changes/dedicated-historical-recovery-runtime/specs/historical-recovery-command/spec.md`
- `openspec/changes/dedicated-historical-recovery-runtime/tasks.md`
- `compose.prod.yml`
- `tests/unit/test_prod_worker_runtime_io.py`
- `tests/unit/test_prod_orchestrator_runtime_io.py`

## Scope

Implement only production runtime wiring and focused runtime tests.

Allowed repository files for this slice:

- `compose.prod.yml`
- one focused unit test file under `tests/unit/`
- `openspec/changes/dedicated-historical-recovery-runtime/tasks.md`, only if
  you mark completed DHRR-S1 tasks after evidence exists

Do not modify Python command code, scraping code, extractor services, database
models, `Dockerfile`, `compose.yml`, `deploy/README.md`, `README.md`, systemd
units or `AGENTS.md` in this slice.

If you need to exceed this scope, stop and report the blocker.

## Implementation intent

Add a production Compose service named `historical_recovery`.

Expected runtime shape:

```yaml
historical_recovery:
  profiles: ["recovery"]
  build:
    context: .
    dockerfile: Dockerfile
    target: prod
  container_name: sirhosp-historical-recovery
  init: true
```

The service must include:

- Django/PostgreSQL/source-system/proxy environment needed to run management
  commands;
- `UV_PROJECT_ENVIRONMENT=/opt/venv`, `UV_CACHE_DIR=/opt/.uv_cache` and
  `UV_NO_CACHE=1`;
- `depends_on` for healthy `db`;
- `default` and `hospital_edge` networks, equivalent to scraping-capable
  production services;
- no long-running restart behavior. Prefer `restart: "no"` or omit restart
  entirely if tests and design agree.

The service is for manual `docker compose run --rm` batches. Its default command
must be safe and non-mutating. Prefer a help command:

```yaml
command:
  - uv
  - run
  - --no-sync
  - python
  - manage.py
  - recover_historical_data
  - --help
```

Actual operator batches will override this command with the full management
command in documentation, for example:

```bash
docker compose -f compose.yml -f compose.prod.yml --profile recovery run \
  --rm historical_recovery uv run --no-sync python manage.py \
  recover_historical_data --date 01/06/2026 --extractor admissions
```

Add volatile runtime settings with recovery-specific variables:

```yaml
shm_size: "${HISTORICAL_RECOVERY_SHM_SIZE:-1g}"
tmpfs:
  - "/tmp:size=${HISTORICAL_RECOVERY_TMPFS_TMP_SIZE:-2g},mode=1777"
  - "/var/tmp:size=${HISTORICAL_RECOVERY_TMPFS_VAR_TMP_SIZE:-256m},mode=1777"
  - "/home/10001/.cache:size=${HISTORICAL_RECOVERY_TMPFS_CACHE_SIZE:-512m},uid=10001,gid=10001,mode=700"
  - "/home/10001/.config:size=${HISTORICAL_RECOVERY_TMPFS_CONFIG_SIZE:-128m},uid=10001,gid=10001,mode=700"
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

Keep the YAML explicit and boring. Avoid anchors or clever abstractions unless
there is already a project pattern requiring them.

## Engineering methodology

Use TDD, clean code, DRY and YAGNI:

1. **Red:** add focused characterization tests that fail because
   `historical_recovery` does not exist in `compose.prod.yml`.
2. **Green:** make the minimal Compose change to satisfy the tests and specs.
3. **Refactor:** simplify test helpers and YAML comments if needed, without
   expanding scope.

The tests may read `compose.prod.yml` as text, matching the existing style in
`tests/unit/test_prod_worker_runtime_io.py` and
`tests/unit/test_prod_orchestrator_runtime_io.py`. Do not add a YAML parser
dependency.

Suggested test coverage:

- service block exists and uses profile `recovery`;
- production build target is used;
- command is safe/non-mutating and references `recover_historical_data --help`;
- service does not run `web`, Gunicorn, a loop or a scheduler;
- tmpfs mounts exist for `/tmp`, `/var/tmp`, `.cache` and `.config`;
- tmpfs defaults use `HISTORICAL_RECOVERY_TMPFS_*` variables and explicit
  bounds;
- `shm_size` uses `HISTORICAL_RECOVERY_SHM_SIZE:-1g`;
- temp/cache environment variables point to volatile paths;
- source-system and proxy environment variables are present;
- service depends on healthy `db` and joins `hospital_edge`;
- Docker log rotation is bounded;
- restart behavior is not long-running daemon style.

## Required validation

Run at least:

```bash
./scripts/test-in-container.sh unit
```

Render production Compose with synthetic secrets and do not print secrets in the
report:

```bash
DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=localhost POSTGRES_PASSWORD=x \
SOURCE_SYSTEM_URL= SOURCE_SYSTEM_USERNAME= SOURCE_SYSTEM_PASSWORD= \
  docker compose -f compose.yml -f compose.prod.yml --profile recovery \
  config >/tmp/sirhosp-dhrr-s1-compose-config.yml
```

Inspect only the `historical_recovery` section in the generated temp file. Do
not include interpolated credentials in the report. Delete the temp file after
inspection if it contains local `.env` values.

If time and environment allow, also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate dedicated-historical-recovery-runtime --type change --strict
```

If a command cannot run, document the reason clearly.

## Acceptance criteria

- The focused tests fail before implementation and pass after implementation.
- `compose.prod.yml` defines `historical_recovery` without changing existing
  worker or census orchestrator tmpfs contracts.
- The service is behind an explicit `recovery` profile.
- The default service command is safe and non-mutating.
- Operator batch execution can override the command with
  `recover_historical_data` and its existing CLI options.
- The service has bounded tmpfs mounts for `/tmp`, `/var/tmp`,
  `/home/10001/.cache` and `/home/10001/.config`.
- The service has `shm_size` with `HISTORICAL_RECOVERY_SHM_SIZE` override
  support.
- The service defines `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` and
  `XDG_CONFIG_HOME` for volatile runtime paths.
- The service has bounded Docker log rotation.
- The service is not configured as a long-running loop, timer or systemd unit.
- No credentials, patient data, PDFs, dumps or debug artifacts are committed.
- Markdown files touched by this slice pass markdown lint.

## Required report

Create `/tmp/sirhosp-slice-DHRR-S1-report.md` with:

- summary of the slice;
- checklist of acceptance criteria;
- files changed;
- before/after snippets for every changed repository file;
- red/green/refactor evidence;
- commands executed and results;
- rendered Compose validation summary without secrets;
- risks, pending work and suggested next step.

Do not include real credentials or patient data in the report.
