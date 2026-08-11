# Slice Prompt - RHID-S1-C1 Release Gate Test Isolation

## Handoff

Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` OpenSpec change, GitHub Actions run
`31485096685` failure output and this prompt before editing.

RHID-S1 was merged at `9e4509d` and prerelease `v0.1.0-rc.1` triggered the new
workflow. Its validation job correctly blocked publication: four
`TestCallLlmGatewayCost` tests depended on an API key inherited from the local
`.env`, but GitHub Actions intentionally has no production LLM secret. Local
quality gate passed only because the container entrypoint loaded that `.env`.
No image or Compose asset was published for RC1.

## Objective

Make the four unit tests self-contained with synthetic phase-1 configuration,
then publish a new immutable RC tag and verify the complete image/asset flow.
Do not inject production credentials into CI and do not weaken the release gate.

## Scope

Allowed implementation file:

- `tests/unit/test_phase1_cost.py`.

Control artifacts:

- this prompt;
- `openspec/changes/add-release-image-hospital-deploy/tasks.md`;
- `/tmp/sirhosp-slice-RHID-S1-C1-report.md`.

Do not modify application code, GitHub workflow, Compose, migrations, settings
or an existing release/tag.

## Requirements

1. Preserve the four existing observable gateway cost assertions.
2. Supply complete synthetic `SUMMARY_PHASE1_*` configuration for every test in
   `TestCallLlmGatewayCost`.
3. Clear inherited environment during those tests so local `.env` values cannot
   determine the result.
4. Keep the OpenAI client mocked; no network or real key may be used.
5. Run focused and official quality gates.
6. Merge the correction to `master` and publish `v0.1.0-rc.2`; do not move or
   delete failed `v0.1.0-rc.1`.
7. Verify the workflow succeeds, exact and `prerelease` GHCR tags exist,
   `latest` was not created by the prerelease, and `compose.hospital.yml` is
   attached.

## TDD

### RED

Use the failed GitHub validation run as the RED evidence:

```text
4 failed, 2347 passed
RuntimeError: No LLM API key found
```

### GREEN

Add only synthetic test configuration with `patch.dict(..., clear=True)` around
the affected class. Run the four tests and the official quality gate.

### REFACTOR

Keep one class-level environment contract rather than duplicating configuration
inside four methods. Use obvious synthetic values and no helper abstraction.

## Acceptance Gates

- [ ] Four previously failing tests pass without ambient LLM variables.
- [ ] No real credential or GitHub secret is added.
- [ ] Full official quality gate passes on the corrected commit.
- [ ] `master` contains the correction.
- [ ] RC2 workflow succeeds at the corrected `master` commit.
- [ ] Exact RC2 and moving prerelease image tags resolve in GHCR.
- [ ] Release asset is downloadable and byte-identical to the tagged Compose.
- [ ] `latest` remains absent or unchanged by RC2.
- [ ] Temporary report records RED/GREEN, commit, run, image digests and asset
  checksum.

## Required Report

Create `/tmp/sirhosp-slice-RHID-S1-C1-report.md` with root cause, before/after
fragment, failed RC1 evidence, local and GitHub gate results, changed files,
release URLs, image/asset verification, risks and next step. Run markdownlint on
the report, commit and push, then stop.
