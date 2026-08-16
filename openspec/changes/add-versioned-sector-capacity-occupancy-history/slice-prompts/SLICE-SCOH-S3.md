# SLICE-SCOH-S3: Integrate accepted censuses and daily summaries

## Handoff for a zero-context implementer

You are implementing the third of four vertical slices in SIRHOSP. This slice
turns explicit occupancy materialization into the normal accepted-census flow
and persists a deterministic daily summary. It must preserve clinical census
processing and must never run before the completeness defense.

Read completely before editing:

1. `AGENTS.md` and `PROJECT_CONTEXT.md`;
2. every artifact in
   `openspec/changes/add-versioned-sector-capacity-occupancy-history/`;
3. `slice-prompts/SLICE-SCOH-S1.md` and `SLICE-SCOH-S2.md`;
4. reports `/tmp/sirhosp-slice-SCOH-S1-report.md` and
   `/tmp/sirhosp-slice-SCOH-S2-report.md` when available;
5. all artifacts, code and tests of the archived and completed GCEC change
   `openspec/changes/archive/2026-08-16-guard-census-extraction-completeness/`;
6. this file;
7. `apps/census/models.py`, `apps/census/occupancy.py` and
   `apps/census/services.py`;
8. `apps/census/management/commands/process_census_snapshot.py`;
9. `tests/unit/test_occupancy_measurement.py`,
   `tests/unit/test_process_census_snapshot.py` and related batch tests.

Hard prerequisite checks before baseline:

- SCOH-S1 tasks 1.1-1.9 are checked;
- SCOH-S2 tasks 2.1-2.8 are checked;
- GCEC-S2 tasks 2.1-2.6 in
  `openspec/changes/archive/2026-08-16-guard-census-extraction-completeness/tasks.md`
  are checked (GCEC change already archived and complete);
- processing code rejects snapshots with fewer than 40 distinct sectors before
  batch creation.

If any prerequisite is absent, stop as `INCOMPLETE/BLOCKED`. Do not implement
or repair GCEC-S2 inside this slice.

## Mandatory protocol for DeepSeek4-Flash

Failure of any item makes the slice **INCOMPLETE**. Do not update tasks, commit
or push.

1. Record `BASE_REF=$(git rev-parse HEAD)` and `git status --short`.
2. Preserve unrelated edits; stop on unexplained changes in expected files.
3. Put a `Requirement -> file(s) -> test(s)` matrix in the report before code.
4. Run official baseline `./scripts/test-in-container.sh unit` before editing
   and record exit code plus passed/failed/error summary. Any baseline failure
   blocks work.
5. Add daily tests first and prove a real assertion RED. Implement daily GREEN.
6. Then add processing integration tests first and prove a second real RED
   before editing `services.py`.
7. Implement only minimal integration after the completeness guard and before
   clinical effects. Do not modify scraper, orchestrator or UI.
8. Refactor only after both groups are GREEN; enforce clean code, DRY and YAGNI.
9. Run every inspection and final official gate. Final unit must exit 0, have no
   failures/errors and satisfy `passed_final >= passed_baseline`.
10. Mark only tasks 3.1-3.8, create the report, commit, push and stop. If commit
    or push fails, report incomplete.

## Objective

Every complete post-activation census selected for processing creates or reuses
one immutable occupancy measurement before clinical batch side effects. A newly
created measurement transactionally updates one local-day hospital summary and
its group summaries using equal-weight arithmetic.

## Current technical context

After SCOH-S2:

- catalog selection is future-dated and immutable;
- `materialize_occupancy_measurement(run_id)` is explicit and idempotent;
- measurement uses `occupancy-v1`, raw occupied legacy records, dual coverage
  and non-calculable states;
- no daily model or automatic call exists.

Current processing has two paths:

- explicit `run_id`, used by adaptive orchestration;
- legacy latest `captured_at` without a run argument.

GCEC-S2 must validate either selected queryset before creating
`CensusExecutionBatch` or queueing patients. The occupancy call belongs after
that guard but before the early return for zero occupied patients and before
batch creation.

Project timezone is `America/Bahia`. Daily summary date comes from measurement
capture time converted to project local date, not processing time.

## Functional scope

### R1. Daily summary schema

Add minimal additive models:

