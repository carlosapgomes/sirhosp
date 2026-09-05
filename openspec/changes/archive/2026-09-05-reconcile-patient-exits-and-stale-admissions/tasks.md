## 1. Identity and canonical exit foundation

- [x] **RPSA-S1 — Layered admission identity and relation inventory**
  - Characterize every Admission reverse relation and every production query
    path before schema mutation.
  - Add source-key aliases and nullable `merged_into` with database constraints,
    canonical/unfiltered query access and additive migration.
  - Update admissions snapshot upsert to resolve current key, alias, exact start
    and unique local date in order, failing closed on same-day ambiguity.
  - Prove that a closed snapshot with a changed key updates one compatible open
    episode rather than inserting a duplicate.
  - Evidence: `slice-prompts/SLICE-RPSA-S1.md` and
    `/tmp/sirhosp-slice-RPSA-S1-report.md`.

- [x] **RPSA-S2 — Canonical hospital-discharge reconciliation**
  - Add nullable Admission/status linkage to discharge evidence and append-only
    reconciliation audit.
  - Implement pure match decision plus transactional, locked application using
    only identifiers/precision present in each normalized source shape,
    `saida_em` in `America/Bahia`, never `alta_em`.
  - Decouple `DischargeRecord` persistence from `DailyDischargeCount` so report
    rows cannot overwrite the operational aggregate.
  - Route persisted discharge rows through the canonical service and preserve
    all closed statuses and idempotency.
  - Keep logs identity-safe and enqueue bounded source synchronization instead
    of creating synthetic domain rows.
  - Depends on: RPSA-S1.
  - Evidence: `slice-prompts/SLICE-RPSA-S2.md` and
    `/tmp/sirhosp-slice-RPSA-S2-report.md`.

- [x] **RPSA-S3 — Death reconciliation and legacy PDF retirement**
  - Link death evidence to canonical reconciliation.
  - Close only the unique episode whose known period contains a complete
    death datetime; date-only and unresolved rows enqueue `admissions_only`
    without synthetic hour.
  - Convert repeated death persistence to stable-key upsert that preserves the
    evidence PK, Admission link and reconciliation state.
  - Mark `process_discharge_pdf` and the PDF-based `backfill_daily_discharges`
    command inactive: every invocation fails safely before reading a PDF,
    logging identity, persisting evidence, enqueuing work or changing
    aggregate or clinical state.
  - Update active documentation and mark both commands plus the dedicated PDF
    helper as removal candidates after one release cycle and caller
    verification.
  - Depends on: RPSA-S2.
  - Evidence: `slice-prompts/SLICE-RPSA-S3.md` and
    `/tmp/sirhosp-slice-RPSA-S3-report.md`.

## 2. Duplicate resolution and conservative discovery

- [x] **RPSA-S4 — Source-confirmed merge and rollback**
  - Re-derive the Admission relation inventory against the post-S2/S3 schema,
    requiring a superset of S1 that explicitly includes discharge and death
    evidence links.
  - Classify every `Admission.objects`/reverse-accessor call site as clinical
    versus maintenance, recorded in the change's evidence inventory; switch
    maintenance paths that must observe merged rows to `all_objects` and
    expose both rows in admin before any merge writer ships.
  - Implement source-confirmation eligibility for exactly one episode.
  - Keep the oldest Admission, transfer every inventoried supported relation,
    preserve aliases, mark `merged_into` and write immutable operation audit.
  - Add atomic rollback with a strict post-state precondition and no partial
    mutation.
  - Exclude merged rows from normal clinical queries while retaining explicit
    admin/maintenance visibility.
  - Depends on: RPSA-S1, RPSA-S2 and RPSA-S3.
  - Evidence: `slice-prompts/SLICE-RPSA-S4.md` and
    `/tmp/sirhosp-slice-RPSA-S4-report.md`.

