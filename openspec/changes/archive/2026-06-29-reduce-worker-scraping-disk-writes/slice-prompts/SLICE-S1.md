# Slice S1 Prompt: Production Worker Runtime Config

## Handoff for a zero-context implementer

You are implementing only Slice S1 of OpenSpec change
`reduce-worker-scraping-disk-writes` in the SIRHOSP repository.

The operational problem is excessive NVMe writes from production Playwright
workers. The dominant workload is `full_sync`, with up to 15 continuously
running `worker` replicas. Scraper debug artifacts are disposable. The host has
about 62 GiB RAM, 8 GiB swap and `vm.swappiness=10`.

Read these files before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/proposal.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/design.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/specs/production-worker-runtime-io-control/spec.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/tasks.md`

## Scope

Implement only production `worker` runtime configuration.

Allowed repository files for this slice:

- `compose.prod.yml`
- one focused unit test file under `tests/unit/`
- `openspec/changes/reduce-worker-scraping-disk-writes/tasks.md`, only if you
  mark completed S1 tasks after evidence exists

Do not modify scraper Python code, `Dockerfile`, `compose.yml`,
`compose.dev.yml`, `compose.test.yml`, `deploy/README.md`, database code,
summary worker, web service or Tailscale service in this slice.

If you need to exceed this scope, stop and report the blocker.

## Implementation intent

Update the production `worker` service in `compose.prod.yml` with:

```yaml
shm_size: "${WORKER_SHM_SIZE:-512m}"
tmpfs:
  - "/tmp:size=${WORKER_TMPFS_TMP_SIZE:-1g},mode=1777"
  - "/var/tmp:size=${WORKER_TMPFS_VAR_TMP_SIZE:-128m},mode=1777"
  - "/home/10001/.cache:size=${WORKER_TMPFS_CACHE_SIZE:-256m},uid=10001,gid=10001,mode=700"
  - "/home/10001/.config:size=${WORKER_TMPFS_CONFIG_SIZE:-64m},uid=10001,gid=10001,mode=700"
```

Add these environment variables to the same `worker` service:

```text
TMPDIR=/tmp
TEMP=/tmp
TMP=/tmp
XDG_CACHE_HOME=/tmp/xdg-cache
XDG_CONFIG_HOME=/tmp/xdg-config
```

Add Docker log rotation to the same `worker` service:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

Keep the change minimal and readable. Prefer explicit YAML over cleverness.

## Engineering methodology

Use TDD, clean code, DRY and YAGNI:

1. Red: add a focused unit test that fails against the current
   `compose.prod.yml` because the production `worker` lacks tmpfs, `shm_size`,
   required environment variables and log rotation.
2. Green: make the minimal YAML change to satisfy the test and spec.
3. Refactor: simplify the test and YAML if needed, without broadening scope.

The test should avoid new dependencies. Reading the Compose file as text is
acceptable for this config characterization test. Do not include real secrets.

## Required validation

Run at least:

```bash
./scripts/test-in-container.sh unit
```

Also render production Compose with synthetic secrets and do not print secrets
in the report:

```bash
DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=localhost POSTGRES_PASSWORD=x \
TS_AUTHKEY=x docker compose -f compose.yml -f compose.prod.yml config \
>/tmp/sirhosp-rwsdw-s1-compose-config.yml
```

Then inspect only the `worker` section in the generated temp file. If time and
environment allow, also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If a command cannot run, document the reason clearly.

## Acceptance criteria

- The focused test fails before the YAML change and passes after it.
- `compose.prod.yml` changes only the production `worker` service.
- Rendered Compose includes bounded tmpfs mounts for `/tmp`, `/var/tmp`,
  `/home/10001/.cache` and `/home/10001/.config`.
- Rendered Compose includes `shm_size` with `WORKER_SHM_SIZE` override support.
- Rendered Compose includes `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` and
  `XDG_CONFIG_HOME` in the production `worker` environment.
- Rendered Compose includes bounded Docker log rotation for `worker`.
- No credentials, patient data, PDFs, dumps or debug artifacts are committed.
- Markdown files touched by this slice pass markdown lint.

## Required report

Create `/tmp/sirhosp-slice-RWSDW-S1-report.md` with:

- summary of the slice;
- checklist of acceptance criteria;
- files changed;
- before/after snippets for every changed repository file;
- red/green/refactor evidence;
- commands executed and results;
- risks, pending work and suggested next step.

Do not include real credentials or patient data in the report.