- `DailyOccupancySummary`, unique by local date;
- `DailyGroupOccupancySummary`, unique by daily summary and stable group key.

Use `PROTECT` for catalog references and copy resolved algorithm, names,
policies and capacities needed for historical interpretation. Add constraints
for nonnegative counts, ordered capture bounds and valid nullable statistics.
Do not add a scheduler model.

### R2. Deterministic local-day aggregation

When and only when a new measurement is inserted:

- select all immutable measurements for its `local_date`;
- atomically upsert one daily parent and complete child set;
- record measurement count, first/last capture, mean/min/max occupied,
  mean/min/max percentage and maximum exceeded-by;
- preserve known/calculable capacities and coverage evidence;
- give each census one equal observation;
- calculate means from exact numerator/capacity values and round only final
  decimals with `ROUND_HALF_UP`;
- perform no time weighting, interpolation or projection.

A delayed first-time measurement updates its original capture date. A repeated
existing measurement does not rewrite the summary.

### R3. Daily non-calculable groups and coverage

For `linked_slots_pending`, `unrated` and `unmapped` children:

- persist measurement count and mean/min/max raw occupied values;
- keep percentage summaries null.

The parent summary records minimum and maximum observed, capacity-covered and
calculable sector counts across the day so changing coverage is auditable.
A date with zero measurements receives no fabricated row.

### R4. Explicit-run processing integration

In `process_census_snapshot(run_id=...)`:

- select snapshots;
- run the GCEC-S2 completeness guard;
- call occupancy materialization for the exact run;
- only then evaluate occupied patients, create batch or queue work;
- expose aggregate-safe materialization status/id in the returned result if
  needed for tests and operations.

A structurally invalid catalog or database failure must propagate before any
clinical batch or queued patient run. `unmapped`, `unrated`, pending 3A and name
mismatch are valid measurement states and must not block clinical processing.

### R5. Zero-occupied and pre-activation behavior

A complete post-activation run with zero occupied patients still gets a
measurement and daily summary, while current behavior creates no clinical
batch.

A complete pre-activation run returns no measurement but continues existing
clinical processing unchanged.

### R6. Incomplete snapshots are never measured

Tests must prove a 39-sector explicit or legacy snapshot is rejected by the
existing GCEC guard before occupancy service invocation, daily summary, batch or
queue side effects.

Do not duplicate the threshold logic. Reuse the GCEC helper/guard.

### R7. Legacy latest-snapshot provenance

For the no-`run_id` path:

- materialize only if all latest rows resolve to exactly one non-null census
  run;
- use that run as idempotency key;
- if provenance is absent or ambiguous, return/report
  `missing_provenance`, skip occupancy history and preserve existing clinical
  processing.

Never synthesize a run key from `captured_at`.

### R8. No hidden backfill or extra runtime

Do not create a daily timer, systemd unit, signal, Celery task, scanning command
or historical rebuild. Daily updates happen synchronously only after a newly
materialized measurement in the existing processing flow or explicit command.

## Expected files and hard scope limit

Expected implementation files, maximum **6** excluding `tasks.md` and report:

```text
apps/census/models.py
apps/census/migrations/00xx_daily_occupancy_summary.py
apps/census/occupancy.py
apps/census/services.py
tests/unit/test_occupancy_measurement.py
tests/unit/test_process_census_snapshot.py
```

Use an existing equivalent process test file if project organization requires,
but do not add a third test file. If the management command needs no behavior
change, do not edit it. More than six implementation files requires stopping
for planner approval.

Forbidden in this slice:

- editing the GCEC change or implementing its missing tasks;
- changes to extraction/Playwright or adaptive orchestrator;
- view, template, navigation or CSS changes;
- a background scheduler, signal or new management command;
- recalculation of existing measurement values;
- retroactive rebuild command;
- real patient fixtures or production access.

## Mandatory TDD cycle

### RED phase A: daily summary

Write tests first for:

1. first measurement creates one parent and expected group summaries;
2. second same-day measurement updates instead of duplicates;
3. arithmetic mean, min, max, first, last and exceeded-by are exact;
4. unequal intervals still have equal weights;
5. decimal final rounding uses `ROUND_HALF_UP`;
6. delayed measurement updates its original local date;
7. repeated existing measurement does not rewrite/recount summary;
8. pending/unrated/unmapped groups have raw statistics and null percentages;
9. changing intraday coverage preserves minimum/maximum evidence;
10. day without measurement has no summary;
11. later catalog does not rebuild prior summary.

