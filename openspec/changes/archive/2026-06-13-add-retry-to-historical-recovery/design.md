# Add Retry to Historical Recovery Design

## Context

`recover_historical_data` currently executes a deterministic batch of
per-date/per-extractor steps, continues after failures by default, and exits
non-zero if any step fails. Manual testing over 27 days showed two transient
`discharges` failures with `source_unavailable` while the remaining 106 steps
succeeded.

The desired behavior is to retry only the failed steps after the initial batch
has completed. This creates a natural delay before retrying and avoids delaying
or repeating steps that already succeeded.

## Goals / Non-Goals

**Goals:**

- Retry only failed steps at the end of each batch attempt.
- Default to at most 3 retry rounds after the initial attempt.
- Keep retries deterministic and operator-visible.
- Keep retry state in memory and within a single command execution.
- Preserve existing dry-run, fail-fast, and safe error-message behavior.

**Non-Goals:**

- Do not add persistent recovery jobs or recovery-attempt tables.
- Do not add Celery, Redis, queues, or new background infrastructure.
- Do not change extractor service internals unless tests reveal a narrow bug.
- Do not retry successful steps.
- Do not retry dry-run steps.

## Decisions

### Decision: Retry after the full batch, not immediately

The orchestrator SHOULD finish the initially planned batch before retrying any
failed steps. Each retry round then executes only the failures from the previous
round, preserving date/extractor order. This gives transient source failures a
natural delay while other dates continue processing.

Alternative considered: immediate retry after each failed step. This is rejected
because it provides less delay and can block unrelated extractors.

### Decision: Use max retry rounds, default 3

The command SHOULD expose `--max-retries`, defaulting to 3. A value of `0` means
no retries and preserves the current behavior for operators who need it.

Alternative considered: hard-code 3 retries. A CLI option is more testable and
lets operators reduce retries during diagnostics.

### Decision: Keep retry accounting explicit but in memory

`RecoveryStepResult` SHOULD include attempt metadata, or `RecoveryRunResult`
SHOULD otherwise expose enough information for the command to print retry
attempts and final counts. No database model is needed in this change.

Alternative considered: add persistent retry attempts. This is out of scope and
was explicitly excluded from the current recovery command sequence.

### Decision: Preserve fail-fast semantics

With `--fail-fast`, the command SHOULD stop on the first failed step and not run
retry rounds. Fail-fast is a diagnostic mode intended to stop early.

Alternative considered: retry before stopping. This would make fail-fast less
predictable and harder to diagnose.

## Risks / Trade-offs

- Retrying all failure categories can waste time for permanent failures.
  Mitigation: keep maximum retries bounded and consider category-specific retry
  in a future change if needed.
- Operator output can become noisy. Mitigation: print compact retry round
  headers and per-step outcomes.
- In-memory retry state is lost if the command process exits. Mitigation:
  persistent retry jobs remain a future, explicitly separate change.
