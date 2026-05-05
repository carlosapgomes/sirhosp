# services-portal-navigation Specification

## ADDED Requirements

### Requirement: Admission summary CTA opens a configuration step

The system SHALL route admission summary actions through a configuration page
before enqueuing processing.

#### Scenario: Open summary configuration from admission page

- **WHEN** user clicks `Gerar resumo`, `Atualizar resumo`, or `Regenerar resumo`
  on admission context
- **THEN** user is redirected to a summary configuration page for that admission

### Requirement: Configuration page supports phase-2 model and prompt mode

The configuration step SHALL expose phase-2 model choice and prompt mode
(standard/custom).

#### Scenario: Submit standard configuration

- **WHEN** user submits with standard prompt mode
- **THEN** a queued summary run is created with selected phase-2 option

#### Scenario: Submit custom prompt configuration

- **WHEN** user submits with custom prompt mode and valid text
- **THEN** a queued summary run is created with custom prompt snapshot

#### Scenario: Prompt selector includes default and custom options

- **WHEN** user opens configuration page
- **THEN** user sees prompt padrão (origem: arquivo versionado)
- **AND** sees prompts customizados disponíveis para reutilização
- **AND** can choose one custom prompt as execution input

### Requirement: Prompt library CRUD is available to authenticated users

The system SHALL provide a dedicated prompt management page with CRUD
operations and visibility rules.

#### Scenario: Owner manages own prompts

- **WHEN** authenticated user opens prompt library page
- **THEN** user can create, edit, and delete own prompts
- **AND** title is required when creating or updating prompt

#### Scenario: Non-owner cannot modify third-party prompt

- **WHEN** authenticated user tries to edit or delete prompt owned by another
  user
- **THEN** operation is denied by access control

### Requirement: Summarization logs are visible in two permission levels

The system SHALL provide public operational logs for authenticated users and a
restricted sensitive log view for administrators.

#### Scenario: Public logs list operational usage

- **WHEN** authenticated non-admin user opens summary logs page
- **THEN** user sees run-level and phase-level operational metadata
- **AND** user does not see prompt or payload/response content

#### Scenario: Admin logs include sensitive call details

- **WHEN** admin opens summary logs admin page
- **THEN** admin sees all public metadata
- **AND** sees prompt snapshot and full request/response payloads per call
