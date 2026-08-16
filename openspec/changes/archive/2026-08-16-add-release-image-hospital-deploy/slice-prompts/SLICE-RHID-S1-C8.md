# Slice Prompt - RHID-S1-C8 Immutable Release Publication

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` change, the current release workflow,
`compose.hospital.yml`, `tests/unit/test_release_hospital_deploy.py`, the hospital
section of `deploy/README.md`, and this prompt before editing.

RC5 is running successfully in hospital production. The existing workflow reacts
after a release is published and then uploads the Compose with `--clobber`.
GitHub immutable releases lock the Git tag and release assets at publication, so
the current order would fail once repository immutability is enabled. Future
releases must instead be assembled as drafts, validated and populated before
publication.

## Objective

Correct the stale persistent-worker documentation and change future publication
to this controlled flow:

```text
manual workflow dispatch for an existing exact tag
-> official quality gate
-> require repository immutable releases
-> reject an existing exact GHCR image tag
-> create draft with Compose asset
-> build and push image
-> publish and verify immutable release
```

Existing RC1-RC5 releases and the running RC5 deployment must remain unchanged.

## Scope and file limit

Modify no more than these eight tracked files:

1. `.github/workflows/publish-release-image.yml`
2. `tests/unit/test_release_hospital_deploy.py`
3. `deploy/README.md`
4. `openspec/changes/add-release-image-hospital-deploy/proposal.md`
5. `openspec/changes/add-release-image-hospital-deploy/design.md`
6. `openspec/changes/add-release-image-hospital-deploy/specs/release-image-hospital-deploy/spec.md`
7. `openspec/changes/add-release-image-hospital-deploy/tasks.md`
8. `openspec/changes/add-release-image-hospital-deploy/slice-prompts/SLICE-RHID-S1-C8.md`

Create `/tmp/sirhosp-slice-RHID-S1-C8-report.md`. Do not modify application
Python, Compose files, Dockerfile, existing releases/tags/assets, migrations,
settings, clinical behavior or the hospital host.

## Requirements

### R1 - Immutable-safe publication order

Replace the post-publication release trigger with an explicit
`workflow_dispatch` contract receiving an existing exact release tag and a
prerelease boolean. Validate the tag with the official quality gate first. The
publication job must use the validated commit, require repository immutable
releases to be enabled, create a draft containing `compose.hospital.yml`, build
and push the image, publish the draft, and verify that GitHub reports the release
as immutable.

### R2 - Exact image protection and channels

Refuse to continue if the exact GHCR image tag already exists. Always publish the
new exact tag, update `latest` only for stable releases and update `prerelease`
only for prereleases. Preserve OCI metadata, SBOM and provenance.

### R3 - No post-publication asset mutation

Remove `--clobber` and ensure the Compose asset is attached while the release is
a draft. No step may upload or edit an asset after publication.

### R4 - Accurate production documentation

Replace the stale `NOT rollout-ready` persistent-worker section with the current
production state: RC5 runs four persistent workers using the real bridge, with
operational evidence already recorded. Document the future immutable release
procedure, including workflow dispatch, draft assembly, repository-level
immutability and the rule that corrections receive a new tag.

### R5 - Safe activation

Do not enable repository immutable releases until the corrected workflow is
committed and pushed to the default branch. Then enable it through the GitHub API
and verify `enabled=true`. Do not alter RC1-RC5.

## TDD

### RED

First update `tests/unit/test_release_hospital_deploy.py` to require:

- `workflow_dispatch` inputs instead of `release.published`;
- draft creation with the Compose asset before image publication;
- repository immutability preflight;
- exact-image-tag collision refusal;
- draft publication followed by immutable-state verification;
- absence of `--clobber` and post-publication asset upload.

Run the focused test and record failures against the current workflow.

### GREEN

Implement only the minimum workflow and documentation/artifact updates needed to
satisfy the tests and requirements.

### REFACTOR

Keep shell steps explicit and operator-readable. Do not create another workflow,
release service, deployment agent or automatic hospital update.

## Acceptance criteria

- [ ] RED fails for the old post-publication workflow.
- [ ] The official gate runs before any draft, image or release mutation.
- [ ] The publication job uses the commit resolved by validation.
- [ ] Repository immutable releases are required before publication.
- [ ] Existing exact GHCR image tags are rejected.
- [ ] Compose is attached to a draft before the image push and publication.
- [ ] Published release immutability is verified.
- [ ] Stable and prerelease moving channels remain separated.
- [ ] No `--clobber` or post-publication asset mutation remains.
- [ ] The persistent-worker runbook matches RC5 production reality.
- [ ] Existing RC1-RC5 artifacts remain untouched.
- [ ] Focused tests, official quality gate, strict OpenSpec and Markdown lint
  pass.
- [ ] Repository setting is enabled only after the corrected workflow reaches
  the default branch.

## Required validation

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh quality-gate
openspec validate add-release-image-hospital-deploy --strict
./scripts/markdown-lint.sh
```

Use focused host pytest only for rapid RED/GREEN diagnostics; official gate
claims must come from `scripts/test-in-container.sh`. Inspect the workflow with
`rg` and query `GET /repos/carlosapgomes/sirhosp/immutable-releases` after
activation.

## Required report

Create `/tmp/sirhosp-slice-RHID-S1-C8-report.md` with status, requirement matrix,
changed files, literal before/after fragments, RED/GREEN evidence, validation
commands and results, immutable-setting API evidence, confirmation that RC1-RC5
were untouched, risks and the next release procedure. Do not include tokens,
credentials, patient data or rendered production environment values.

## Stop rule

If draft-first publication cannot be proven, any gate fails, another tracked file
is needed, or the corrected workflow cannot be pushed before repository
activation, report the slice as incomplete and stop. Update task checkboxes only
after evidence exists. Commit and push the slice, enable repository immutable
releases, verify the setting, create the report and stop without publishing a
new release.
