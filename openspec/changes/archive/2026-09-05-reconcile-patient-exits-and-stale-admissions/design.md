## Context

Production read-only analysis found a large class of admissions that remain open
locally after the patient disappeared from the current census. The existing
historical discharge path persists `DischargeRecord` and daily aggregates but
does not invoke the legacy reconciler. Admission synchronization also treats a
mutable source admission key too strongly, which can preserve an open row and
create a later closed row for one source episode.

The change is clinically and operationally critical because it modifies episode
identity, discharge time and historical data. It must fail closed, retain
indefinite audit, avoid patient identity in logs and keep production backfill
outside implementation. All local-day decisions use `America/Bahia`.

Current architecture remains a Django monolith with PostgreSQL coordination,
management commands, Playwright connectors and systemd timers. Celery, Redis and
new services are outside scope.

### Current facts that constrain the design

- `Admission.discharge_date` is the canonical effective end of an episode.
- The XLS column `Saida` maps to `DischargeRecord.saida_em`; `Alta Medica` maps
  to `alta_em` and describes summary registration, not physical exit.
- `recover_historical_data` calls extraction services, but persisted discharge
  rows currently do not close admissions.
- The current census is intentionally not an authoritative discharge source.
- Existing `admissions_only` ingestion runs already provide targeted source
  synchronization through PostgreSQL.
- The repository contains legacy three-times-daily discharge systemd units, but
  read-only production inspection found neither those units nor historical
  recovery installed. The active hospital runtime uses
  `/srv/apps/prisma/compose.hospital.yml`; only ingestion health is scheduled by
  systemd, while census, ingestion and summary loops run as containers.

## Goals / Non-Goals

**Goals:**

- Establish one canonical, idempotent, evidence-linked exit reconciler.
- Make admission identity survive changes in external admission keys.
- Resolve only source-confirmed duplicates while preserving the oldest row.
- Turn repeated census absence into bounded source investigation, never a
  guessed exit.
- Make current and historical extraction reconcile persisted evidence and
  distinguish confirmed zero from missing data.
- Provide safe dry-run/apply/rollback tooling, protected review, aggregate
  monitoring and deployment guidance.
- Separate effective exits (`saida_em`) from medical summaries (`alta_em`) in
  dashboard and historical indicators.

**Non-Goals:**

- Executing any production backfill or enabling hourly production load during
  implementation.
- Inferring discharge datetime from census absence, `alta_em`, report date,
  date-only death or PDF date.
- Reactivating the legacy PDF flow as evidence or as an operational fallback;
  `process_discharge_pdf` is disabled and retained temporarily only for explicit
  deprecation before removal.
- Replacing the ingestion queue or systemd with Celery, Redis or microservices.
- Deleting merged admissions or shortening audit retention.
- Building a general master-patient-index or a broad redesign of clinical event
  models.
- Automatically refreshing all clinical summaries inside reconciliation.

## Decisions

### 1. Effective exit and summary timestamps remain separate

`Admission.discharge_date` is populated only from authoritative effective exit
evidence: `DischargeRecord.saida_em`, a source admissions snapshot end datetime,
or a complete death datetime. `alta_em` remains report evidence and feeds a
separate medical-summary indicator. A naive source datetime is interpreted in
`America/Bahia`; an exit before admission is invalid.

This prevents the current semantic error where the report creation time can be
mistaken for the end of an episode.

### 2. One canonical reconciliation service owns matching and mutation

A pure decision layer accepts normalized evidence and returns one of:
`pending`, `reconciled`, `already_reconciled`, `patient_not_found`,
`admission_not_found`, `ambiguous`, `conflict`, or
`invalid_exit_datetime`. A transactional application layer performs the
selected mutation under row locks and writes audit.

Matching order is fixed:

1. current `(source_system, source_admission_key)`;
2. historical key alias;
3. patient plus exact admission start;
4. patient plus local admission date only when exactly one canonical candidate
   exists.

