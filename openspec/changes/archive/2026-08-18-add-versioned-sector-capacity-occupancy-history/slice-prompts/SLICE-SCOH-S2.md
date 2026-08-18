# SLICE-SCOH-S2: Materialize one census occupancy measurement

## Handoff for a zero-context implementer

You are implementing the second of four vertical slices in SIRHOSP. SCOH-S1
must already provide a validated, future-dated catalog. This slice delivers an
operator-visible flow that materializes one immutable occupancy measurement for
one explicit census run. It does not integrate automatically with census
processing and does not create daily summaries or UI.

Read completely before editing:

1. `AGENTS.md` and `PROJECT_CONTEXT.md`;
2. all artifacts in
   `openspec/changes/add-versioned-sector-capacity-occupancy-history/`;
3. `slice-prompts/SLICE-SCOH-S1.md` and its report at
   `/tmp/sirhosp-slice-SCOH-S1-report.md` if available;
4. this file;
5. `apps/census/models.py`;
6. `apps/census/capacity_catalog.py`;
7. `apps/census/services.py` only to understand current snapshot selection;
8. `apps/census/management/commands/process_census_snapshot.py` as a command
   style reference;
9. tests added by SCOH-S1 and current census model tests.

Verify tasks 1.1 through 1.9 are checked and inspect their implementation. If
SCOH-S1 is incomplete or its contracts differ from the approved design, stop
and report a blocker instead of repairing it inside this slice.

## Mandatory protocol for DeepSeek4-Flash

If any protocol item fails, this slice is **INCOMPLETE**. Do not update tasks,
commit or push.

1. Record `BASE_REF=$(git rev-parse HEAD)` and initial `git status --short`.
2. Do not overwrite unrelated changes. Stop if an expected file has unexplained
   edits.
3. Write the report matrix `Requirement -> file(s) -> test(s)` before code.
4. Run `./scripts/test-in-container.sh unit` before editing. Record exit code,
   passed, failed and errors. Any baseline failure blocks the slice.
5. Write tests first. Run the official unit suite and prove at least one test
   fails because measurement behavior is missing. Import/setup failures are not
   valid RED.
6. Implement minimal GREEN for the explicit run-scoped command and domain
   service. Do not touch automatic processing, summaries, view or template.
7. Run every inspection check and explain expected and unexpected matches.
8. Run every final official gate. Final unit must exit 0 with zero
   failures/errors and `passed_final >= passed_baseline`.
9. Mark only tasks 2.1 through 2.8 after all evidence exists.
10. Create the required report, commit, push and stop. Failure to commit or push
    must be reported as `INCOMPLETE`, not silently ignored.

## Objective

Given an explicit complete census run and an applicable catalog, the operator
can materialize exactly one immutable `occupancy-v1` measurement containing all
group results, unknown states, totals and coverage. Repeating the command
returns the same measurement without recalculation.

## Current technical context

After SCOH-S1, the expected catalog domain has:

- one complete version selected by local capture date;
- `standard`, `linked_slots_pending` and `unrated` policies;
- 39 groups with capacity, of which 38 are calculable;
- 47 configured codes, with 44 capacity-covered and 43 calculable;
- known capacity 658 and calculable capacity 626;
- immutable activation by date/hash.

Relevant source data:

- `CensusSnapshot.ingestion_run` provides measurement provenance;
- `captured_at` determines local date and applicable catalog;
- `setor_codigo` is the mapping key;
- `setor` is the observed source name;
- `bed_status` contains occupied, empty, reserved, maintenance and isolation;
- patient name and record fields MUST NOT be copied to new history tables.

Only `BedStatus.OCCUPIED` enters a numerator. A patient suspected of stale
administrative status remains counted while the legacy census marks the row
occupied.

## Functional scope

### R1. Immutable measurement schema

Add minimal additive models for:

- `OccupancyMeasurement`, one-to-one with the census `IngestionRun`;
- `OccupancyGroupMeasurement`, children unique by measurement and stable group
  key.

