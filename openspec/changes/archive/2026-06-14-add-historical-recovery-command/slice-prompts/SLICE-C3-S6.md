# SLICE C3-S6 - Final validation and archive readiness

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/add-historical-recovery-command/proposal.md`
- `openspec/changes/add-historical-recovery-command/design.md`
- `openspec/changes/add-historical-recovery-command/specs/historical-recovery-command/spec.md`
- `openspec/changes/add-historical-recovery-command/specs/ingestion-run-observability/spec.md`
- `openspec/changes/add-historical-recovery-command/tasks.md`
- `openspec/changes/extract-census-discharge-services/change-3-handoff.md`

Implement only Slice C3-S6. Do not start the next slice.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/add-historical-recovery-command
```

If the branch does not exist yet, stop and ask for the previous slice handoff.
Do not implement this slice directly on `main`.

## Objective

Perform final validation for Change 3 and document archive readiness for the
three-change refactor sequence.

## Suggested scope

Before coding, confirm Slice C3-S5 was committed. If not, stop and ask for the
S5 commit/handoff. Do not mix uncommitted S5 changes into this final validation
slice.

Do not add production behavior unless a validation failure requires a tiny fix.
Update checkboxes and document known unrelated failures exactly.

Carry forward these C3-S5 verifier notes:

- S1-S4 checkboxes in `tasks.md` may still be unchecked even though their
  slices are complete and committed. In this slice, mark all completed S1-S6
  tasks accurately.
- Existing quality-gate failures may remain unrelated to this change. Capture
  exact command output and classify them only with evidence.
- Do not archive Change 1, Change 2, or Change 3 here. Only document readiness
  for later archive.
- If touching Python for a tiny cleanup, consider removing unnecessary
  `# type: ignore[arg-type]` comments in `recover_historical_data.py`, but do
  not create a broad cleanup/refactor in this final validation slice.

## Suggested files

Prefer no more than 5 changed files unless tests require a small helper.

Likely files:

- `openspec/changes/add-historical-recovery-command/tasks.md`
- optional `openspec/changes/add-historical-recovery-command/recovery-handoff.md`
- optional focused tests only if final validation exposes a small gap
- optional `apps/ingestion/management/commands/recover_historical_data.py` only
  for tiny cleanup tied to validation findings

If Python files are touched, run focused ruff/pytest and document why the change
belongs in final validation.

## Required behavior

Complete all of the following:

1. Confirm S1-S5 commits exist and no S5 changes are left uncommitted.
2. Mark every completed task in `tasks.md` for S1 through S6.
3. Run the quality-gate commands listed below and record exact outcomes.
4. Re-run OpenSpec validation for `add-historical-recovery-command`.
5. Run markdown lint for changed `.md` files. If full-project markdown lint is
   noisy due to pre-existing files, also run focused markdownlint on the changed
   OpenSpec files and document both facts.
6. Confirm no recovery job model, attempt model, migration, Celery, Redis, or
   new persistent orchestration state was added.
7. Confirm existing extractor commands remain supported wrappers.
8. Confirm `apps/discharges/services.py` was not modified.
9. Confirm Changes 1, 2, and 3 are ready for later archive, but do not archive
   any change in this slice.
10. Document all known caveats and whether they are pre-existing or introduced
    by this change.

Known caveats to verify and document if still present:

- stale inpatient unit test failure in
  `tests/unit/test_report_suspected_stale_inpatients_command.py`;
- pre-existing lint errors in `apps/services_portal/urls.py`,
  `tests/integration/test_services_portal_ingestion_metrics_failures_tab.py`,
  and `tests/unit/test_report_suspected_stale_inpatients_command.py`;
- pre-existing mypy duplicate module issue around
  `tests/unit/test_services_portal_sectors.py`.

## Constraints

- Do not modify `apps/discharges/services.py`.
- Do not modify Playwright automation scripts.
- Do not add Celery, Redis, queues, or new orchestration infrastructure.
- Do not add persistent recovery job models or migrations.
- Do not use `call_command` or subprocessed Django commands to run extractors.
- Do not delete existing extractor management commands.
- Do not archive OpenSpec changes in this slice.
- Use synthetic/anonymized test data only.
- Do not hide or suppress validation failures; document exact evidence.
- Do not use `<!-- markdownlint-disable -->`.

## Validation

Run at least:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
openspec validate add-historical-recovery-command --type change --strict
```

If any command fails, do not proceed as if it passed. Record:

- exact command;
- failing file/test/rule;
- whether evidence shows it is pre-existing;
- whether it blocks archive readiness.

If `.md` files are changed, also run focused markdownlint on those files, for
example:

```bash
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/add-historical-recovery-command/tasks.md \
  openspec/changes/add-historical-recovery-command/recovery-handoff.md
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. Host-only `uv run pytest ...` is
acceptable only as diagnostic evidence, not as the official gate.

## Required report

Create `/tmp/sirhosp-slice-C3-S6-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for changed production files;
- commands executed and results;
- exact known validation caveats and ownership;
- readiness statement for later archive of Changes 1, 2, and 3;
- explicit note that no archive was performed in this slice;
- risks, pending work, and next suggested step.