- [x] **RPSA-S5 — Two-census absence detection and bounded confirmation**
  - Add idempotent PostgreSQL-backed reconciliation cases and absence
    observations.
  - Advance only on two consecutive accepted complete runs separated by at
    least 30 minutes; ignore rejected runs and resolve census-only suspicion on
    reappearance.
  - Create the dedicated reconciliation-review permission in the same additive
    model migration and prove it exists after migrate.
  - Trigger observation post-census and provide an hourly safety command.
  - Enqueue at most 100 deduplicated `admissions_only` runs using 6-hour and
    24-hour cooldowns; never close from census absence.
  - Route exit-reconciliation `conflict` evidence (null admission start or
    contradictory strong identifiers) into the same bounded sync queue, since
    re-syncing the admissions catalog can populate the missing start.
  - Depends on: RPSA-S1.
  - Evidence: `slice-prompts/SLICE-RPSA-S5.md` and
    `/tmp/sirhosp-slice-RPSA-S5-report.md`.

- [x] **RPSA-S6 — Permission-protected reconciliation review and ephemeral CSV**
  - Add queue/detail routes protected by a dedicated reconciliation permission.
  - Show names and record numbers only after authorization; deny access without
    disclosing cases.
  - Stream filtered CSV without a server-side file and keep logs free of patient
    identity and body content.
  - Land the two RPSA-S5 deferred display fixes: evidence-resolved cases read
    `exit_confirmed` on reappearance, and merged+closed cases stay frozen in
    the settled evaluation step.
  - Show merged/canonical state and immutable audit safely in Django admin.
  - Depends on: RPSA-S2, RPSA-S4 and RPSA-S5.
  - Evidence: `slice-prompts/SLICE-RPSA-S6.md` and
    `/tmp/sirhosp-slice-RPSA-S6-report.md`.

## 3. Extraction, indicators and historical repair tooling

- [x] **RPSA-S7 — Confirmed-zero discharge extraction and recovery integration**
  - Require one independent retry before accepting an empty or missing discharge
    report as semantically confirmed zero.
  - Keep a failed confirmation failed and process a non-empty confirmation
    normally without overwriting prior evidence prematurely.
  - Persist `zero_confirmed` and attempt count in ingestion-stage metadata for
    later health/catch-up processes.
  - Stop discharge evidence persistence from writing `DailyDischargeCount` and
    make the post-reconciliation refresh its sole extraction-triggered writer.
  - Expose reconciliation counters through extraction and historical recovery,
    preserving idempotency and partial-failure semantics.
  - Depends on: RPSA-S2.
  - Evidence: `slice-prompts/SLICE-RPSA-S7.md` and
    `/tmp/sirhosp-slice-RPSA-S7-report.md`.

- [x] **RPSA-S7A — Credential-safe historical subprocess transport**
  - Remove source username and password from argv for admission, discharge,
    death and official-census automation subprocesses.
  - Pass credentials only through a scoped child environment and make each
    automation entry point reject missing values without echoing credentials.
  - Prove command lines, safe errors and captured output contain no credential
    values while preserving existing extraction behavior.
  - Land the three RPSA-S7 deferred P2s: failure-stage metadata carries
    `attempt_count`/`zero_confirmed`, confirmation timeout sets
    `timed_out=True`, and the recovery mock matches the real
    unconfirmed-zero shape.
  - Depends on: RPSA-S7.
  - Evidence: `slice-prompts/SLICE-RPSA-S7A.md` and
    `/tmp/sirhosp-slice-RPSA-S7A-report.md`.

- [x] **RPSA-S8 — Effective-exit aggregates and separate summary indicators**
  - Rebuild `DailyDischargeCount` from canonical effective exits by `saida_em`
    in `America/Bahia` with dry-run and aggregate before/after output.
  - Clear legacy patient-bearing `raw_data` and prove aggregate refresh is the
    only remaining writer.
  - Add separate dashboard cards and chart series for effective exits and
    `alta_em` medical summaries, retaining moving averages on exits.
  - Exclude death exits from hospital-discharge indicators.
  - Depends on: RPSA-S2 and RPSA-S7.
  - Evidence: `slice-prompts/SLICE-RPSA-S8.md` and
    `/tmp/sirhosp-slice-RPSA-S8-report.md`.

