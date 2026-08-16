# SLICE-SCOH-S4: Enrich `/beds` with official occupancy

## Handoff for a zero-context implementer

You are implementing the fourth and final feature slice in SIRHOSP. The first
three slices already provide an immutable catalog, per-census measurements,
daily summaries and automatic materialization after completeness validation.
This slice exposes only the exact latest-census measurement on the existing
authenticated `/beds` page while preserving its bed and patient detail.

Read completely before editing:

1. `AGENTS.md` and `PROJECT_CONTEXT.md`;
2. every artifact in
   `openspec/changes/add-versioned-sector-capacity-occupancy-history/`;
3. all previous slice prompts and available reports in `/tmp`;
4. this file;
5. `apps/census/views.py`, especially `bed_status_view`;
6. `apps/census/templates/census/bed_status.html` completely;
7. `apps/census/occupancy.py` and the measurement models;
8. `tests/unit/test_bed_status_view.py` completely;
9. `apps/census/urls.py` only to confirm the route, which must not change.

Verify tasks 1.1 through 3.8 are checked and inspect the implemented contracts.
If the exact-run measurement or daily integration is incomplete, stop instead
of recreating calculations in the view.

## Mandatory protocol for DeepSeek4-Flash

Any failed item makes the slice **INCOMPLETE**. Do not update tasks, commit or
push.

1. Record `BASE_REF=$(git rev-parse HEAD)` and initial `git status --short`.
2. Stop on unexplained edits in expected files; preserve unrelated work.
3. Write `Requirement -> file(s) -> test(s)/inspection(s)` in the report before
   implementation.
4. Run `./scripts/test-in-container.sh unit` before editing and record exit code
   and complete passed/failed/error summary. Baseline failure blocks work.
5. Add/adjust tests first and run the official unit suite. Capture at least one
   assertion RED caused by missing capacity presentation. Import/template setup
   errors are not valid RED.
6. Implement minimal GREEN. Keep calculations in existing domain/presentation
   helpers, not inline in view or template.
7. Preserve authentication, patient links, status labels, empty state and raw
   fallback with regression tests.
8. Execute every mandatory inspection and explain the matches.
9. Run every official final gate. Final unit must exit 0, have zero
   failures/errors and `passed_final >= passed_baseline`.
10. Mark only tasks 4.1-4.7, create the report, commit, push and stop. If commit
    or push fails, report incomplete.

## Objective

An authenticated user opening `/beds` sees official group capacity, raw legacy
occupancy percentage, excedent and two coverage indicators for the exact latest
census measurement. Shared groups appear once, their source-sector beds remain
expandable, and absence of an exact measurement safely falls back to the
current raw table without stale statistics.

## Current technical context

Current `/beds` behavior:

- `@login_required` protects `bed_status_view`;
- view selects the maximum `CensusSnapshot.captured_at`;
- rows are grouped by observed `setor` name and status;
- global totals include occupied, empty, maintenance, reserved and isolation;
- each row expands into beds and shows patient name/link when occupied;
- no capacity or measurement is read.

After SCOH-S3:

- `OccupancyMeasurement` is one-to-one with a census `IngestionRun`;
- its group children contain resolved names, capacities, status counts,
  components, percentages, exceeded-by and calculation statuses;
- parent contains known/calculable totals and dual coverage;
- 3A is capacity-known but `linked_slots_pending`;
- unknown/unrated groups are explicit;
- the page must never compute or infer these values independently.

## Functional scope

### R1. Exact latest-measurement selection

Select the current raw snapshot exactly as today. Resolve capacity statistics
only when all rows in that latest set identify one non-null run and that exact
run has one measurement.

- do not select `latest measurement` independently;
- do not reuse an older measurement;
- do not calculate from current catalog in the view;
- expose census capture and catalog effective date when exact data exists.

### R2. Safe fallback and empty state

When there is no census, preserve the existing empty message. When a latest
census exists but exact measurement is absent, preserve existing sector rows,
status totals, expansions and patient links, and show capacity as
`Pendente`/`Indisponível`. Do not hide current census data.

### R3. Official grouped presentation

When exact measurement exists, show one row per measured official group or
synthetic unmapped group:

- group display name;
- observed occupied, empty, reserved, maintenance, isolation and total;
- official capacity when known;
- persisted percentage and exceeded-by when calculable;
- calculation state otherwise.

For shared groups, combine summary counts once while retaining contributing
source sectors and every bed inside the expansion. Do not duplicate capacity 15
for Cardio or capacity 8 for CO.

Use a cohesive helper in `apps/census/occupancy.py` if grouping current snapshot
rows would otherwise put business/presentation assembly loops in the view.
The helper must consume persisted measurement results, not recalculate rates.

### R4. Registered-legacy semantics and over-capacity warning

Display the exact label:

`Lotação registrada no sistema legado`

For percentage greater than 100.00:

- apply a Bootstrap-compatible visual highlight;
- include textual `Acima da capacidade` or equivalent;
- show absolute exceeded-by value;
- do not rely on color alone;
- do not cap or adjust raw CO occupants.

