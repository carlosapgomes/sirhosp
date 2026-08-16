# SLICE-SCOH-S1: Publish the versioned capacity catalog

## Handoff for a zero-context implementer

You are implementing the first of four vertical slices in the SIRHOSP Django
project. This slice delivers an operator-visible, tested flow: validate a
complete capacity catalog and publish it atomically for a future local date.
It does not calculate occupancy yet.

Before planning or editing, read completely:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. `openspec/changes/add-versioned-sector-capacity-occupancy-history/proposal.md`;
4. `openspec/changes/add-versioned-sector-capacity-occupancy-history/design.md`;
5. all specs under that change;
6. `openspec/changes/add-versioned-sector-capacity-occupancy-history/tasks.md`;
7. this file;
8. `apps/census/models.py` and its latest migrations;
9. `apps/census/management/commands/import_wards_beds_registry.py` only as a
   command-style reference, not as architecture to reuse.

The authoritative initial mapping is the table in `design.md`. Do not consult
production, invent capacities or include patient data. Existing `Ward` and
`Bed` tables are not the versioned catalog and must not be repurposed.

## Mandatory protocol for DeepSeek4-Flash

This slice will be implemented by a fast model that can conclude too early.
Follow this protocol literally. If any item fails, the slice is **INCOMPLETE**:
do not check `tasks.md`, do not commit or push, and respond with the blocker and
evidence.

1. Record `BASE_REF=$(git rev-parse HEAD)` before editing and put it in the
   report.
2. Confirm `git status --short` is understood. Do not overwrite unrelated user
   changes; if expected files already contain unexplained edits, stop.
3. Write a mini matrix `Requirement -> file(s) -> test(s)` in the report before
   implementation.
4. Run the official baseline before editing:
   `./scripts/test-in-container.sh unit`. Record exit code and the complete
   pytest summary. Host-only pytest is diagnostic and cannot replace this gate.
5. If baseline has any failure/error or nonzero exit code, stop as
   `INCOMPLETE/BLOCKED` before coding.
6. Create tests first and run the official unit command again. At least one new
   test must fail for the expected missing behavior. A syntax, import, fixture
   or environment failure is not valid RED.
7. Implement only the minimum GREEN for this slice. Do not implement
   measurement, daily summary, `/beds` UI or census integration.
8. Run the inspection checks below and interpret every result in the report.
9. Run all official final gates listed below. The final unit suite must have
   exit code 0, zero failures/errors and `passed_final >= passed_baseline`.
10. Update only tasks 1.1 through 1.7 after every criterion is proven. Then
    create the report, commit, push and stop. If commit or push cannot be
    completed, report `INCOMPLETE` without claiming completion.

## Objective

An operator can provide a complete JSON catalog, validate it with `--dry-run`
and publish it for tomorrow or a later date. The operation is atomic,
idempotent for the same date and hash, and preserves every earlier version.

## Current technical context

- `apps/census/models.py` contains `CensusSnapshot`, `Ward`, `Bed` and other
  census models, but no capacity model.
- Census migrations currently end at `0013_patientmovement.py`; inspect rather
  than assume the next number.
- Project timezone is `America/Bahia` with `USE_TZ=True`.
- The initial catalog has 42 definitions and 47 unique source codes:
  - 39 groups with known capacity totaling 658;
  - 38 `standard` groups totaling calculable capacity 626;
  - `OBST-3A`, capacity 32, policy `linked_slots_pending`;
  - three `unrated` groups for codes `733`, `1522` and `1002`.
- Shared groups are `ENF-2B-CARD` (`719`, `2156`, capacity 15) and `CO`
  (`20`, `1110`, `1112`, `1114`, `1116`, capacity 8).
- The JSON is a versioned synthetic configuration. Do not commit the original
  spreadsheet from `/home/dev/Downloads`.

## Functional scope

### R1. Minimal temporal catalog schema

Create the minimal additive models described in `design.md`:

- `CapacityCatalogVersion`;
- `CapacityGroupDefinition`;
- `CapacitySectorMembership`.

Use explicit constraints/indexes for effective date, stable key, source code and
positive capacities where the database can enforce them. Use `PROTECT` for
historical relationships. Do not change or migrate existing `Ward`/`Bed` rows.

### R2. Whole-document validation

Implement cohesive domain validation outside the management command. It must
reject duplicate stable keys, duplicate source codes, cross-catalog ambiguity,
invalid policy/capacity combinations, missing required names/codes and malformed
JSON before any write.

Only these policies exist in this slice:

- `standard` with positive capacity;
- `linked_slots_pending` with positive capacity;
- `unrated` with null capacity.

### R3. Controlled future activation

Implement `activate_sector_capacity_catalog` with required `--input`, required
`--effective-from` and optional `--dry-run`.