Capture an assertion failure caused by absent daily behavior.

### GREEN phase A

Add minimal models/migration and transactional refresh logic. Make the
measurement service indicate whether a row was newly created so idempotent calls
skip summary writes.

### RED phase B: processing integration

Before editing `services.py`, add tests proving failure for missing integration:

1. complete explicit post-activation run invokes materialization before batch;
2. materialization failure leaves zero clinical batches and queue runs;
3. complete zero-occupied run still gets measurement/summary and no batch;
4. pre-activation run has no measurement and preserves clinical behavior;
5. unknown/unrated/pending states do not block clinical processing;
6. explicit 39-sector run never invokes materialization;
7. legacy 39-sector path never invokes materialization;
8. legacy latest set with one run materializes by that run;
9. missing/ambiguous provenance skips history and preserves legacy processing.

Capture a second assertion RED for absent integration.

### GREEN phase B

Insert one narrow call at the validated processing boundary. Avoid moving,
rewriting or reformatting unrelated patient-processing code.

### REFACTOR

After all tests pass:

- keep aggregation in `occupancy.py`, not `services.py`;
- reuse pure decimal/statistics helpers from SCOH-S2;
- avoid duplicated queryset selection and GCEC threshold logic;
- keep transaction scopes explicit;
- use clear status result types rather than broad exception swallowing;
- apply clean code, DRY and YAGNI;
- rerun affected tests after every refactor.

## Mandatory inspection checks

Run and interpret:

```bash
rg -n \
  "class DailyOccupancySummary|class DailyGroupOccupancySummary" \
  apps/census/models.py
rg -n \
  "Avg|Min|Max|ROUND_HALF_UP|local_date|transaction\.atomic" \
  apps/census/occupancy.py
rg -n \
  "validate_census_completeness|materialize_occupancy" \
  apps/census/services.py
rg -n \
  "CensusExecutionBatch\.objects\.create|queue_admissions_only_run" \
  apps/census/services.py
rg -n \
  "materialize_occupancy" \
  apps/census/management/commands/extract_census.py \
  apps/census/orchestration.py automation 2>/dev/null
rg -n \
  "Celery|celery|Redis|redis|post_save|receiver" \
  apps/census/occupancy.py apps/census/services.py
rg -n \
  "rebuild|backfill|scan-all|all-runs" \
  apps/census apps/ingestion/management/commands
rg -n 'markdownlint-''disable' \
  openspec/changes/add-versioned-sector-capacity-occupancy-history
uv run python manage.py makemigrations --check --dry-run

git diff --check
git status --short
```

The report must inspect line ordering in `services.py`, not merely list matches:
completeness validation must precede materialization, and materialization must
precede batch creation and queue calls. Extraction/orchestration search should
show no new integration. Celery/signal and rebuild searches should show no new
implementation attributable to this slice.

## Binary success criteria

- [ ] All prerequisites, including GCEC-S2, are verified complete.
- [ ] R1-R8 each have passing test or inspection evidence.
- [ ] Two valid RED stages are captured before their production edits.
- [ ] Daily parent/children are deterministic, idempotent and local-date based.
- [ ] Equal-weight arithmetic and final-only rounding are exact.
- [ ] Non-calculable daily groups preserve raw values and null rates.
- [ ] Complete zero-occupied census is measured before early return.
- [ ] Incomplete snapshots never invoke occupancy materialization.
- [ ] Structural failure occurs before any clinical side effect.
- [ ] Capacity-data gaps remain nonblocking.
- [ ] Missing provenance never creates synthetic history.
- [ ] No scheduler, backfill, UI or extraction change exists.
- [ ] File limit, inspections and all official gates pass.
- [ ] Final pytest has zero failures/errors and no passed-count regression.
- [ ] Report and verifier handoff are complete.

## Self-evaluation gates

Answer `YES` or `NO` with evidence:

1. Were both daily and integration RED failures captured before corresponding
   production edits?
