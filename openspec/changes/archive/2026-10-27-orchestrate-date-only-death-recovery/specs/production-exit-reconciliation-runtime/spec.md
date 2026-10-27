# Spec Delta: production-exit-reconciliation-runtime

## MODIFIED Requirements

### Requirement: Previous-day recovery runs in the orchestrator quiet window

Production SHALL run the D-1 recovery (`run_exit_reconciliation_runtime
--mode d1`, selecting `discharges`, `admissions`, `deaths` and
`official_census` in canonical order) inside the adaptive census
orchestrator loop, when the loop is eligible (queue drained, no open census
batch) and the local time is in the quiet window `[01:00, 05:00)`
`America/Bahia`. The systemd calendar timer is no longer the primary
scheduling path; the manual scheduler remains the documented fallback for
operator re-execution and catch-up. After the D-1 extraction completes, the
runtime SHALL reconcile the recovered date's date-only death evidence: each
`DeathRecord` of that local date is processed by the online death path,
closing only on a unique date-granularity match, fail-closed per record,
and emitting one success marker with aggregate counts after the step ends.

#### Scenario: Daily timer fires

- **WHEN** the orchestrator loop becomes eligible during the quiet window
  `[01:00, 05:00)` `America/Bahia` and D-1 has not been attempted for the
  current local date in this process (the scenario name preserves the
  historical timer-era title for traceability)
- **THEN** the in-process runtime requests recovery for the previous local
  calendar date
- **AND** selects exactly `discharges`, `admissions`, `deaths` and
  `official_census` in canonical order
- **AND** does not expose credentials in arguments, output or logs

#### Scenario: One extractor fails

- **WHEN** one selected extractor remains failed after configured command retries
- **THEN** the in-process step logs the aggregate failure without aborting
  the orchestrator loop
- **AND** successful extractor steps remain recorded
- **AND** health coverage exposes the failed date and extractor
- **AND** the orchestrator proceeds with the scheduled census cycle

#### Scenario: PDF command is not scheduled

- **WHEN** the D-1 step or catch-up runtime executes
- **THEN** it never invokes `process_discharge_pdf`

#### Scenario: Manual scheduler remains the fallback

- **WHEN** the operator needs a manual D-1 re-execution or catch-up
- **THEN** `exit-reconciliation-scheduler.sh` keeps working through the
  `recovery` profile one-shot runner
- **AND** advisory locks already prevent concurrent execution with the
  orchestrator step

#### Scenario: Date-only death closes overnight

- **WHEN** the recovered date has a date-only `DeathRecord` whose evidence
  uniquely matches one admission's known period at date granularity
- **THEN** the nightly step closes that admission on the death's local
  date with exit type `death` and the date-only precision marker
- **AND** the reconciliation event carries runtime provenance
- **AND** the step's log summary counts it as reconciled

#### Scenario: Ambiguous death stays pending in the nightly step

- **WHEN** the recovered date has a date-only `DeathRecord` that resolves
  to zero or multiple admissions
- **THEN** the nightly step writes nothing for that record
- **AND** counts it in the aggregate log summary
- **AND** the step still completes and emits the success marker

#### Scenario: Death step failure does not abort recovery

- **WHEN** an unexpected error affects one death record during the nightly
  step
- **THEN** the step logs the failure, processes the remaining records
- **AND** a total failure of the step never aborts the D-1 recovery or the
  orchestrator loop
- **AND** the success marker is emitted only when the step completes