- compare against `timezone.localdate()`;
- require a date strictly after today;
- validate and hash before persistence;
- use `transaction.atomic()`;
- persist source reference, SHA-256 and schema version;
- never update or delete an existing version.

### R4. Idempotency and conflicts

For an existing effective date:

- same document hash is a successful no-op;
- different hash is a hard conflict with no mutation.

Concurrent duplicate publication must be protected by database uniqueness and
handled without creating a partial catalog.

### R5. Approved initial catalog

Create one JSON file under `apps/census/data/` using exactly the mapping and
provenance in `design.md`. Tests must prove:

- 42 groups;
- 47 unique codes;
- 39 groups with capacity;
- 44 capacity-covered codes;
- 43 calculable codes;
- known capacity 658;
- calculable capacity 626;
- exact shared and special groups listed in the current context.

No patient, credential, production dump or real clinical payload may appear.

### R6. Dry-run and output safety

Dry-run must execute the same parsing and validation as publication and print
aggregate totals, effective date and hash without persistence. Command output
and exceptions must not include patient data or dump the entire input document.

## Expected files and hard scope limit

Expected implementation files, maximum **6** excluding `tasks.md` and the
temporary report:

```text
apps/census/models.py
apps/census/migrations/00xx_capacity_catalog.py
apps/census/capacity_catalog.py
apps/census/management/commands/activate_sector_capacity_catalog.py
apps/census/data/initial_sector_capacity_catalog.json
tests/unit/test_sector_capacity_catalog.py
```

You may choose a more accurate migration filename after inspecting the graph.
If a seventh implementation file is necessary, stop and report the reason; do
not exceed the limit autonomously.

Forbidden in this slice:

- `apps/census/views.py` or templates;
- measurement or daily-summary models;
- edits to extraction, orchestration or Playwright;
- editable Django Admin;
- new dependencies;
- data migrations with a hard-coded activation date;
- loading or changing production data.

## Mandatory TDD cycle

### RED

Write tests before production code. Minimum failing scenarios:

1. valid initial JSON produces exact totals and mappings;
2. duplicate code and duplicate stable key are rejected;
3. every invalid policy/capacity combination is rejected;
4. today/past effective dates are rejected with zero rows;
5. dry-run creates zero rows;
6. valid future activation creates the complete graph atomically;
7. same date/hash is idempotent;
8. same date/different hash is rejected without mutation;
9. simulated validation failure leaves no partial version/group/member.

Run `./scripts/test-in-container.sh unit` and capture the expected assertion
failure caused by missing catalog behavior.

### GREEN

Implement the smallest clear solution that passes the new tests. Keep JSON
parsing, validation and persistence in cohesive functions in
`capacity_catalog.py`; keep the command as an argument/output adapter.

### REFACTOR

After GREEN only:

- remove duplicated policy checks and magic totals;
- use descriptive immutable DTO/value shapes where useful;
- keep functions short and transactional boundaries explicit;
- apply clean code, DRY and YAGNI;
- do not create generic repository layers, plugin systems or future policies.

Rerun tests after every refactor.

## Mandatory inspection checks

Execute and include command plus interpreted result in the report:

```bash
python -m json.tool \
  apps/census/data/initial_sector_capacity_catalog.json >/dev/null
rg -n \
  "class CapacityCatalogVersion|class CapacityGroupDefinition" \
  apps/census/models.py
rg -n \
  "class CapacitySectorMembership" \
  apps/census/models.py
rg -n \
  "effective-from|dry-run|transaction\.atomic|timezone\.localdate|sha256" \
  apps/census/capacity_catalog.py \
  apps/census/management/commands/activate_sector_capacity_catalog.py
rg -n \
  '"(719|2156|20|1110|1112|1114|1116|654|733|1522|1002)"' \
  apps/census/data/initial_sector_capacity_catalog.json
rg -n \
  "OccupancyMeasurement|DailyOccupancy|bed_status_view" \
  apps/census tests/unit/test_sector_capacity_catalog.py
rg -n 'markdownlint-''disable' \
  openspec/changes/add-versioned-sector-capacity-occupancy-history \
  AGENTS.md PROJECT_CONTEXT.md
uv run python manage.py makemigrations --check --dry-run

git diff --check
git status --short
```

Interpretation requirements:

- JSON parser must exit 0;
- all three catalog classes and command safeguards must be present;
- special codes must be present in the initial catalog;
- the occupancy/UI search must have no new implementation attributable to this
  slice;
- the Markdown suppression search must have no match;
- migration check and diff check must exit 0.

## Binary success criteria

- [ ] R1 through R6 each map to at least one passing test.
- [ ] Baseline and final unit summaries are recorded and final passed count is
  not lower.