2. Does any incomplete path call materialization before returning rejection?
3. Can a zero-occupied complete run exit before measurement?
4. Can a capacity-data gap suppress patient processing?
5. Can an idempotent rerun alter a daily summary?
6. Is the local date derived from capture time in `America/Bahia`?
7. Are means equal-weight and free of interval interpolation?
8. Can no-run or multi-run legacy data create a measurement?
9. Did you avoid modifying GCEC, scraper, orchestrator, UI and deployment?
10. Are all errors/logs aggregate-safe?
11. Did final pytest exit 0 with no failures/errors and enough passed tests?
12. Is the implementation within six files and free of migration drift?

Any `NO` means incomplete.

## Automatic INCOMPLETE conditions

The slice is incomplete if any occurs:

- SCOH-S1, SCOH-S2 or GCEC-S2 prerequisite is not complete;
- baseline or either RED stage is missing/invalid;
- any final gate fails or final passed count regresses;
- daily summary uses processing date, time-weighting or rounded intermediate
  values;
- idempotent rerun rewrites summary;
- a no-measurement day gets fabricated zeros;
- incomplete census invokes occupancy code;
- zero-occupied complete census is not measured;
- materialization occurs after batch creation or queue calls;
- structural failure is swallowed after clinical side effects;
- missing provenance is replaced by `captured_at` identity;
- GCEC, scraper, orchestrator, UI, deployment or unrelated app is edited;
- scheduler, signal, scanning or backfill behavior is introduced;
- more than six implementation files are changed without approval;
- report/evidence/handoff is incomplete or contains patient data;
- tasks are marked before gates;
- commit or push is missing after technical completion.

## Official validation commands

Run all:

```bash
./scripts/test-in-container.sh quality-gate
./scripts/test-in-container.sh integration
./scripts/markdown-lint.sh
openspec validate \
  add-versioned-sector-capacity-occupancy-history \
  --type change --strict
```

The integration gate is mandatory here because processing and persistence
boundaries changed.

## Mandatory temporary report

Create `/tmp/sirhosp-slice-SCOH-S3-report.md` with:

- status, `BASE_REF`, git status and prerequisite evidence;
- requirement/file/test matrix;
- baseline summary;
- RED A and RED B commands, failing assertions and expected reasons;
- GREEN evidence after each stage;
- before/after snippets for every changed implementation file;
- daily formulas and synthetic examples;
- proof of service call ordering before clinical effects;
- inspections with output and interpretation;
- baseline versus final passed/failed/error table;
- all official commands and exit codes;
- acceptance checklist and gate answers;
- file-limit justification, risks and deferred UI;
- exact rerun commands;
- final `Handoff para verificador` with:
  - changed files, commit hash and push result;
  - R1-R8 checklist;
  - exact third-party reruns;
  - mandatory manual inspection of call ordering and transaction boundary;
  - known limitations;
  - next slice `SCOH-S4`.

The report must pass Markdown lint and contain no real patient data.

## Ready-to-run implementer prompt

```text
Read AGENTS.md, PROJECT_CONTEXT.md, every artifact under
openspec/changes/add-versioned-sector-capacity-occupancy-history and the
archived GCEC change
openspec/changes/archive/2026-08-16-guard-census-extraction-completeness.
Read SLICE-SCOH-S3.md completely.
Verify SCOH-S1, SCOH-S2 and GCEC-S2 are complete. If not, stop BLOCKED.
Implement ONLY SCOH-S3.

Follow the DeepSeek4-Flash protocol: BASE_REF, official unit baseline,
requirement matrix, separate real RED evidence for daily behavior and processing
integration, minimal GREEN, clean-code/DRY/YAGNI refactor, every rg inspection,
all official gates including integration, and baseline-vs-final comparison.

Deliver only deterministic daily summaries and occupancy integration after the
completeness guard and before clinical side effects. Touch at most six
implementation files. Do not edit GCEC, extraction, scraper, orchestrator,
/beds, deployment or future slices. Do not add scheduler, signal or backfill.
Use synthetic data only.

If any prerequisite, test, inspection, gate, ordering rule, file limit, commit
or push fails, report INCOMPLETE and do not mark tasks. Otherwise mark only
tasks 3.1-3.8, create /tmp/sirhosp-slice-SCOH-S3-report.md, commit, push, reply
with REPORT_PATH=/tmp/sirhosp-slice-SCOH-S3-report.md and STOP for planner
review.
```
