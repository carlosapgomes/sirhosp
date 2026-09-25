## Context

See `proposal.md` for motivation and scope. The source state is split across
immutable census rows and measurements, mutable or reconciled clinical evidence,
and downstream patient-processing batches:

- `IngestionRun(intent="census_extraction")` owns a full hospital census and
  records `started_at`/`finished_at`.
- `CensusSnapshot` is the only per-run, per-sector, bed-level photograph.
- `OccupancyMeasurement` and its group rows preserve official capacity and
  occupancy for the exact run and historical catalog.
- `CensusExecutionBatch` is created after census processing to drain
  per-patient synchronization work; it does not own the source census and may
  finish much later.
- `PatientMovement` is date-granular, collapses repeated same-day visits to a
  sector and is therefore not a sufficient transfer-event ledger.
- effective hospital exits use `DischargeRecord.saida_em`; deaths may have an
  exact `obito_em` or only a source date; neither source guarantees sector.

The page and workbook contain sensitive patient identity. The change is
classified as CRÍTICO and stays within the phase-1 modular monolith,
PostgreSQL coordination and systemd/management-command operation.

## Goals / Non-Goals

**Goals:**

- Produce a deterministic daily projection from accepted census runs and
  persisted source evidence.
- Preserve clinical time, detection time, source provenance, historical sector
  grouping and report revision independently.
- Keep page and XLSX fast and mutually consistent by reading the same
  materialized revision.
- Fail closed on ambiguous identity, sector, classification or completeness.
- Allow automatic late-evidence revisions without changing source-domain
  records or the selected closing photograph.

**Non-Goals:**

- Observe movements that leave no difference between consecutive census
  photographs.
- Turn `PatientMovement` into a canonical event stream.
- Change admission, discharge, death or occupancy reconciliation rules.
- Reconstruct dates before feature activation.
- Add manual corrections, report editing or approval workflow.
- Add Celery, Redis, pandas, XlsxWriter or persisted workbook files.

## Decisions

### 1. Census extraction runs, not clinical batches, define the window

The selector will use successful `census_extraction` runs and explicit Bahia
local boundaries. A run is accepted only when its snapshots pass existing
completeness/provenance rules and resolve the exact occupancy measurement.

For local date `D`:

- opening = earliest accepted run with `finished_at` in `[D 00:00, D 03:00)`;
- closing = latest accepted run with `started_at >= D 20:00` and
  `finished_at < D+1 00:00`;
- anchor = latest accepted run before opening;
- opening and closing must be distinct.

`CensusExecutionBatch.finished_at` is deliberately excluded. It represents the
drain of clinical synchronization, has no authoritative source-census FK and
can move a photograph to another day merely because work was slow.

Alternative considered: `CensusSnapshot.captured_at`. It is close to
persistence completion and remains useful as photograph metadata, but
`IngestionRun.finished_at` matches the stakeholder's explicit completion
contract and provides one run-level boundary.

### 2. A dedicated reporting module owns a materialized read model

Create a modular Django app such as `apps.statistics_reports`; avoid the name
`apps.statistics`, which can collide conceptually with Python's standard
`statistics` module. Domain apps remain authoritative for source facts, while
the reporting app owns only the reproducible projection.

The model shape is:

- `DailyStatisticsReport`: local date, revision, status, activation boundary,
  anchor/opening/closing run FKs, closing measurement/catalog context,
  source fingerprint, quality metadata and generation timestamps;
- `DailyStatisticsSector`: historical stable key/display label plus persisted
  closing metrics or immutable references sufficient to reproduce them;
- `DailyStatisticsPatient`: closing-sector patient row with only the nominal
  fields required by page/export and source-snapshot provenance;
- `DailyStatisticsEvent`: one logical event with kind, patient/admission
  references where resolved, historical nominal fields, nullable clinical
  instant/date, detection interval, origin/destination, attribution quality,
  source kind/id and deterministic fingerprint;
- `StatisticsExportLog`: actor, served timestamp, report/revision, selected date
  and aggregate row/sheet counts, with no nominal payload.

Uniqueness will cover `(local_date, revision)`, sector per report, patient/event
fingerprints per report and one current ready revision per date. Date/status,
report/sector/kind and provenance lookup paths receive composite indexes.

Alternative considered: derive on every request. Rejected because mutable
source evidence could make the page and workbook disagree, queries would grow
with all source history, and an audited download could not identify an exact
revision.

Alternative considered: write events progressively during every census.
Rejected for the first version because all accepted snapshots are retained; an
idempotent close-of-day scan is simpler and progressive writes still cannot see
movements between snapshots.

