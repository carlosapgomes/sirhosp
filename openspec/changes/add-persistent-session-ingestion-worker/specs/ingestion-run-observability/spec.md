# Ingestion Run Observability Delta

## ADDED Requirements

### Requirement: Worker groups are distinguishable

Ingestion run observability SHALL allow operators to distinguish runs processed
by the current worker group from runs processed by the persistent-session worker
group without exposing patient data or credentials.

#### Scenario: Persistent label identifies group

- **WHEN** a persistent-session worker claims a queued `IngestionRun`
- **THEN** the persisted `worker_label` identifies the persistent worker group
- **AND** the label uses configured `SIRHOSP_WORKER_LABEL` or a safe default
- **AND** the label may include a safe process-level suffix
- **AND** the label contains no patient data, clinical text, cookies or secrets

#### Scenario: Side-by-side metrics can be grouped

- **WHEN** both worker groups process runs concurrently
- **THEN** operators can group completed runs by label prefix or group label
- **AND** compare run count, success rate, failure rate, timeout rate, queue
  latency, and processing duration between groups

### Requirement: Persistent worker preserves heartbeat

The persistent-session worker SHALL provide worker heartbeat behavior equivalent
to the current ingestion worker for claimed runs.

#### Scenario: Heartbeat is populated on claim

- **WHEN** the persistent-session worker claims a queued run
- **THEN** `worker_heartbeat_at` is populated near processing start time
- **AND** `worker_label` is populated with a safe operational identifier

#### Scenario: Heartbeat refreshes during processing

- **WHEN** the persistent-session worker is processing a run
- **THEN** it refreshes `worker_heartbeat_at` periodically until terminal state
  or processing exit
- **AND** stale-run recovery can use the heartbeat timestamp without container
  or browser process access