Every weaker match is skipped once a stronger unique match succeeds. Adapters
must identify the precision they actually possess: the discharge XLS has no
admission key and its `data_internacao` is a local date, not an exact timestamp;
death evidence without an episode identifier may use only one canonical period
that contains a complete death datetime. Unavailable levels are skipped, never
synthesized. A key/alias match whose admission start is null cannot be
temporally validated and becomes `conflict`. Multiple candidates are
`ambiguous`; contradictory strong identifiers are `conflict`. Reconciliation
never creates synthetic patients or admissions.

Discharge and death extraction adapters normalize source rows then call this
service. Management commands stay orchestration-only. The legacy
`process_discharge_pdf` command is not part of the layered capture strategy: it
is marked inactive and must raise a safe deprecation error before opening a PDF,
printing patient data, persisting evidence or requesting work. The PDF-based
aggregate backfill `backfill_daily_discharges` is retired in the same step: it
is the last executable caller of the PyMuPDF helper and a PDF-driven writer of
the operational aggregate. The retired commands, the PyMuPDF helper and their
dedicated tests are candidates for removal after one release
cycle and confirmation that no operational caller exists.

### 3. Persist source aliases and preserve merged rows

`AdmissionSourceAlias` maps a unique `(source_system, source_admission_key)` to
one canonical Admission. The current key remains on Admission for compatibility
while all observed historical keys are retained as aliases.

Admission gains nullable self-reference `merged_into`. The default manager
(`Admission.objects`) filters to canonical rows (`merged_into IS NULL`) and
`Admission.all_objects` provides unfiltered maintenance access.

Decision recorded in RPSA-S1 (amending the original deferral): a global
canonical default is adopted instead of per-call-site `.canonical()` because
the spec's clinical-hiding requirement (`Merged record is hidden clinically`)
gets a zero-miss guarantee — an explicitly-filtered-per-site approach can miss
a site and leak merged rows into clinical views, which is the worse failure
mode. The maintenance-hiding risk of a global filter is compensated by a hard
gate: before any merge writer ships (RPSA-S4), every existing
`Admission.objects`/default-manager and reverse-accessor call site in `apps/`
must be inventoried and classified clinical versus maintenance; maintenance
paths that must observe merged rows are switched to `all_objects`, and Django
admin exposes both canonical and merged rows. Until that classification is
recorded, no code path may write `merged_into`.

Incoming closed snapshots first attempt current key, alias and unique period
resolution. They update the existing open row when unique rather than inserting
a second episode.

### 4. Automatic merge requires a fresh unique source episode

A local open/closed candidate pair is not sufficient. Automatic merge is
allowed only after a fresh admissions snapshot shows exactly one episode for
the patient and local admission date. More than one episode, source failure or
same-day ambiguity requires review.

For an eligible pair, the oldest primary key is canonical. The merge service:

1. locks both admissions and validates the source-confirmation fingerprint;
2. records before-state and relation ownership;
3. repoints every inventoried supported foreign key;
4. combines authoritative period and metadata without replacing non-empty data
   with empty values;
5. moves all source aliases;
6. marks the newer row `merged_into=canonical` rather than deleting it;
7. writes one operation-level append-only audit.

The first implementation slice must inventory all direct and indirect Admission
relations before the migration/service contract is finalized. An unsupported
relation is a hard stop, not a best-effort omission.

### 5. Evidence state and append-only audit are database-backed

`DischargeRecord` and `DeathRecord` gain nullable Admission linkage,
reconciliation status and reconciliation timestamp. `DischargeRecord` is
decoupled from `DailyDischargeCount` as report-batch storage so evidence
persistence never writes the operational aggregate. Source rows remain evidence
even when unresolved. Death persistence becomes stable-key upsert and never
deletes/recreates a row that carries linkage or reconciliation state.

Admission-owned models provide:

- source aliases;
- stale reconciliation cases and their observation/cooldown state;
- append-only reconciliation events with operation UUID, evidence kind and
  primary key, prior/new exit values, exit type, status, reason code and time;
- merge operations with canonical/merged identifiers, source-confirmation
  metadata, relation movement manifest, before/after state and rollback state.

Audit payloads store identifiers and structural state required for reversibility,
but no duplicated patient name, record number or free clinical text. Audit is
not aged out. Application code does not update or delete audit rows.

Database constraints cover closed status choices, alias uniqueness, no
self-merge, and valid evidence shape where practical. Service transactions use
`select_for_update` and deterministic ordering to avoid races.

### 6. Census absence only creates a case

Only successfully processed complete, unambiguous census runs contribute
observations. The first absence starts a case. Eligibility requires a second
consecutive complete absence and at least 30 elapsed minutes. Reappearance
resolves a case that is based only on census absence. Rejected or incomplete
runs neither advance nor reset state.

Eligible cases enqueue existing PostgreSQL-backed `admissions_only` work, at
most 100 patients per cycle. Deduplication checks active equivalent runs. The
cooldown is 6 hours after an inconclusive/recent suspicion and 24 hours after a
conclusive source response that still shows no exit. An explicit uniquely
matched `saida_em` bypasses census waiting.

Observation is called after successful snapshot processing in the existing
adaptive census cycle. An hourly management command is a safety net and uses a
distinct PostgreSQL advisory lock.

### 7. Empty discharge reports need semantic confirmation

One empty/missing XLS result is not success. The extraction service performs one
independent confirmation attempt. Two successful empty results constitute a
confirmed zero. A failed confirmation remains failed; a non-empty confirmation
is processed normally. Previous evidence is not replaced by an unconfirmed
zero.

Historical recovery includes reconciliation counters in step results. An
ambiguous row is preserved and counted but does not fail unrelated deterministic
rows. Re-running remains idempotent. Confirmed-zero and attempt count are stored
in durable ingestion-stage metadata so later health and catch-up processes do
not depend on an in-memory result.

All four historical service wrappers pass source username/password to automation
through a scoped child environment rather than argv. Entry points accept that
environment contract, fail safely when credentials are missing and never echo
values. This is implemented before any scheduled recovery is enabled.

### 8. Backfill reuses online services and is operationally separate

The backfill command is dry-run by default. Apply requires an explicit flag,
positive limit, operation label and backup reference. Automatic cohorts execute
in this order:

1. duplicate pairs with fresh one-episode source confirmation;
2. discharge evidence with exact patient/admission local date and valid
   `saida_em`;
3. death evidence with complete datetime and one compatible admission;
4. no automatic action for ambiguity, merely protected review.

The first authorized production canary is at most 50 patients. A later batch may
rise to 100 only after validation. Every applied row goes through the online
transaction and audit services. Each item has an operation UUID; one batch UUID
groups the exact ordered item operations from an applied command. Command-level
rollback validates every item post-state, then reverses the whole batch in
reverse order atomically or makes no change. Online single-item rollback remains
addressable by operation UUID.

Implementation and validation do not execute production apply. Summary refresh
is a separate bounded post-validation operation.

### 9. Indicators distinguish operational exit from medical summary

`DailyDischargeCount` becomes an aggregate of canonical
`Admission.discharge_date`, whose authoritative discharge source is
`saida_em`. The aggregate refresh is its sole writer: XLS persistence does not
write count or patient-bearing `raw_data`. The applied historical rebuild clears
legacy patient rows from `raw_data`, reports aggregate before/after counts and
uses `America/Bahia`; no new aggregate audit model is introduced.

The dashboard shows two cards and `/painel/altas/` shows two labeled series:
effective hospital exits by `saida_em` and medical summaries by `alta_em`.
Existing moving averages remain on the effective-exit series. Death exits are
not counted as hospital discharges.

### 10. Review UI and exports follow least privilege

