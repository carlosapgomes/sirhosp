# Slice Prompt - RHID-S1-C2 Hospital Edge Network

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` OpenSpec change, `compose.hospital.yml`,
`compose.prod.yml`, `deploy/README.md`, the prior RHID reports under `/tmp`, and
this prompt before editing.

RHID-S1 published the standalone hospital Compose in `v0.1.0-rc.2`, but its
network contract incorrectly excluded external networks. The hospital already
runs Cloudflared on the external Docker network `hospital_edge`; that container
routes the application FQDN to the established `prisma` alias. Therefore the
release Compose must preserve the relevant network topology from
`compose.prod.yml` without bundling Cloudflared or Tailscale.

## Scope and file limit

Modify no more than these eight tracked files:

1. `compose.hospital.yml`
2. `tests/unit/test_release_hospital_deploy.py`
3. `deploy/README.md`
4. `openspec/changes/add-release-image-hospital-deploy/proposal.md`
5. `openspec/changes/add-release-image-hospital-deploy/design.md`
6. `openspec/changes/add-release-image-hospital-deploy/specs/release-image-hospital-deploy/spec.md`
7. `openspec/changes/add-release-image-hospital-deploy/tasks.md`
8. `openspec/changes/add-release-image-hospital-deploy/slice-prompts/SLICE-RHID-S1-C2.md`

Do not modify application Python, settings, migrations, the release workflow,
Dockerfile, `compose.yml`, `compose.prod.yml`, domestic tunnel services, or
clinical behavior. If another tracked file is required, stop and report the
blocker rather than expanding scope.

## Required change

1. Add a failing contract test proving the current hospital Compose lacks the
   required edge topology.
2. Declare `hospital_edge` as an external network named exactly
   `hospital_edge`.
3. Keep PostgreSQL attached only to the standalone internal network.
4. Attach every Django service to both the internal network and
   `hospital_edge`, matching the production topology inherited by application
   services.
5. Give only `web` the `prisma` alias on `hospital_edge`, so the existing
   Cloudflared origin `http://prisma:8000` remains valid.
6. Do not add a Cloudflared or Tailscale service and do not remove the existing
   web host-port binding.
7. Update proposal, design, specification and runbook to replace the obsolete
   no-external-network assertion. Document an explicit preflight that verifies
   the existing network and Cloudflared membership before startup.
8. Render the Compose with synthetic values and ensure no secret value is
   captured in tracked artifacts or the report.

## Acceptance criteria

- [ ] RED fails because `hospital_edge` and `prisma` are absent.
- [ ] Focused contract tests pass after the change.
- [ ] `docker compose --env-file /dev/null -f compose.hospital.yml config
      --quiet` succeeds with every required variable supplied synthetically.
- [ ] Rendered `web` joins `internal` and `hospital_edge` and has alias `prisma`.
- [ ] Rendered workers join both networks.
- [ ] Rendered `db` joins only `internal`.
- [ ] `hospital_edge` is external and Compose does not create a substitute.
- [ ] No bundled Tailscale/Cloudflared service, source checkout or local build is
      introduced.
- [ ] Strict OpenSpec, official tests, lint, typecheck and focused Markdown lint
      pass.
- [ ] `/tmp/sirhosp-slice-RHID-S1-C2-report.md` records literal before/after
      fragments, RED/GREEN proof, commands, results, risks and next operator
      action without credentials or patient data.

## Stop rule

Use TDD: RED, minimum GREEN, then controlled cleanup. Run only the official
container commands for final gate claims. Update task checkboxes only after the
corresponding evidence exists. Create the required report, commit and push the
correction branch, then stop for independent verification; do not publish or
replace another release without an explicit operator decision.
