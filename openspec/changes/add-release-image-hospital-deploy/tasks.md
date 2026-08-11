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
