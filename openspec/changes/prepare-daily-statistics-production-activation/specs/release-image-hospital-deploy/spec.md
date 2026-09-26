## MODIFIED Requirements

### Requirement: Each release distributes its matching deployment assets

The system SHALL attach `compose.hospital.yml`, the version-specific upgrade
runbook, the exit-reconciliation scheduler, every supported systemd unit, and
the daily-statistics activation preflight while the GitHub release or
prerelease is still a draft. It MUST verify every required file before creating
the draft and SHALL make no asset mutation after publication.

#### Scenario: Operator installs without repository checkout

- **WHEN** the release workflow finishes successfully
- **THEN** the immutable release contains `compose.hospital.yml`,
  `<release-tag>-upgrade.md`, the exit-reconciliation scheduler, all supported
  services and timers including both daily-statistics units, and the activation
  preflight as downloadable assets
- **AND** the operator can deploy using those files, a host-local `.env` and
  Docker Compose
- **AND** no Git clone, source bind mount or Docker build is required
- **AND** the release tag and every attached asset cannot be changed after
  publication

#### Scenario: Required runtime asset is absent

- **WHEN** the exact tag lacks the activation preflight, either daily-statistics
  unit or another required deployment asset
- **THEN** the workflow stops before creating the draft release
- **AND** it does not publish an image or a partial set of deployment assets

#### Scenario: Draft contains the complete runtime set

- **WHEN** the workflow creates the draft release
- **THEN** all required deployment assets are attached in that draft operation
- **AND** image publication occurs only after the complete draft exists
- **AND** publication does not add or replace any asset