Use `PROTECT` for run/catalog references, constraints for uniqueness and
nonnegative aggregate values, and indexes needed for run/date lookup. Historical
children must copy resolved group key, name, policy, capacity and calculation
status instead of depending solely on current catalog values.

### R2. Explicit run-scoped materialization

Implement a cohesive service and
`materialize_occupancy_measurement --run-id <id>`.

- accept only a census-extraction run with snapshots;
- require all selected rows to belong to that run;
- derive one captured timestamp/local date deterministically;
- return `pre_activation` with no row when no catalog applies;
- never scan other runs or offer all/history/backfill options;
- create parent and every child in one transaction;
- repeat the same run as a no-op returning the existing immutable row.

This command is recovery/inspection tooling, not a new scheduler.

### R3. Standard and shared calculations

For every `standard` group:

- aggregate status counts across all member codes;
- numerator is only occupied count;
- apply official capacity once;
- `percentage = occupied / capacity * 100`;
- `exceeded_by = max(occupied - capacity, 0)`;
- persist percentage to two decimals using `Decimal` and `ROUND_HALF_UP`;
- never cap at 100%.

Mandatory regressions:

- `719` plus `2156` use capacity 15 once;
- `20`, `1110`, `1112`, `1114`, `1116` use capacity 8 once;
- 54 occupied in `CO` produce 675.00% and exceeded-by 46;
- no stale-patient/evolution/admission query adjusts the numerator.

### R4. Non-calculable states

- `OBST-3A` stores capacity 32 and raw status counts but null numerator,
  percentage and exceeded-by with `linked_slots_pending` status.
- `unrated` groups store raw counts with null capacity and percentage.
- unknown non-empty codes create synthetic `unmapped` children.
- blank codes remain visible as `unmapped` using source name only as a safe
  presentation fallback; never capacity-map by name.

None of these states fails an otherwise valid measurement.

### R5. Historical evidence and privacy

Each group child stores aggregate `status_counts_json` and
`components_json` sufficient to audit configured code/name, observed code/name,
counts and `source_name_mismatch`. JSON must never include patient name,
prontuário, clinical text or complete source rows.

Known source code with a different observed name stays in its configured group
and records the mismatch. It does not auto-create or mutate a catalog.

### R6. Hospital totals and dual coverage

Compute over distinct observed sector identities:

- observed sector count;
- capacity-covered count: mapped to non-null capacity;
- calculable count: mapped to `standard`;
- known capacity: includes all non-null capacities, including 3A;
- calculable capacity and occupied numerator: only `standard` groups;
- hospital percentage and exceeded-by from calculable groups only.

With all 47 initial codes, tests must prove 44/47 capacity coverage, 43/47
calculable coverage, known capacity 658 and calculable capacity 626. Unknown
codes increase the observed denominator and neither coverage numerator.

### R7. Algorithm and deterministic ordering

Persist algorithm version exactly `occupancy-v1`. Normalize code strings
without converting away leading zeros. Order group creation and component JSON
deterministically so reruns and test evidence are stable.

## Expected files and hard scope limit

Expected implementation files, maximum **5** excluding `tasks.md` and report:

```text
apps/census/models.py
apps/census/migrations/00xx_occupancy_measurement.py
apps/census/occupancy.py
apps/census/management/commands/materialize_occupancy_measurement.py
tests/unit/test_occupancy_measurement.py
```

If SCOH-S1 chose a justified domain-module name, extend that cohesive module
instead of creating both it and `occupancy.py`, while staying within five files.
If a sixth implementation file is needed, stop for planner approval.

Forbidden in this slice:

- edits to `process_census_snapshot` or orchestrator;
- daily summary models/services;
- `/beds` view/template/tests;
- stale-admission or clinical-event joins;
- periodic tasks, signals, Celery or Redis;
- a bulk/backfill command;
- production access or real patient fixtures;
- edits to the approved initial catalog unless SCOH-S1 is formally reopened.

## Mandatory TDD cycle

### RED

Write synthetic tests first. Minimum failing scenarios:

1. pre-activation run creates no measurement;
2. first applicable run creates one parent and expected children;
3. repeated run returns same parent and unchanged child values;
4. later catalog cannot change an earlier measurement;
5. simple 8/10 calculation gives 80.00 and no exceedance;
6. shared Cardio capacity is applied once;
7. CO 54/8 gives 675.00 and exceeded-by 46;
8. non-occupied statuses are retained but excluded from numerator;
9. 3A, unrated, unknown and blank-code states remain explicit and null-rated;
10. all 47 configured codes yield 44/47, 43/47, 658 and 626;
11. unknown code lowers coverage without blocking;
12. name drift records mismatch without remapping;
13. model/JSON persistence contains no patient identifiers;
14. manual command requires one run and has no scan/backfill behavior;
15. a mid-transaction failure leaves no partial parent/children.

At least one test must fail by assertion for missing measurement behavior before
implementation.

### GREEN

Implement the smallest domain service and command that pass these scenarios.
Keep selection, aggregation and persistence out of the management command.
Prefer bulk aggregate queries or one deterministic pass through approximately
862 snapshot rows; avoid one query per group or row.

### REFACTOR

Only after GREEN:

- extract small calculation/value helpers when they remove duplication;
- keep query, pure calculation and persistence boundaries understandable;
- make type hints and names precise;
- remove magic strings except centralized policy/status choices;
- apply clean code, DRY and YAGNI;
- do not generalize for historical rebuild, arbitrary formulas or future UI.

Rerun tests after each refactor.

## Mandatory inspection checks

Run and interpret:

```bash
rg -n \
  "class OccupancyMeasurement|class OccupancyGroupMeasurement" \
  apps/census/models.py
rg -n \
  "occupancy-v1|ROUND_HALF_UP|transaction\.atomic|pre_activation" \
  apps/census/occupancy.py \
  apps/census/management/commands/materialize_occupancy_measurement.py
rg -n \
  "719|2156|1110|1112|1114|1116|linked_slots_pending|unmapped" \
  apps/census/occupancy.py tests/unit/test_occupancy_measurement.py
rg -n \
  "ClinicalEvent|report_suspected|stale|recent_event|Admission" \
  apps/census/occupancy.py
rg -n \
  "all-runs|backfill|rebuild|scan" \
  apps/census/management/commands/materialize_occupancy_measurement.py
rg -n \
  "materialize_occupancy|OccupancyMeasurement" \
  apps/census/services.py apps/census/views.py \
  apps/census/templates 2>/dev/null
rg -n 'markdownlint-''disable' \
  openspec/changes/add-versioned-sector-capacity-occupancy-history
uv run python manage.py makemigrations --check --dry-run

git diff --check
git status --short
```

Expected interpretation:

- both model classes, algorithm version, rounding and transaction are present;
- special policies/codes have tests;
- clinical/stale query search has no production-code match;
- command exposes no scan/backfill mode;
- services/view/template search has no automatic integration from this slice;
- no Markdown suppression, migration drift or whitespace error exists.

## Binary success criteria

- [ ] Every R1 through R7 has direct passing evidence.
- [ ] A valid RED assertion is captured before production implementation.
- [ ] Measurement and children are transactionally idempotent per run.
- [ ] Shared groups, extreme over-capacity and rounding are exact.
- [ ] 3A is not approximated and hospital numerator/denominator exclude it.
- [ ] Dual coverage and totals equal the design for 47 codes.
- [ ] Unknown/name-drift behavior is visible and nonblocking.
- [ ] No patient identifier exists in new history models or JSON.
- [ ] No automatic integration, daily summary or UI was implemented.
- [ ] File limit, inspections and all official gates pass.
- [ ] Final tests have zero failures/errors and no passed-count regression.
- [ ] Required report and verifier handoff are complete.

## Self-evaluation gates

Answer `YES` or `NO` with evidence:

1. Did a test fail for missing behavior before production edits?
2. Is the run, not `captured_at`, the one-to-one idempotency key?
3. Can a second call recalculate an existing measurement with a newer catalog?
4. Does every group preserve resolved historical values?
5. Are 54 raw occupied CO rows still 54 regardless of clinical evolution?
6. Is 3A excluded from both hospital numerator and denominator?
7. Do all aggregate JSON keys avoid patient-level data?
8. Does an unknown code lower coverage and remain visible?
9. Did you avoid editing processing, summaries and UI?
10. Did final pytest exit 0 with zero failures/errors and at least baseline pass
    count?
11. Did Markdown lint and strict OpenSpec validation pass?
12. Did the diff stay within five implementation files?

Any `NO` means incomplete.

## Automatic INCOMPLETE conditions

The slice is automatically incomplete if:

- SCOH-S1 tasks or baseline are not complete;
- baseline/RED/final evidence is absent or invalid;
- any final gate fails or final passed count regresses;
- percentages use float, truncate, cap at 100 or use inconsistent rounding;
- shared capacity is applied per member instead of once;
- suspected stale patients are filtered;
- 3A receives an approximate percentage;
- unrated/unmapped sectors disappear or fail the measurement;
- existing measurement is updated/recomputed;
- patient identifiers enter models, JSON, logs or report;
- command can scan or backfill multiple runs;
- integration, daily summary or `/beds` work appears;
- migration drift, partial transaction behavior or unexplained extra files exist;
- more than five implementation files are touched without approval;
- tasks are checked before evidence is complete;
- report lacks RED/GREEN, before/after snippets, reruns or verifier handoff;
- commit/push is missing after technical completion.

## Official validation commands

Run every command:

```bash
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
openspec validate \
  add-versioned-sector-capacity-occupancy-history \
  --type change --strict
```

Host-only pytest may be used diagnostically but is not an official gate.

## Mandatory temporary report

Create `/tmp/sirhosp-slice-SCOH-S2-report.md` containing:

- status, `BASE_REF`, git state and prerequisite verification;
- requirement/file/test matrix;
- baseline, RED and GREEN exact commands, exit codes and summaries;
- failing RED assertion and why it proves the requirement;
- before/after snippets for every changed implementation file;
- files changed with scope justification;
- evidence for formulas, special mappings, coverage and privacy;
- every inspection command with interpretation;
- baseline versus final passed/failed/error table;
- every official gate and exit code;
- acceptance and self-evaluation answers;
- risks, limitations and deferred work;
- exact commands for rerun;
- final `Handoff para verificador` with:
  - commit hash and push result;
  - changed files;
  - R1 through R7 checklist;
  - exact third-party rerun commands;
  - manual checks for schema, JSON privacy and immutable behavior;
  - next slice `SCOH-S3` and its GCEC-S2 dependency.

Use no real patient data and pass Markdown lint on the report.

## Ready-to-run implementer prompt

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every artifact under
openspec/changes/add-versioned-sector-capacity-occupancy-history, especially
slice-prompts/SLICE-SCOH-S2.md. Verify SCOH-S1 is complete. Implement ONLY
SCOH-S2.

Follow the DeepSeek4-Flash protocol literally: BASE_REF, official containerized
unit baseline before edits, requirement matrix, real RED, minimal GREEN,
controlled REFACTOR, mandatory rg inspections, all official gates and
baseline-vs-final pytest evidence. Apply clean code, DRY and YAGNI.

Deliver only immutable run-scoped occupancy-v1 materialization and its explicit
single-run command. Touch at most five implementation files. Do not integrate
with process_census_snapshot, create daily summaries, edit /beds, query clinical
evolution, scan/backfill runs, access production or use real patient data.

If any prerequisite, test, inspection, gate, file limit, privacy condition,
commit or push fails, report INCOMPLETE and do not mark tasks.md. Otherwise mark
only tasks 2.1-2.8, create /tmp/sirhosp-slice-SCOH-S2-report.md, commit, push,
reply with REPORT_PATH=/tmp/sirhosp-slice-SCOH-S2-report.md and STOP for planner
review.
```