A dedicated Django permission protects reconciliation queue and detail views.
Only authorized authenticated reviewers may see patient name and record number.
CSV is streamed from an authenticated request and is never written to a server
file. Application and journal logs contain aggregate counts and reason codes,
not patient identity or clinical text.

Django admin exposes canonical/merged state and append-only audit to appropriate
staff but does not provide delete/edit actions for audit rows.

### 11. Runtime uses an isolated hospital execution substrate

`compose.hospital.yml` gains a profile-gated, one-shot `historical_recovery`
service derived from the Playwright service anchor. It uses the immutable release
image, internal database/network, tmpfs and `/dev/shm` sizing, and never starts
with normal `up`. Both D-1 recovery and current-day discharge execute through
this runner, never through `web`.

A runtime command supplies distinct job locks, checks for queued/running
`IngestionRun` and open census batches before Playwright, and returns fixed
`EX_TEMPFAIL` code 75 when busy. It also records durable aggregate outcomes.
Systemd retries only temporary-busy outcomes every 10 minutes for at most six
attempts. Timer offsets and those guards prevent simultaneous scheduled
Playwright starts; residual user-triggered overlap remains monitored and is
called out in the runbook.

Bounded benchmarks cover both hourly current-day discharge and the worst allowed
four-extractor, seven-date catch-up. Until the latter passes, automation runs D-1
only and multi-date catch-up remains manual.

### 12. Systemd schedules and immutable release assets are explicit

Versioned systemd units and timers provide:

- benchmark-gated hourly current-day discharge extraction;
- one daily D-1 invocation at `05:00:00 America/Bahia` of
  `recover_historical_data`, explicitly selecting `discharges`, `admissions`,
  `deaths` and `official_census`;
- benchmark-gated catch-up of at most seven missing dates;
- staggered hourly bounded stale-admission safety sweep.

Systemd, rather than cron, is the canonical scheduler so installation,
activation, logs and rollback are inspectable in one place. Units target
`/srv/apps/prisma`, `.env` and `compose.hospital.yml`, or consume an explicit
environment file resolving to those values; legacy `/opt/sirhosp` is not
assumed. The timezone is anchored in each `OnCalendar`, independent of host
default timezone.

The immutable release ships Compose, upgrade runbook, scheduler script and units
as same-tag assets because the hospital host has no repository clone. Timers are
deployed disabled. Historical activation requires runner validation, D-1 dry-run
and all-four-extractor smoke test. Hourly extraction and automatic catch-up each
require their applicable benchmark. Health checks report durable confirmed-zero
coverage, backlog counts/age, ambiguities and duplicate invariants. No timer
calls `process_discharge_pdf`.

## Data Flow

```text
Discharge XLS / admissions snapshot / death evidence
                    |
                    v
       source-specific normalization
                    |
                    v
      canonical match decision (read-only)
                    |
          +---------+----------+
          |                    |
      unique match         unresolved
          |                    |
          v                    v
 transactional close     evidence status +
 or confirmed merge      admissions_only/review
          |
          v
 append-only audit -> daily aggregate -> protected UI/health
```

```text
complete census N -> first absence case
complete census N+1 + >=30 min -> eligible case
             -> bounded admissions_only source confirmation
             -> canonical reconciler if authoritative exit appears
```

## Migration and Rollout Sequence

1. Inventory Admission foreign keys, query paths and source datetime shapes;
   add characterization tests before schema changes.
2. Add aliases, merge marker, evidence links/statuses and append-only audit with
   backward-compatible nullable fields.
3. Centralize admission identity and canonical exit reconciliation; route
   discharge/death/current admissions writers through it and disable
   `process_discharge_pdf` before it reads or mutates data.
4. Re-run the relation inventory after discharge/death evidence FKs exist, then
   add confirmed merge, rollback and normal-query filtering.
5. Add census cases, dedicated review permission, post-census observation and
   bounded safety queue.
