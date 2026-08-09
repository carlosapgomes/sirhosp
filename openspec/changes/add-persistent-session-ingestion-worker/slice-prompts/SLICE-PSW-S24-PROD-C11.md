# Slice Prompt — PSW-S24-PROD-C11 Authorized Stale Disposal

## Handoff

Start from zero context. Read `AGENTS.md`, the active OpenSpec change, the
existing stale-recovery service and command, their focused tests, PSW-S24
production evidence, and this prompt.

## Operator Decision

The operator explicitly authorizes abandoned `running` ingestion runs to be
discarded. The system is stopped and unused. Losing incomplete extraction
series is acceptable because source data can be scraped again.

## Goal

Remove stale `running` rows as a cutover blocker without deleting audit rows,
requeueing work, touching queued work, or starting any worker. Use the existing
terminal recovery path when it already satisfies this contract.

## Guardrails

1. Confirm no ingestion worker is running.
2. Run the existing command in dry-run mode first.
3. Classify candidates with the existing intent age limits and heartbeat grace.
4. Set the apply circuit breaker to the exact observed candidate count.
5. Apply once; stale rows become terminal `failed`, `timed_out=True`, with no
   retry and the existing sanitized reason.
6. Re-run dry-run and aggregate status checks. Require zero remaining stale
   candidates and zero `running` rows.
7. Do not mutate `queued`, `succeeded`, or already `failed` rows.
8. Do not print patient data, payloads, URLs, credentials, or clinical text.
9. Keep the continuous persistent worker disabled.

## Versioned Scope

No production implementation change is expected because the existing
`recover_stale_ingestion_runs` service and command already provide the required
transactional, terminal, bounded behavior. At most two versioned documentation
files may change:

1. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`; and
2. this prompt.

If the existing command fails any guardrail, stop before production mutation
and open a separate TDD corrective slice.

## Verification

Run the focused stale-recovery tests, official Django check and unit gate,
strict OpenSpec validation, Markdown lint, and diff checks. Create
`/tmp/sirhosp-slice-PSW-S24-PROD-C11-report.md` with sanitized before/after
counts, commands, results, risks, and the next blocker. Stop after this slice.
