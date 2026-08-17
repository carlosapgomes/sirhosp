# Tasks: Versioned sector capacity and occupancy history

## 1. Slice SCOH-S1 - Publish the versioned capacity catalog

- [x] 1.1 Read `slice-prompts/SLICE-SCOH-S1.md` completely and record the
  required baseline before editing.
- [x] 1.2 Add failing tests for complete-catalog validation, future-date
  enforcement, dry-run, atomic activation and idempotency.
- [x] 1.3 Add the minimal catalog models, constraints and additive migration.
- [x] 1.4 Add the initial synthetic JSON catalog with 42 groups, 47 codes,
  known capacity 658 and calculable capacity 626.
- [x] 1.5 Implement the controlled activation service and management command
  without editable Django Admin or periodic spreadsheet import.
- [x] 1.6 Prove RED, GREEN and REFACTOR, run inspection checks and all official
  gates required by the slice prompt.
- [x] 1.7 Create `/tmp/sirhosp-slice-SCOH-S1-report.md` with complete evidence
  and verifier handoff.
- [x] 1.8 Apply corrections C1-C7 from
  `slice-prompts/SLICE-SCOH-S1-R1.md` and pass independent verification.
- [x] 1.9 Restore the compatible Markdown policy (MD013/MD041 false), zero the
  global Markdown gate, version this change with `git add -f` and finalize.

## 2. Slice SCOH-S2 - Materialize one census occupancy measurement

- [x] 2.1 Read `slice-prompts/SLICE-SCOH-S2.md` completely and verify SCOH-S1
  is complete before editing.
- [x] 2.2 Add failing tests for post-activation, pre-activation, idempotent and
  privacy-safe measurement materialization.
- [x] 2.3 Add the minimal immutable measurement models, constraints and additive
  migration.
- [x] 2.4 Implement `occupancy-v1` for simple/shared groups, raw legacy
  occupants, deterministic rounding, source-name mismatch and aggregate status
  snapshots.
- [x] 2.5 Implement pending, unrated and unmapped states plus hospital totals
  and dual coverage, without approximating Obstetrícia 3A.
- [x] 2.6 Add the explicit run-scoped recovery command without scan or backfill.
- [x] 2.7 Prove RED, GREEN and REFACTOR, run inspection checks and all official
  gates required by the slice prompt.
- [x] 2.8 Create `/tmp/sirhosp-slice-SCOH-S2-report.md` with complete evidence
  and verifier handoff.

## 3. Slice SCOH-S3 - Integrate accepted censuses and daily summaries

- [x] 3.1 Read `slice-prompts/SLICE-SCOH-S3.md` completely and verify both
  SCOH-S2 and dependency GCEC-S2 are complete before editing.
- [x] 3.2 Add failing tests for daily creation/update, equal-weight arithmetic,
  delayed measurements, non-calculable groups and idempotent reruns.
- [x] 3.3 Add minimal daily parent/group summary models, constraints and an
  additive migration.
- [x] 3.4 Refresh the local-date summary transactionally after a new
  measurement, without scheduler or retroactive rebuild command.
- [x] 3.5 Add failing integration tests proving the completeness gate precedes
  materialization, zero-occupied runs are measured and capacity gaps do not
  block clinical processing.
- [x] 3.6 Integrate materialization into `process_census_snapshot` before
  clinical side effects while preserving pre-activation and missing-provenance
  behavior.
- [x] 3.7 Prove RED, GREEN and REFACTOR, run inspection checks and all official
  gates required by the slice prompt.
- [x] 3.8 Create `/tmp/sirhosp-slice-SCOH-S3-report.md` with complete evidence
  and verifier handoff.

## 4. Slice SCOH-S4 - Enrich `/beds` with official occupancy

- [x] 4.1 Read `slice-prompts/SLICE-SCOH-S4.md` completely and verify SCOH-S3
  is complete before editing.
- [x] 4.2 Add failing view/template tests for exact-measurement selection,
  pending fallback, grouped rows, dual coverage and existing authentication.
- [x] 4.3 Present capacity, registered legacy occupancy, exceeded-by and
  accessible over-capacity warnings without business calculation in the view.
- [x] 4.4 Preserve expandable source-sector, bed-status and authorized patient
  details, including shared groups and unmapped sectors.
- [x] 4.5 Show Obstetrícia 3A, unrated sectors and hospital known/calculable
  totals without approximate percentages.
- [x] 4.6 Prove RED, GREEN and REFACTOR, run inspection checks and all official
  gates required by the slice prompt.
- [x] 4.7 Create `/tmp/sirhosp-slice-SCOH-S4-report.md` with complete evidence
  and verifier handoff.

## 5. Final verification and governance

- [ ] 5.1 Create or confirm the required ADR for temporal catalog and immutable
  occupancy materialization before archiving this CRITICAL/HIGH-ARCH change.
- [ ] 5.2 Run `openspec validate add-versioned-sector-capacity-occupancy-history
  --type change --strict`.
- [ ] 5.3 Run `./scripts/test-in-container.sh quality-gate`.
- [ ] 5.4 Run `./scripts/test-in-container.sh integration`.
- [ ] 5.5 Run `./scripts/markdown-lint.sh` with zero errors.
- [ ] 5.6 Verify no real patient data, credentials, PDFs or production dumps
  appear in the diff or temporary reports.
- [ ] 5.7 Create `/tmp/sirhosp-slice-SCOH-FINAL-report.md` with command output,
  rollback readiness, unresolved risks and verifier handoff.
- [ ] 5.8 Stop after final review; do not activate a catalog in production and
  do not archive the change without explicit operator approval.
