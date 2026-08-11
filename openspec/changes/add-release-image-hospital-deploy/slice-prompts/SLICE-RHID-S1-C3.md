# Slice Prompt - RHID-S1-C3 Integrate and Publish RC3

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` OpenSpec change, all RHID slice prompts,
`/tmp/sirhosp-slice-RHID-S1-C2-report.md`, the current Git branch topology and
this prompt before acting.

RHID-S1-C2 corrected `compose.hospital.yml` so the hospital release stack joins
the existing external `hospital_edge` network and exposes `web` through alias
`prisma`. The correction is committed and pushed on
`fix/hospital-compose-edge-network`. The operator explicitly authorized merging
it into the repository default branch and publishing a new prerelease.

## Scope and file limit

This is an integration and release-evidence slice. It may modify only:

1. `openspec/changes/add-release-image-hospital-deploy/tasks.md`
2. `openspec/changes/add-release-image-hospital-deploy/slice-prompts/SLICE-RHID-S1-C3.md`

It must create the untracked report
`/tmp/sirhosp-slice-RHID-S1-C3-report.md`. Do not change application code,
Compose files, workflows, tests, migrations, settings or other documentation.
If any implementation change is required, stop and report the blocker instead
of expanding scope.

## Required sequence

1. Confirm the correction branch is clean, synchronized and contains commits
   `c682648` and `9286bd0` after the current default branch.
2. Integrate it into `master` using fast-forward only and push `master`.
3. Run `./scripts/test-in-container.sh quality-gate` on the exact integrated
   commit before creating a release.
4. Publish immutable GitHub prerelease `v0.1.0-rc.3` targeting the exact
   integrated commit. Do not edit, move or delete RC1 or RC2.
5. Wait for `Publish Release Image` and require both validation and publication
   jobs to succeed.
6. Independently verify:
   - the workflow head SHA equals the RC3 tag commit;
   - exact `v0.1.0-rc.3` and moving `prerelease` GHCR tags resolve to one digest;
   - `latest` remains absent or unchanged;
   - RC1 and RC2 remain unchanged;
   - the RC3 `compose.hospital.yml` asset is byte-identical to the file at the
     RC3 tag;
   - the downloaded asset contains external `hospital_edge`, web alias
     `prisma`, and internal-only PostgreSQL.
7. Record all evidence in the report without credentials, rendered environment
   values or patient data.

## Acceptance criteria

- [ ] Correction is fast-forwarded and pushed to `master`.
- [ ] Official quality gate passes on the exact pre-release commit.
- [ ] RC3 is a published prerelease and points to that commit.
- [ ] GitHub release workflow succeeds completely.
- [ ] Exact and `prerelease` image tags share one OCI index digest.
- [ ] `latest` is not moved by RC3.
- [ ] RC3 release contains exactly the matching `compose.hospital.yml` asset.
- [ ] Asset digest equals the tagged source digest.
- [ ] Asset preserves `hospital_edge`, `prisma`, and database isolation.
- [ ] RC1 and RC2 evidence remains immutable.
- [ ] Strict OpenSpec and Markdown lint pass for the evidence artifacts.
- [ ] Final report names commits, tags, workflow, digests, commands, results,
      risks and the next hospital-host step.

## Stop rule

Do not weaken or bypass a failing quality gate. If the release workflow fails,
preserve the failed RC, diagnose the cause and use a new immutable RC only after
an explicit corrective slice. Update task checkboxes only after evidence exists.
Commit and push the final task state, then stop with the report path and release
URLs.
