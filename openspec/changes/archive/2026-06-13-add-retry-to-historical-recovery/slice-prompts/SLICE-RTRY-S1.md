# SLICE RTRY-S1 - End-of-batch retry for historical recovery

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `README.md`
- `openspec/changes/add-retry-to-historical-recovery/proposal.md`
- `openspec/changes/add-retry-to-historical-recovery/design.md`
- `openspec/changes/add-retry-to-historical-recovery/specs/historical-recovery-command/spec.md`
- `openspec/changes/add-retry-to-historical-recovery/tasks.md`
- `openspec/changes/add-historical-recovery-command/recovery-handoff.md`
- `openspec/changes/add-historical-recovery-command/specs/historical-recovery-command/spec.md`

Implement only this slice. Do not archive this change or any recovery/extraction
change.

## Branch protocol

Start from a clean working tree. If `README.md` or any unrelated file is
modified, stop and ask for that change to be committed or stashed first.

Work on a dedicated branch:

```bash
git switch -c change/add-retry-to-historical-recovery
```

If the branch already exists, use:

```bash
git switch change/add-retry-to-historical-recovery
```

Do not implement this slice directly on `master`.

## Objective

Add automatic retry rounds to `recover_historical_data` so that failed
per-date/per-extractor steps are retried only after the initial batch finishes.
Default retry limit: 3 retry rounds after the initial attempt.

## Suggested files

Prefer no more than 6 changed files.

Likely files:

- `apps/ingestion/historical_recovery.py`
- `apps/ingestion/management/commands/recover_historical_data.py`
- `tests/unit/test_historical_recovery_failures.py`
- `tests/unit/test_historical_recovery_orchestration.py`
- `tests/unit/test_recover_historical_data_command.py`
- `README.md` if operator docs need to mention retry behavior

## Required behavior

Implement and test all of the following:

1. Default `max_retries` is 3 retry rounds after the initial batch.
2. Retry rounds run only after the current batch/round completes.
3. Each retry round includes only failed date/extractor steps from the previous
   round.
4. Successful steps are not retried.
5. If a failed step succeeds on retry, final aggregation treats it as successful.
6. If a step still fails after retry exhaustion, final aggregation remains
   failed and the command exits non-zero.
7. `--max-retries 0` disables retries and preserves current behavior.
8. Negative retry values fail validation before extraction.
9. `--dry-run` does not call services and does not run retry rounds.
10. `--fail-fast` stops on the first failure and does not run retry rounds.
11. Unexpected exceptions remain credential-safe and can be retried according to
    retry settings.
12. Operator output identifies retry rounds compactly.

## Design guidance

Prefer implementing retry in the orchestration layer, not only in the management
command, so tests can exercise deterministic service-call behavior directly.
Keep retry state in memory within `RecoveryRunResult`/step metadata or a small
internal helper. Do not add persistent models or migrations.

Use stable step identity based on date and extractor name. Retry order should
remain deterministic: date order, then configured extractor order.

Avoid reusing failed `RecoveryStepResult` objects as the final outcome if a
later retry succeeds. The final summary should reflect the final state of each
planned date/extractor step while still making retry attempts visible enough for
operator output/tests.

## Guardrails

- Do not add recovery job models, retry-attempt tables, migrations, Celery,
  Redis, queues, or new background infrastructure.
- Do not retry dry-run steps.
- Do not retry successful steps.
- Do not print raw exception text or credentials.
- Do not touch `apps/discharges/services.py`.
- Do not modify Playwright automation scripts.
- Do not change extractor service internals unless a focused test exposes a
  narrow bug and you document the reason.
- Use synthetic/anonymized test data only.

## Validation

Run focused tests first, then official gates:

```bash
uv run ruff check \
  apps/ingestion/historical_recovery.py \
  apps/ingestion/management/commands/recover_historical_data.py \
  tests/unit/test_historical_recovery_failures.py \
  tests/unit/test_historical_recovery_orchestration.py \
  tests/unit/test_recover_historical_data_command.py
uv run pytest -q \
  tests/unit/test_historical_recovery_failures.py \
  tests/unit/test_historical_recovery_orchestration.py \
  tests/unit/test_recover_historical_data_command.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/add-retry-to-historical-recovery/proposal.md \
  openspec/changes/add-retry-to-historical-recovery/design.md \
  openspec/changes/add-retry-to-historical-recovery/tasks.md
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/add-retry-to-historical-recovery/specs/historical-recovery-command/spec.md
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/add-retry-to-historical-recovery/slice-prompts/SLICE-RTRY-S1.md
openspec validate add-retry-to-historical-recovery --type change --strict
```

Host-only commands are diagnostic only; official evidence comes from the
container scripts above.

## Required report

Create `/tmp/sirhosp-slice-RTRY-S1-report.md` with:

- summary of the retry implementation;
- baseline behavior and why retry is needed;
- files changed;
- before/after snippets for production files;
- commands executed and results;
- confirmation that no persistent retry state/infrastructure was added;
- confirmation that no historical extractor internals were changed, unless
  explicitly justified;
- risks, pending work, and next suggested step.

Commit the implementation after validation with a clear message, then stop.