- [x] **RPSA-S9 — Bounded dry-run backfill and operation rollback**
  - Add deterministic cohorts in the mandated order: confirmed duplicates,
    exact-date discharges, complete-datetime deaths, then manual ambiguities.
  - Default to dry-run; require explicit apply, positive limit, operation label
    and backup reference.
  - Assign one operation UUID per item and one batch UUID per apply; rollback a
    batch only after validating every item post-state and then reverse all items
    atomically.
  - Document and test 50-record canary then maximum 100-record later batches;
    do not run production apply.
  - Land the RPSA-S8 deferred P2: episode-level counting fixture (same
    patient, two canonical same-day exits count 2).
  - Depends on: RPSA-S3 and RPSA-S4.
  - Evidence: `slice-prompts/SLICE-RPSA-S9.md` and
    `/tmp/sirhosp-slice-RPSA-S9-report.md`.

## 4. Monitoring and production runtime

- [x] **RPSA-S10 — Aggregate reconciliation health and integrity report**
  - Extend read-only health diagnostics with durable ingestion-stage
    confirmed-zero coverage, missing dates, status backlog/count/age, ambiguity
    and source-confirmed duplicate invariants.
  - Return nonzero on configured violations and report only aggregate-safe
    output.
  - Add the daily integrity command without source calls, queue writes or
    clinical mutation.
  - Depends on: RPSA-S4, RPSA-S5 and RPSA-S7.
  - Evidence: `slice-prompts/SLICE-RPSA-S10.md` and
    `/tmp/sirhosp-slice-RPSA-S10-report.md`.

- [x] **RPSA-S11 — Hospital recovery runner, coordination and benchmarks**
  - Add a profile-gated one-shot `historical_recovery` service to
    `compose.hospital.yml`, inheriting Playwright tmpfs and shared-memory guards
    and never starting under normal `up`.
  - Add runtime locks, drained-queue/open-batch eligibility and fixed temporary
    busy code 75 before launching Playwright.
  - Benchmark hourly current-day discharge separately from the maximum
    four-extractor, seven-date catch-up; keep each automation disabled until its
    own threshold passes.
  - Depends on: RPSA-S5, RPSA-S7A and RPSA-S10.
  - Evidence: `slice-prompts/SLICE-RPSA-S11.md` and
    `/tmp/sirhosp-slice-RPSA-S11-report.md`.

- [x] **RPSA-S12 — Systemd schedules, release assets and operational runbook**
  - Version disabled-by-default hourly extraction, staggered safety sweep and a
    timer anchored at `05:00:00 America/Bahia` that runs D-1 with all four
    extractors explicitly.
  - Retry only temporary-busy code 75 every 10 minutes for at most six attempts;
    do not retry final extractor failure at the systemd layer.
  - Ship scripts and units as immutable same-tag release assets for the no-clone
    hospital deployment under `/srv/apps/prisma/compose.hospital.yml`.
  - Document baseline, installation, smoke tests, independent benchmark gates,
    activation, monitoring, disablement, rollback and absence of cron/PDF calls.
  - Land the documentation-routed deferred notes from RPSA-S5/S8/S9/S10/S11
    (sweep-vs-orchestrator window, summary-series axis, authorized-backfill
    runbook with duplicate-cohort gating, health options/daily-command doc
    plus the pipeline_health comment fix, benchmark calibration guidance).
  - Depends on: RPSA-S11.
  - Evidence: `slice-prompts/SLICE-RPSA-S12.md` and
    `/tmp/sirhosp-slice-RPSA-S12-report.md`.

## 5. Final independent verification

- [x] **RPSA-FINAL — Cross-artifact and release-readiness verification**
  - Confirm every normative scenario is mapped to an automated test or an
    explicit deployment inspection.
  - Run the complete containerized quality gate and Markdown lint.
  - Prove from dry-run and synthetic fixtures that zero unequivocal discharge
    evidence remains open and zero source-confirmed duplicate pair remains
    unresolved.
  - Confirm no production backfill, timer enablement, credential or real patient
    data occurred during the change.
  - Confirm RPSA-S1 through RPSA-S12, including RPSA-S7A, are complete and that
    runtime artifacts ship with the immutable release.
  - Verify ADR-0009, specs, design, tasks, runbook and implementation agree.
  - Depends on: every implementation slice RPSA-S1 through RPSA-S12.
  - Evidence: `slice-prompts/SLICE-RPSA-FINAL.md` and
    `/tmp/sirhosp-slice-RPSA-FINAL-report.md`.