### 3. Report publication is atomic and idempotent

A materializer computes a complete candidate revision inside a transaction,
uses deterministic fingerprints, validates invariants and only then marks the
revision current/ready. A failed build never partially replaces the prior ready
revision.

A source fingerprint covers the selected run IDs, closing measurement/catalog,
relevant evidence IDs and normalized values used by the projection. Repeating a
build with the same fingerprint is a no-op. Changed late evidence creates a new
revision and supersedes the former current revision; it never mutates the old
revision in place.

The closing photograph and its official metrics stay pinned across a
late-evidence revision unless the accepted closing-run selection itself changes
under the same deterministic boundary rules.

### 4. Transfers come from raw consecutive census photographs

The materializer compares identified occupied patients across the anchor,
opening and every accepted run through closing. It does not use
`PatientMovement` as the event source because that model has date precision and
a uniqueness key that collapses repeated visits.

A sector change produces one transfer event with origin and destination. The
projection layer renders that one event in the origin's exit list and the
destination's entry list. A bed-only change inside the same official grouping
produces no sector event.

Patient matching uses normalized source-system patient identity and fails
closed for missing or conflicting identity. The report records incomplete or
ambiguous transitions as quality cases instead of selecting a patient or sector
arbitrarily.

### 5. Event classification uses explicit precedence and origin policy

The stable normalized kinds are:

- `hospital_admission`;
- `internal_transfer`;
- `death`;
- `hospital_discharge`;
- `unclassified_entry`;
- `unclassified_departure`.

Public labels explain the missing information rather than exposing generic
"unclassified" wording:

- `unclassified_entry` → `Entrada no setor — origem não identificada`;
- `unclassified_departure` → `Saída do setor — destino não identificado`;
- confirmed `internal_transfer` without one endpoint → `Transferência interna —
  origem não identificada` or `Transferência interna — destino não
  identificado`.

A transfer is one logical kind with both legs rather than separate duplicated
facts. Exit precedence is death, effective hospital discharge, internal
transfer, then `unclassified_departure`.

Origin classification is a versioned policy mapping normalized source values or
codes into `external` or `hospital_internal`. Emergency, operating room and
unmonitored hospital sectors are internal. Unknown values use
`unclassified_entry` unless independent evidence already confirms an internal
transfer. The policy must be data-driven and tested; ad hoc string checks in
views or templates are forbidden.

Alternative considered: infer every absent-to-present patient as a hospital
admission. Rejected because it would inflate admissions whenever origin data is
missing or a patient came from an unmonitored hospital sector.

### 6. Clinical and detection time are separate fields

Events store:

- `occurred_at` when an exact aware clinical instant exists;
- `occurred_on` when only a clinical date exists;
- `detected_not_before` from the prior accepted run;
- `detected_at` from the detecting run.

No synthetic hour is created. Source clinical date determines the event's local
report date when available; observation-only transitions use the detecting
run's local date and retain their uncertainty interval. Late exact evidence can
therefore revise a formerly observation-only classification.

### 7. Sector attribution is historical and quality-labeled

Sector identity uses the closing run's exact catalog graph and stable official
group keys. Display labels and partitioning are pinned to that historical
catalog. Official capacity, occupancy, balance and excess are copied from or
strictly referenced to the exact immutable group measurement; they are never
recomputed in the view, template or exporter.

For a discharge or death with no source sector, the materializer uses the last
unique census sector at or before the event. The event records
`sector_attribution="inferred_last_census"`. No unique prior position means
`unknown`, not the patient's current or final sector.

The existing occupancy presentation logic should expose or reuse public
mapping/presentation primitives where necessary. Copying its capacity formulas
or maintaining a parallel catalog graph is out of bounds.

### 8. Page and export read one projection service

A query/presentation service returns report metadata, sector headers, category
counts, naturally sorted event rows and closing patients. Both HTML and XLSX use
this same projection contract.

The canonical route is `/statistics/`; Django's slash behavior may redirect
`/statistics`. The default date is yesterday when ready, otherwise the latest
ready date, never today. The HTML follows the Bootstrap collapse and
accessibility patterns already used by `/beds/`. Events whose origin and
destination are both unknown cannot be assigned to an official sector and are
therefore shown once in a report-level `Setor não identificado` section rather
than being silently omitted or arbitrarily attributed. XLSX mirrors that
section with a conditional worksheet of the same name only when such events
exist.

Natural bed sorting tokenizes textual and numeric segments, puts missing beds
last and then uses normalized name and record as tie-breakers. The helper is
shared by HTML and XLSX.

### 9. Permissions and sensitive-response policy are separate