- [ ] Initial totals and every special mapping equal the approved design.
- [ ] Dry-run, future date, atomicity, idempotency and conflict behavior pass.
- [ ] No pre-existing model data is migrated or production data accessed.
- [ ] No implementation beyond the six-file limit or this slice exists.
- [ ] All inspection checks have evidence and interpretation.
- [ ] Every official validation command exits 0.
- [ ] Markdown lint reports zero errors.
- [ ] The report exists and contains `Status: COMPLETE` only if all above pass.

## Self-evaluation gates

Answer each with `YES` or `NO` plus evidence in the report:

1. Did a new test fail for the intended missing catalog behavior before code?
2. Does every source code occur exactly once in the initial catalog?
3. Can any command path publish a catalog for today or the past?
4. Can a validation or conflict failure leave partial rows?
5. Can an existing published version be edited by this command?
6. Did you accidentally implement measurement, summaries or UI?
7. Did final pytest have exit code 0, zero failures and zero errors?
8. Is `passed_final >= passed_baseline`?
9. Did all project Markdown pass lint without suppression comments?
10. Is the diff free of patient data, credentials and the original spreadsheet?

Any `NO` makes the slice incomplete.

## Automatic INCOMPLETE conditions

Mark this slice `INCOMPLETE` if any occurs:

- an expected test was not written or not executed;
- official baseline was not recorded before editing;
- RED passed before implementation or failed for environment/import reasons;
- any final test, check, lint, typecheck or OpenSpec validation failed;
- final pytest has nonzero exit, any failure/error or fewer passed tests;
- migration drift remains;
- initial totals/mappings differ from the design;
- date validation uses UTC date instead of project-local date;
- dry-run writes data, or activation is not atomic/idempotent;
- unrelated model, view, template, scraper or dependency was changed;
- implementation exceeds six files without prior planner approval;
- `tasks.md` is checked despite a missing criterion;
- report is missing evidence, before/after snippets or verifier handoff;
- report contains sensitive/real patient data;
- commit or push was not completed after all technical gates passed.

## Official validation commands

Run all of these, not substitutes:

```bash
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
openspec validate \
  add-versioned-sector-capacity-occupancy-history \
  --type change --strict
```

Also run the exact focused test path in a container if practical and include the
command. Host-only commands are diagnostic and do not satisfy official gates.

## Mandatory temporary report

Create:

`/tmp/sirhosp-slice-SCOH-S1-report.md`

The report must contain:

- `Status: COMPLETE` or `Status: INCOMPLETE`;
- `BASE_REF` and initial git status;
- requirement-to-file-to-test matrix;
- baseline command, exit code and full pytest summary;
- RED command, failing test names, expected reason and output excerpt;
- GREEN commands, exit codes and summaries;
- before/after snippets for every changed implementation file;
- files changed and justification;
- inspection commands, output summaries and interpretation;
- baseline versus final passed/failed/error comparison;
- every official gate with exact command and exit code;
- binary acceptance checklist and answers to all self-evaluation gates;
- risks, limitations and confirmation that future slices were not implemented;
- exact rerun commands;
- final section `Handoff para verificador` containing:
  - files changed;
  - commit hash and push result;
  - requirement checklist R1 through R6;
  - commands a third LLM must rerun;
  - claims requiring manual inspection;
  - next expected slice `SCOH-S2`.

The report itself must pass project Markdown lint and contain no sensitive data.

## Ready-to-run implementer prompt

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every artifact under
openspec/changes/add-versioned-sector-capacity-occupancy-history, especially
slice-prompts/SLICE-SCOH-S1.md. Implement ONLY SCOH-S1.

Follow the DeepSeek4-Flash protocol literally: record BASE_REF and clean-state
context, run the official containerized unit baseline before editing, write the
requirement matrix, prove a real RED, implement minimal GREEN, REFACTOR only
after green, run every inspection and official gate, compare baseline versus
final pytest, and create the required evidence report.

Deliver only the future-dated, immutable, whole-catalog activation flow and the
approved synthetic initial JSON. Do not implement occupancy measurements,
daily summaries, census integration, UI, Admin editing or future slices. Touch
at most six implementation files. Apply clean code, DRY and YAGNI. Do not use
real patient data or access production.

If any required test/check/gate is missing or failing, if final pytest has any
failure/error, if passed_final is lower than baseline, if the file limit is
exceeded, or if commit/push cannot complete, report INCOMPLETE and do not mark
tasks.md. Otherwise update only tasks 1.1-1.7, create
/tmp/sirhosp-slice-SCOH-S1-report.md, commit, push, reply with
REPORT_PATH=/tmp/sirhosp-slice-SCOH-S1-report.md and STOP for planner review.
```