6. Add zero confirmation with durable coverage, recovery integration and remove
   report persistence as a `DailyDischargeCount` writer.
7. Move credentials out of argv for all four historical extractor subprocesses.
8. Add indicators, protected review, aggregate health and dry-run backfill.
9. Add the profile-gated hospital recovery runner, runtime guards and benchmark
   commands.
10. Package disabled-by-default systemd schedules as immutable release assets and
    complete the hospital runbook.
11. Deploy code and observe dry-run/health. Each benchmark and timer activation
    is an explicit operational checkpoint. Production backfill is a later
    separately authorized operation.

## Alternatives Considered

### Close admissions directly from census absence

Rejected. Census extraction can be incomplete, delayed or operationally
ambiguous and supplies no authoritative exit datetime.

### Continue using only the latest external admission key

Rejected. The source can change keys for one episode, and key-only identity is
the mechanism that preserves residual open rows.

### Delete duplicate admissions

Rejected. Deletion weakens clinical traceability and makes relation recovery and
rollback harder. A merge marker preserves provenance.

### Use `alta_em` when `saida_em` is missing

Rejected. The fields represent different events and can cross dates.

### Keep the PDF command as a secondary signal

Rejected. The command has no deployed scheduler, logs identity and derives a
clinical timestamp not present in the source. Layered coverage is provided by
XLS discharge extraction, admission snapshots, death extraction, census
suspicion and protected review. Keeping the PDF active would add ambiguity
without authoritative evidence.

### Add Celery or Redis for stale-case work

Rejected. Existing PostgreSQL ingestion runs, advisory locks and systemd timers
satisfy bounded phase-1 needs.

### Require the official daily census before investigation

Rejected. It is useful corroboration but has different timing and should not
block current-source confirmation.

### Run production backfill as part of deployment

Rejected. The observed scale and clinical impact require backup, benchmark,
canary, review and explicit operator authorization.

## Risks / Trade-offs

- **Relation loss during merge** -> hard inventory gate, relation-manifest tests,
  atomic updates and no delete.
- **False episode match** -> ordered matching, exact/unique fallback only,
  same-day ambiguity and source confirmation before merge.
- **Race between extractors** -> row locks, alias uniqueness, deterministic
  ordering, runtime job locks, queue-drain/open-batch guards and staggered
  timers; user-triggered overlap remains a monitored residual.
- **Load on legacy source** -> separate hourly and seven-date catch-up benchmark
  gates, cooldown, active-run deduplication, per-cycle cap and schedules disabled
  by default.
- **Credential exposure in process lists** -> remove username/password from argv
  before any scheduled historical runtime is activated.
- **Aggregate semantic overwrite** -> decouple evidence persistence from
  `DailyDischargeCount` and keep exactly one aggregate writer.
- **Long-lived audit growth** -> append-only normalized metadata and hashes
  without duplicating clinical text; accept storage cost for traceability.
- **Hidden merged rows surprise maintenance code** -> explicit canonical query
  helpers first; retain unfiltered admin/maintenance access.
- **Two indicator semantics confuse users** -> explicit labels, separate cards
  and series, with operational exit primary.
- **Date-only death remains unresolved longer** -> deliberate safety trade-off;
  request source admissions data rather than fabricate time.
- **Rollback after later edits may be impossible automatically** -> strict
  post-state precondition and manual escalation rather than partial reversal.

## Open Questions

- The first implementation slice must record the complete reverse-FK and
  many-to-many inventory for Admission and decide which relations require
  custom merge handling.
- The source death payload must be characterized to identify which rows provide
  a true time versus a date parsed at midnight.
- Exact benchmark thresholds for hourly source access and the maximum
  four-extractor catch-up must be measured independently; their corresponding
  automation remains disabled until each passes.
- Removal of `process_discharge_pdf` and its PDF helper requires a final static
  and operational caller check after the deprecation cycle; it is inactive from
  this change onward.