At or below 100.00, do not render the warning.

### R5. Dual coverage and hospital totals

Show persisted values, not hard-coded constants:

- `<covered> de <observed> setores com capacidade cadastrada`;
- `<calculable> de <observed> setores com lotação calculável`;
- capacity known;
- capacity calculable;
- hospital occupancy numerator, percentage and exceeded-by based only on
  calculable groups.

Tests may use the approved 44/47, 43/47, 658 and 626 example, but template code
must render model values.

### R6. Explicit non-calculable states

- 3A shows capacity 32 and text that calculation awaits cama-berço mapping;
- `unrated` and `unmapped` show `Capacidade não cadastrada` or equivalent;
- null percentage never renders as `0%`;
- component/source name mismatch can be shown as a safe data-quality hint but
  must not remap the group.

### R7. Preserve existing authorization and detail

Keep:

- `@login_required`;
- `/beds/` route and navigation contract;
- patient detail only for users already authorized by this page;
- current patient links, status labels and expansion behavior;
- no new API or client-side dependency.

Do not add a historical page, daily chart, catalog editor or stale-patient
workflow.

## Expected files and hard scope limit

Expected implementation files, maximum **4** excluding `tasks.md` and report:

```text
apps/census/occupancy.py
apps/census/views.py
apps/census/templates/census/bed_status.html
tests/unit/test_bed_status_view.py
```

If no helper change is needed, touch only three. Do not create a CSS or
JavaScript file; use existing Bootstrap and semantic HTML. More than four
implementation files requires planner approval and an incomplete stop.

Forbidden in this slice:

- models or migrations;
- catalog/measurement/daily formula changes;
- processing, extraction, scraper or orchestrator changes;
- routes, permissions or authentication changes;
- historical UI or charts;
- new dependency;
- production access or real-patient fixtures.

## Mandatory TDD cycle

### RED

Write synthetic authenticated view/template tests before production edits.
Minimum scenarios:

1. exact run measurement displays capture time and effective date;
2. no exact measurement preserves raw latest table and shows pending state;
3. older measurement is never reused for newer census;
4. shared Cardio and CO each render one official summary row;
5. shared row expansion retains contributing source sectors and beds;
6. persisted status counts, capacity and percentage render correctly;
7. >100% shows visual plus textual warning and exceeded-by;
8. <=100% has no over-capacity warning;
9. label `Lotação registrada no sistema legado` is present;
10. dual coverage renders from parent values, including 44/47 and 43/47;
11. known 658 and calculable 626 totals are distinguished;
12. 3A shows 32 and pending pair mapping, never a percentage;
13. unrated/unmapped show unavailable, never 0%;
14. existing empty state, patient link, status label and expansion remain;
15. anonymous request still redirects to login.

At least one new test must fail by assertion for missing capacity UI before
implementation.

### GREEN

Add the smallest query/presentation context and template markup needed. Reuse
persisted values exactly. Preserve existing context keys where possible to
limit regression risk.

### REFACTOR

Only after GREEN:

- extract one cohesive presenter/helper if it removes complex view logic;
- avoid duplicate status/default dictionaries;
- use explicit context names and simple template branches;
- keep template accessible and avoid nested condition duplication;
- enforce clean code, DRY and YAGNI;
- do not refactor unrelated hospital-flow code in the same view module.

Rerun view tests after every refactor.

## Mandatory inspection checks

Run and interpret:

```bash
rg -n \
  "@login_required|def bed_status_view|OccupancyMeasurement" \
  apps/census/views.py
rg -n \
  "Lotação registrada no sistema legado|Acima da capacidade" \
  apps/census/templates/census/bed_status.html
rg -n \
  "capacidade cadastrada|lotação calculável|Capacidade não cadastrada" \
  apps/census/templates/census/bed_status.html
rg -n \
  "linked_slots_pending|cama-berço|exceeded" \
  apps/census/templates/census/bed_status.html apps/census/occupancy.py
rg -n \
  "ROUND_HALF_UP|/.*capacity|official_capacity.*100|percentage.*=" \
  apps/census/views.py apps/census/templates/census/bed_status.html
rg -n \
  "path\(.*beds|name=\"bed_status\"" \
  apps/census/urls.py
rg -n \
  "patient_id|status_label|collapse|Nenhum dado de censo disponível" \
  apps/census/views.py apps/census/templates/census/bed_status.html \
  tests/unit/test_bed_status_view.py
rg -n 'markdownlint-''disable' \
  openspec/changes/add-versioned-sector-capacity-occupancy-history

git diff --check
git status --short
```

Expected interpretation:

- authentication decorator and exact-run measurement query remain;
- all critical labels and accessible warning text exist;
- calculation-pattern search has no new rate formula in view/template;
- route remains unchanged;
- patient/status/expansion/empty-state contracts remain represented;
- no Markdown suppression or whitespace errors exist.

Also inspect rendered HTML in tests, not only template source. Confirm the
warning text is associated with the same group row as the over-capacity value.

## Binary success criteria

