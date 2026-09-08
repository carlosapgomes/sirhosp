## Context

See `proposal.md` for the operational problem. The current main chart mixes a
direct evidence series (`DischargeRecord.alta_em`) with an indirect canonical
series (`Admission.discharge_date` plus reconciled `ReconciliationEvent`). A
production read-only comparison showed complete `saida_em` capture but large
historical reconciliation backlogs, so the canonical series expresses both
patient flow and reconciliation completeness.

`DailyDischargeCount` is deliberately canonical under ADR-0009 and is also read
by hospital-flow calculations. Reusing that table for a different meaning would
silently change downstream analytics. `DischargeRecord` already upserts by the
existing `(prontuario, data_internacao)` uniqueness contract, and the observed
volume is small enough for bounded 30–365-day aggregate queries without a new
materialization.

The existing reconciliation queue is permission-protected and is therefore the
appropriate surface for quality comparisons that ordinary dashboard users do
not need.

## Goals / Non-Goals

**Goals:**

- Make the main dashboard and discharge page answer only the management
  question “how many patients effectively left?”.
- Preserve calendar continuity and `America/Bahia` boundaries.
- Keep reconciliation visible as data-quality information without gating the
  management count.
- Preserve the canonical aggregate and reconciliation domain for episode
  identity and readmission handling.

**Non-Goals:**

- Change reconciliation, merge, backfill or admission-closing rules.
- Execute production backfill as part of implementation or deployment.
- Replace `DailyDischargeCount` or change hospital-flow semantics silently.
- Add schema, queues, schedulers or external dependencies.

## Decisions

### 1. Query `DischargeRecord.saida_em` directly for management indicators

The dashboard current-day card, main daily chart and date list use evidence with
non-null `saida_em`, grouped with explicit `America/Bahia` boundaries. The main
query counts evidence rows regardless of reconciliation status.

Alternatives considered:

- **Keep the canonical series and finish the backfill:** rejected as the primary
  management contract because future reconciliation delays would distort flow
  again.
- **Repurpose `DailyDischargeCount`:** rejected because ADR-0009 and existing
  hospital-flow consumers assign it canonical semantics.
- **Add a new materialized table:** deferred because current volume does not
  justify a migration or second writer. Query performance must be measured in
  the focused tests; an index/materialization can be a later measured change.

### 2. Keep only one event series on the main discharge chart

The green `alta_em` series and reconciliation comparisons leave the main chart.
SMA-7, EMA-7, SMA-30 and weekend colors remain, but are calculated only from
captured `saida_em` counts. This keeps the primary chart operationally legible.

The hourly specialty analysis is not removed: its intended question is bed
release timing, so it also moves from `alta_em` to `saida_em`. Labels and help
text must explicitly say effective patient exit.

### 3. Build an explicit consecutive calendar axis

For `dias=N`, the view creates exactly N labels ending yesterday and overlays
query results by date, defaulting missing dates to zero. Weekday averages and
moving averages consume that same complete sequence.

This avoids the current behavior where the last N database rows can represent
more than N calendar days and omit legitimate zero days.

### 4. Put multi-dimensional quality information on the protected reconciliation surface

The existing permission-protected reconciliation page receives aggregate-only
comparison data for an explicit period:

- exits captured by `saida_em`;
- canonical reconciled hospital exits;
- summaries registered by `alta_em`.

No patient identity enters the chart payload or logs. Existing row-level review
continues to enforce its current permission. This is a secondary quality view,
not another series on `/painel/altas/`.

Alternative considered: a second chart on the main discharge page. Rejected
because it would preserve the visual competition the operator explicitly wants
to remove and would expose reconciliation details outside the established
least-privilege surface.

### 5. Make the linked discharge list coherent with the primary count

The current list relies on the legacy `DailyDischargeCount.records`/`raw_data`
relationship, while post-ADR-0009 evidence is deliberately decoupled and
`raw_data` is cleared. The list instead filters `DischargeRecord.saida_em` by
the selected Bahia date and uses the same count contract as the chart.

### 6. Amend, rather than replace, ADR-0009

ADR-0009 remains authoritative for canonical admission closure, reconciliation,
audit and `DailyDischargeCount`. Its indicator clauses are amended to state that
management presentation may count source-captured `saida_em` independently,
while canonical aggregates remain available for domain integrity and quality
monitoring.

## Risks / Trade-offs

- **A malformed or duplicated evidence row could enter the management count** →
  retain existing upsert uniqueness, characterize re-extraction idempotency and
  test cross-date corrections before changing the view.
- **Direct aggregates may become slower as evidence grows** → bound every query
  by the requested period, measure query count, and defer indexing until there
  is production evidence of need.
- **Main chart and canonical hospital-flow figures can differ** → use explicit
  labels and expose the difference on the protected quality surface.
- **Moving averages change historically after zero-day insertion** → accept this
  as correction to calendar-based analytics and pin it with regression tests.
- **Patient identity exposure through the list** → preserve existing
  authentication and rendering policy; diagnostics remain aggregate-only and
  permission-protected.

## Migration Plan

1. Implement the primary chart/card/list behavior with synthetic regression
   fixtures reproducing a large pending-reconciliation gap.
2. Add the protected aggregate quality comparison without altering row-level
   reconciliation behavior.
3. Amend ADR-0009 and operator-facing labels/documentation.
4. Run the project containerized quality gate and markdown lint.
5. Deploy as a code-only release; no migration or automatic backfill runs.
6. Validate aggregate-only production totals against read-only `saida_em`
   counts for recent dates.

Rollback is an image rollback: no schema or data migration is involved, and the
canonical aggregate remains untouched throughout.
