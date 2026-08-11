# Tasks: add-release-image-hospital-deploy

## 1. Slice RHID-S1 - Publish release image and deploy from one Compose

- [x] 1.1 Read `slice-prompts/SLICE-RHID-S1.md` completely before coding.
- [x] 1.2 Add failing characterization tests for the release workflow and
  standalone hospital Compose contract.
- [x] 1.3 Add a release-published GitHub Actions workflow that gates, builds and
  pushes the exact `prod` image to GHCR with stable/prerelease channel safety.
- [x] 1.4 Add `compose.hospital.yml` with no build/source dependency and one
  exact application version shared by all Django services.
- [x] 1.5 Attach the Compose file to successful releases and document initial
  installation, backup, pull, migration, activation, verification and rollback.
- [x] 1.6 Prove the Compose renders with synthetic configuration and contains no
  build directives or domestic VPN/tunnel services.
- [x] 1.7 Run the official focused gates and create
  `/tmp/sirhosp-slice-RHID-S1-report.md` for independent verification.

## 2. Final verification

- [x] 2.1 Run strict OpenSpec validation for
  `add-release-image-hospital-deploy`.
- [x] 2.2 Run `./scripts/test-in-container.sh check`.
- [x] 2.3 Run the relevant unit tests in the official container.
- [x] 2.4 Run `./scripts/test-in-container.sh lint`.
- [x] 2.5 Run `./scripts/test-in-container.sh typecheck` and document any
  pre-existing notes.
- [x] 2.6 Run Markdown lint for every changed Markdown file.
- [x] 2.7 Commit and push the slice, then stop with the report path and next
  operator step.

## 3. Corrective Slice RHID-S1-C1 - Isolate release gate tests

- [x] 3.1 Read `slice-prompts/SLICE-RHID-S1-C1.md` and diagnose failed GitHub
  Actions run `31485096685`.
- [x] 3.2 Preserve the four gateway cost assertions while supplying complete
  synthetic phase-1 configuration with inherited environment cleared.
- [x] 3.3 Run the focused tests and official quality gate.
- [x] 3.4 Commit, merge and push the correction to `master`.
- [x] 3.5 Publish immutable prerelease `v0.1.0-rc.2` without altering RC1.
- [x] 3.6 Verify successful workflow, exact/prerelease GHCR tags, absent or
  unchanged `latest`, and byte-identical Compose release asset.
- [x] 3.7 Create `/tmp/sirhosp-slice-RHID-S1-C1-report.md` with complete
  corrective evidence.

## 4. Corrective Slice RHID-S1-C2 - Reuse hospital edge network

- [x] 4.1 Read `slice-prompts/SLICE-RHID-S1-C2.md` and the production network
  topology.
- [x] 4.2 Add a failing contract test for external `hospital_edge` and the
  `prisma` web alias.
- [x] 4.3 Attach Django services to `hospital_edge`, keep PostgreSQL internal,
  and preserve the web host port.
- [x] 4.4 Replace obsolete no-external-network assertions in OpenSpec and the
  deployment runbook.
- [x] 4.5 Prove focused tests and synthetic Compose rendering.
- [x] 4.6 Run official checks, tests, lint, typecheck, strict OpenSpec and
  focused Markdown lint.
- [x] 4.7 Create `/tmp/sirhosp-slice-RHID-S1-C2-report.md` with complete
  credential-free evidence.
- [x] 4.8 Commit and push the correction branch for independent verification.

## 5. Integration Slice RHID-S1-C3 - Merge and publish RC3

- [x] 5.1 Read `slice-prompts/SLICE-RHID-S1-C3.md`, verify the correction
  branch, and confirm RC3 is the next immutable prerelease.
- [x] 5.2 Fast-forward the correction into `master` and push the default branch.
- [x] 5.3 Run the official quality gate on the exact integrated commit.
- [x] 5.4 Publish immutable prerelease `v0.1.0-rc.3` without changing RC1 or
  RC2.
- [x] 5.5 Verify the successful release workflow, image tags, `latest` safety,
  matching Compose asset, and hospital edge topology.
- [x] 5.6 Create `/tmp/sirhosp-slice-RHID-S1-C3-report.md`, validate evidence,
  commit the final task state, and push `master`.

## 6. Corrective Slice RHID-S1-C5 - Propagate one-shot census failure

- [x] 6.1 Read `slice-prompts/SLICE-RHID-S1-C5.md` and characterize the observed
  false-success exit status.
- [x] 6.2 Add failing management-command tests for failed, ambiguous and unknown
  one-shot outcomes.
- [x] 6.3 Return nonzero through `CommandError` for those outcomes while keeping
  success, blocked, lock-held, dry-run and loop behavior unchanged.
- [x] 6.4 Add the adaptive-census exit-status delta requirement.
- [x] 6.5 Run focused and official gates and create
  `/tmp/sirhosp-slice-RHID-S1-C5-report.md`.
- [x] 6.6 Commit and push the correction before publishing a new immutable
  prerelease.

## 7. Corrective Slice RHID-S1-C6 - Reuse canonical census login

- [x] 7.1 Read `slice-prompts/SLICE-RHID-S1-C6.md` and reconcile the direct
  `eon` probes with the duplicated census login paths.
- [x] 7.2 Add failing behavioral regressions for password-Enter submission and
  authenticated `#tempoSessao` readiness in both census scripts.
- [x] 7.3 Make the proven bootstrap standalone-safe and reuse it in the official
  and current census extractors without changing later extraction behavior.
- [x] 7.4 Add the production-proven census authentication delta requirement.
- [x] 7.5 Run focused and official gates and create
  `/tmp/sirhosp-slice-RHID-S1-C6-report.md`.
- [x] 7.6 Commit and push the correction before publishing a new immutable
  prerelease.