- [ ] R1 through R7 each have passing test or inspection evidence.
- [ ] A valid assertion RED is captured before UI implementation.
- [ ] Exact run is required and older measurement is never shown as current.
- [ ] Raw fallback and empty state preserve current behavior.
- [ ] Shared groups render once without losing bed/source detail.
- [ ] UI contains no occupancy formula or stale-patient adjustment.
- [ ] Over-capacity uses text and visual styling and shows exceeded-by.
- [ ] Dual coverage and known/calculable totals come from persisted values.
- [ ] 3A, unrated and unmapped null percentages are explicit, never zero.
- [ ] Authentication, patient links and status details remain protected.
- [ ] No models, migrations, routes, processing or future UI changed.
- [ ] File limit, inspections and every official gate pass.
- [ ] Final pytest has zero failures/errors and no passed-count regression.
- [ ] Report and verifier handoff are complete.

## Self-evaluation gates

Answer `YES` or `NO` with evidence:

1. Did a test fail for missing capacity presentation before implementation?
2. Can the page ever use a measurement from another run?
3. Can a view/template branch calculate a percentage from raw rows?
4. Does fallback preserve current data instead of hiding it?
5. Do Cardio and CO each have one summary capacity row?
6. Are all source beds still reachable inside shared expansions?
7. Is over-capacity understandable without color?
8. Can null percentage appear as zero?
9. Are the two coverage labels semantically distinct?
10. Is `@login_required` and patient-link behavior preserved by regression tests?
11. Did final pytest exit 0 without failures/errors and with enough passed tests?
12. Is the diff within four implementation files and free of unrelated work?

Any `NO` means incomplete.

## Automatic INCOMPLETE conditions

Mark incomplete if any occurs:

- SCOH-S1, S2 or S3 is not complete;
- baseline or RED evidence is absent/invalid;
- any final gate fails or passed count regresses;
- page selects latest measurement independently of latest census run;
- view/template calculates rate, coverage or adjusted occupancy;
- older measurement is shown as current;
- fallback, empty state, authentication, patient link or expansion regresses;
- shared groups duplicate official capacity;
- >100% is color-only or lacks exceeded-by;
- 3A receives an approximate/zero percentage;
- unrated/unmapped sector disappears;
- model, migration, route, processing, scraper or orchestrator is edited;
- more than four implementation files are touched without approval;
- report lacks snippets, rendered evidence, gates or verifier handoff;
- real patient data appears in tests/report;
- tasks are marked before all criteria;
- commit or push is missing after technical completion.

## Official validation commands

Run all:

```bash
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
openspec validate \
  add-versioned-sector-capacity-occupancy-history \
  --type change --strict
```

Host-only execution is diagnostic only.

## Mandatory temporary report

Create `/tmp/sirhosp-slice-SCOH-S4-report.md` containing:

- status, `BASE_REF`, git state and prerequisite evidence;
- requirement/file/test matrix;
- baseline, RED and GREEN commands, exit codes and summaries;
- RED assertion excerpt and expected reason;
- before/after snippets for every changed file;
- changed-file list and scope justification;
- rendered HTML assertions for exact measurement, fallback, shared groups,
  warning, coverage and non-calculable states;
- inspection commands, results and interpretation;
- baseline versus final passed/failed/error table;
- every official gate and exit code;
- acceptance checklist and self-evaluation answers;
- accessibility, privacy and regression risks;
- exact rerun commands;
- final `Handoff para verificador` with:
  - changed files, commit hash and push result;
  - R1-R7 checklist;
  - exact commands for third-party rerun;
  - manual rendered-page checks;
  - confirmation that no history UI or formula was added;
  - recommendation for final governance verification.

Report Markdown must lint cleanly and contain only synthetic examples.

## Ready-to-run implementer prompt

```text
Read AGENTS.md, PROJECT_CONTEXT.md and all artifacts under
openspec/changes/add-versioned-sector-capacity-occupancy-history, especially
slice-prompts/SLICE-SCOH-S4.md. Verify SCOH-S1 through SCOH-S3 are complete.
Implement ONLY SCOH-S4.

Follow the DeepSeek4-Flash protocol literally: BASE_REF, official unit baseline
before editing, requirement matrix, real assertion RED, minimal GREEN,
clean-code/DRY/YAGNI refactor, all rg/render inspections, every official gate
and baseline-vs-final pytest evidence.

Enrich only /beds from the exact latest-census measurement. Preserve raw
fallback, authentication, patient links, status labels, empty state and
expansions. Use persisted values; do not calculate rates in view/template or
adjust stale patients. Touch at most four implementation files. Do not edit
models, migrations, routes, processing, extraction, scraper, orchestrator or
future historical UI. Use synthetic test data only.

If any prerequisite, test, inspection, gate, regression, file limit, commit or
push fails, report INCOMPLETE and do not mark tasks. Otherwise mark only tasks
4.1-4.7, create /tmp/sirhosp-slice-SCOH-S4-report.md, commit, push, reply with
REPORT_PATH=/tmp/sirhosp-slice-SCOH-S4-report.md and STOP for planner review.
```
