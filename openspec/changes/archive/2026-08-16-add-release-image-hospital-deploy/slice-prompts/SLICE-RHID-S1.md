# Slice Prompt - RHID-S1 Release Image and Hospital Compose

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, then read these
files completely:

- `openspec/changes/add-release-image-hospital-deploy/proposal.md`;
- `openspec/changes/add-release-image-hospital-deploy/design.md`;
- `openspec/changes/add-release-image-hospital-deploy/tasks.md`;
- `openspec/changes/add-release-image-hospital-deploy/specs/release-image-hospital-deploy/spec.md`;
- `.github/workflows/quality-gate.yml`;
- `Dockerfile`;
- `compose.yml` and `compose.prod.yml` only to reuse existing runtime contracts;
- `deploy/README.md`.

The domestic runtime currently builds locally and uses Tailscale/Cloudflared. It
must remain unchanged. This slice adds a separate hospital deployment artifact:
a GitHub release builds the validated `prod` image in GHCR and distributes one
standalone Compose that pulls an exact version without a repository checkout.

## Objective

Deliver this complete vertical flow:

```text
published release or prerelease -> official gate -> exact GHCR image
-> matching Compose release asset -> operator backup/migrate/up/health flow
```

## Scope Limits

Expected implementation files, excluding this OpenSpec change and the temporary
report:

1. `.github/workflows/publish-release-image.yml`;
2. `compose.hospital.yml`;
3. `tests/unit/test_release_hospital_deploy.py`;
4. `deploy/README.md`.

Do not modify application Python, models, migrations, settings, Dockerfile,
existing Compose files, Tailscale/Cloudflared topology or clinical behavior. If
a fifth implementation file becomes necessary, stop and document the blocker
instead of expanding silently.

## Requirements

### R1 - Exact validated release image

The workflow MUST react to a published stable release or prerelease, checkout
its exact tag, execute `./scripts/test-in-container.sh quality-gate`, and only
then build/push Dockerfile target `prod` to
`ghcr.io/${{ github.repository }}`.

### R2 - Safe image channels

The exact release tag MUST always be published. `latest` MUST be updated only by
a stable release. `prerelease` MUST be updated only by a prerelease. Include OCI
metadata, SBOM and BuildKit provenance. Do not publish credentials or `.env`.

### R3 - Release asset

After a successful image push, attach `compose.hospital.yml` to that same GitHub
release. A failed gate or build MUST leave no asset uploaded by the failed run.

### R4 - One standalone Compose

The Compose MUST:

- contain no `build:` and no source bind mount;
- require an exact `SIRHOSP_VERSION`;
- point every Django service to
  `ghcr.io/carlosapgomes/sirhosp:${SIRHOSP_VERSION}`;
- include `db`, `web`, `persistent_worker`, `census_orchestrator` and
  `summary_worker`;
- persist PostgreSQL in a named volume and not publish its port;
- publish only the configured web port;
- retain health checks, restart policies and isolated Playwright tmpfs/profile
  behavior needed by the current runtime;
- have no Tailscale, Cloudflared or external-network dependency;
- keep all secrets host-local and fail interpolation for critical values.

### R5 - Operator-controlled deployment

Extend `deploy/README.md` with a clearly separated hospital image deployment
section. Document prerequisites, optional GHCR login, release asset download,
synthetic `.env` keys, `config --quiet`, PostgreSQL backup, `pull`, database
startup, one-shot `migrate --noinput`, `up -d --remove-orphans`, health checks,
worker scaling and exact-tag rollback. State that incompatible schema downgrade
requires coordinated database restoration.

### R6 - Domestic runtime preservation

Do not edit or repurpose `compose.yml` or `compose.prod.yml`. The existing home
server remains a pre-production/dev validation environment.

## TDD Protocol

### RED

Create `tests/unit/test_release_hospital_deploy.py` first. It must fail because
the workflow and standalone Compose do not exist. Tests must characterize:

- release trigger, exact checkout and official gate-before-publish dependency;
- exact, stable and prerelease tag rules;
- GHCR login, target `prod`, push, SBOM, provenance and release asset upload;
- no `build:`, no domestic tunnel services and no external network in the
  hospital Compose;
- exact shared application version, required secrets, service commands,
  persistent DB volume and web-only host port.

Capture the failing command and assertion in the report.

### GREEN

Add the minimum workflow, Compose and runbook changes that satisfy the tests and
requirements. Do not add a deployment agent, Watchtower, SSH automation,
Kubernetes, proxy server or secret manager.

### REFACTOR

Remove duplication with YAML extension fields only when it remains clear to
operators. Apply clean code, DRY and YAGNI. Keep service names and commands
aligned with existing production runtime.

## Acceptance Criteria

- [ ] RED failure was observed before workflow/Compose creation.
- [ ] Stable and prerelease publishing cannot overwrite each other's channel.
- [ ] Publishing waits for the official quality gate.
- [ ] Exact release tag is the application version used by the hospital host.
- [ ] Compose has one file, no `build:` and no repository checkout dependency.
- [ ] PostgreSQL is persistent and only web publishes a host port.
- [ ] No domestic VPN/tunnel service is present.
- [ ] Synthetic `docker compose config --quiet` succeeds.
- [ ] Runbook covers install, backup, migration, update, verification and
  rollback limitations.
- [ ] Existing domestic Compose files remain byte-for-byte unchanged.
- [ ] Focused tests and official gates pass.
- [ ] OpenSpec strict validation and Markdown lint pass.

## Self-Evaluation Gates

Answer each question with evidence in the report:

1. Can a prerelease update `latest` by any workflow path?
2. Can an image publish if the official gate fails?
3. Can the hospital Compose build local source or silently choose a version?
4. Does any service other than `web` publish a host port?
5. Can missing critical secrets reach container startup?
6. Does deployment preserve PostgreSQL data across recreation?
7. Does rollback guidance distinguish application rollback from schema restore?
8. Were domestic Tailscale/Cloudflared and existing Compose files untouched?
9. Does the rendered Compose use one exact image for every Django service?
10. Did any output or tracked file expose real credentials or patient data?

## Required Validation

Run:

```bash
uv run pytest -q tests/unit/test_release_hospital_deploy.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-release-image-hospital-deploy --strict
./scripts/markdown-lint.sh
```

Also render the standalone Compose with synthetic non-secret values and
`docker compose -f compose.hospital.yml config --quiet`. Never print rendered
configuration populated from a real `.env`.

## Required Report

Create `/tmp/sirhosp-slice-RHID-S1-report.md` containing:

- status and commit;
- acceptance checklist;
- exact files changed;
- literal before/after fragments for each implementation file;
- RED and GREEN commands/results;
- Compose render proof using only synthetic values;
- all validation commands and outcomes;
- answers to all self-evaluation gates;
- risks, limitations and next operator step;
- confirmation that no real secrets or patient data are present.

Run Markdown lint on the report. Commit and push only after all gates pass, then
reply with `REPORT_PATH=/tmp/sirhosp-slice-RHID-S1-report.md` and stop.

## Prompt Ready for the Implementer

Read `AGENTS.md`, `PROJECT_CONTEXT.md` and every RHID-S1 OpenSpec artifact first.
Implement ONLY RHID-S1 and keep the implementation to the four allowed files.
Use TDD: RED, then minimum GREEN, then controlled REFACTOR with clean code, DRY
and YAGNI. Do not alter application code, existing Compose files, networks,
models, migrations or the domestic runtime. Run every required validation,
update `tasks.md` only after evidence passes, create the mandatory temporary
report with before/after fragments and self-evaluation answers, commit, push and
STOP for independent verification.