Add `view_daily_statistics` and `export_daily_statistics`. The sidebar checks
view permission; the export endpoint additionally checks export permission.
Authentication alone is insufficient.

HTML and XLSX responses use private/no-store cache policy. Workbooks are built
in memory and are never stored. Logs, exceptions and report-generation output
must contain aggregate IDs/counts only, not patient names, records or clinical
text.

Manual adjustment permission and UI are explicitly deferred.

### 10. XLSX generation reuses openpyxl with defensive normalization

Use the existing `openpyxl` dependency. Each official presentation unit gets
one sheet. When the selected revision contains events with neither origin nor
destination sector, one additional conditional `Setor não identificado` sheet
preserves those events without pretending it is an official grouping. Sheet
names are sanitized to Excel's character and 31-character limits,
de-duplicated deterministically and accompanied by the full unit name inside
the sheet.

Every sheet contains fixed sections in the required order, including empty
sections and a styled count cell beside each title. Text beginning with
formula-significant characters is escaped. For expected hospital-scale volume,
in-memory generation is acceptable; implementation tests must measure bounded
query behavior and can use write-only mode if styling requirements permit.

An export log is committed only after workbook generation succeeds and the
response is ready to be served. Its meaning is `arquivo gerado e servido pelo
servidor`, not proof that a browser saved it.

### 11. Close-of-day operation uses management commands and PostgreSQL

Add an idempotent management command that materializes one requested date and a
bounded command/mode that finalizes eligible prior dates. Integrate it with the
existing systemd/PostgreSQL operational model; no request should trigger a
large historical rebuild.

Deployment activation records the first eligible local date. Dates before it
remain unavailable. The operator can rerun one date after late evidence, which
creates or reuses the proper revision according to the source fingerprint.

Before activation, intraday and D-1 exit recovery plus death-extraction cadence
must have operational evidence; otherwise the report may be published with a
quality warning but must not claim source freshness that was not observed.

### 12. Architecture decision is recorded before persistence lands

Because this change adds a clinical reporting projection, sensitive-data
permissions, revisions and audit retention, implementation must add an ADR
covering the materialized/versioned read model, source-of-truth boundaries,
automatic revision policy and rollback. The ADR does not authorize manual
clinical correction.

## Risks / Trade-offs

- Movements entirely between censuses remain invisible → label the coverage
  honestly and preserve detection intervals; evaluate an ADT feed separately
  if exact movement capture becomes mandatory.
- Origin source values may be unknown or drift → version the mapping, reject
  unknown values to a pending category and characterize real values before
  activation without logging identity.
- Discharge/death evidence can duplicate, retract or disagree → use source
  provenance, deterministic fingerprints, precedence and automatic revisions;
  never silently merge contradictory evidence.
- Sector for discharge/death is inferred → store attribution quality and keep
  unknown when no unique prior position exists.
- Sensitive data is duplicated into a historical projection → store only fields
  required by the report, enforce dedicated permissions/no-store, avoid files
  and document retention in the ADR.
- Large workbooks can consume memory → share bounded projection queries, assert
  query budgets and use streaming workbook mode if compatible with layout.
- Concurrent finalizers can publish competing revisions → use transaction-level
  constraints/locking and one current revision invariant.
- Catalog algorithms evolve → pin run, measurement, algorithm and catalog in
  every revision; never substitute the current catalog.
- Downstream clinical batches may still be running → keep them out of window
  selection and mark evidence completeness separately where relevant.

## Migration Plan

1. Add and accept the ADR, migrations and permissions without enabling the
   materializer.
2. Deploy read-only run selection and materialization commands behind an
   activation setting/date.
3. Validate synthetic and non-identifying aggregate dry runs for opening,
   closing, origin mappings, late evidence and report invariants.
4. Activate from a declared future Bahia local date; do not backfill earlier
   dates.
5. Materialize the first eligible completed day and verify aggregate counts,
   sector coverage, permissions and export logs.
6. Enable the menu/page/export only after a ready report exists and operational
   recovery cadence is confirmed.
7. Monitor generation failures, degraded reports, revisions and export counts
   without logging identity.

Rollback disables materialization and navigation/export first. Because source
models are untouched, application rollback leaves report tables isolated; a
follow-up migration may remove them only after retention/audit approval.
Generated XLSX files require no cleanup because they are not persisted.

## Open Questions

- The exact normalized source values that identify external origin, emergency,
  operating room and unmonitored hospital sectors must be characterized before
  activation and recorded in the versioned origin policy.
- The activation date and systemd invocation schedule can be chosen during the
  operations slice without changing behavior or schema.
