# Production Worker Runtime IO Control Delta

## ADDED Requirements

### Requirement: Persistent worker storage is bounded

Production runtime guidance SHALL account for the persistent-session worker's
longer-lived Chromium browser profile, temporary files, and cache behavior. It
MUST also distinguish current non-rollout-ready status from future production
rollout guidance.

#### Scenario: Production rollout prerequisites are documented

- **WHEN** runtime guidance references persistent-session production workers
- **THEN** it states that production rollout is blocked until full-sync
  persistence and the real-handle container contract are resolved
- **AND** current examples are clearly marked as future rollout or lab/staging
  experiment guidance

#### Scenario: Persistent worker uses isolated volatile paths

- **WHEN** an operator deploys persistent-session workers after prerequisites
  are met
- **THEN** each worker process or container uses isolated temp/profile paths
- **AND** those paths are on bounded volatile storage when supported
- **AND** no mutable browser profile is shared by multiple worker processes

#### Scenario: Operator can tune browser lifecycle

- **WHEN** the persistent-session worker is deployed
- **THEN** operators can configure conservative browser/session lifecycle limits
- **AND** documented defaults favor stability over maximum reuse

#### Scenario: Operator can compare IO and memory impact

- **WHEN** current and persistent workers run side-by-side
- **THEN** guidance includes commands or queries to compare temporary storage,
  shared memory, RAM, swap, and Docker log growth for both groups
