## RENAMED Requirements

- FROM: `### Requirement: Current-day discharge extraction is hourly and benchmark-gated`
- TO: `### Requirement: Current-day discharge extraction runs in the orchestrator loop`

## MODIFIED Requirements

### Requirement: Current-day discharge extraction runs in the orchestrator loop

Production SHALL run the current-day discharge extraction
(`run_exit_reconciliation_runtime --mode hourly`) inside the adaptive
census orchestrator loop, throttled to at most once per
`America/Bahia` local hour per process, whenever the loop is eligible
(queue drained, no open census batch). The systemd calendar timer is no
longer the primary scheduling path and MUST remain disabled by default;
the benchmark gate that historically guarded timer activation is preserved
as the deployment precondition for enabling the orchestrator step, and
the manual scheduler remains the documented fallback.

#### Scenario: Benchmark is not approved

- **WHEN** the orchestrator step is deployed before benchmark approval
  documented in the activation evidence
- **THEN** hourly extraction is not considered activated until the
  operator records the approval, using the manual scheduler meanwhile
- **AND** existing extraction remains available for controlled operation

#### Scenario: Benchmark is approved

- **WHEN** documented source latency, error rate, database duration and queue
  thresholds pass
- **THEN** the operator may consider the orchestrator intraday step
  activated and keep the fallback timer disabled by default (it may be
  re-enabled as the documented manual path, e.g. while the orchestrator
  is stopped for maintenance)

#### Scenario: Historical catch-up benchmark is not approved

- **WHEN** D-1 smoke testing passed but the bounded multi-date benchmark did not
  validate up to seven dates across four extractors
- **THEN** automatic scheduling is limited to D-1 and intraday hourly
- **AND** multi-date catch-up requires explicit operator execution

#### Scenario: Hourly extraction succeeds

- **WHEN** an eligible loop iteration runs the intraday step in a new
  local hour
- **THEN** it runs the current-day discharge service in-process through
  the orchestrator container
- **AND** reconciliation eligible from the report can complete within one hour
  of the record becoming available in the legacy report
