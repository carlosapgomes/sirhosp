# Spec Delta: user-profile-self-service (ADDED)

## ADDED Requirements

### Requirement: Authenticated users can view their own profile

The portal SHALL provide a profile page at `/perfil/` that shows the
authenticated user's own identity (username, full name, e-mail, last
login, role) as read-only data.

#### Scenario: Anonymous access is redirected to login

- **WHEN** an anonymous request hits `/perfil/`
- **THEN** the response redirects to the login page

#### Scenario: Authenticated user sees own identity

- **WHEN** an authenticated user opens `/perfil/`
- **THEN** the page renders with their username and full name
- **AND** shows no editable identity fields

### Requirement: Users change their own password

The portal SHALL let authenticated users change their own password from
the profile page, requiring the current password and enforcing the
configured password validators, without terminating the current
session.

#### Scenario: Successful change keeps the session

- **WHEN** the user submits the current password and a valid new
  password
- **THEN** the new password authenticates on the next login
- **AND** the current session remains authenticated without re-login

#### Scenario: Wrong current password is rejected

- **WHEN** the submitted current password does not match
- **THEN** the response re-renders the form with a field error
- **AND** the stored password is unchanged

#### Scenario: Weak new password is rejected by validators

- **WHEN** the new password fails a configured password validator
- **THEN** the response re-renders the form with the validation error
- **AND** the stored password is unchanged

### Requirement: Provisional password forces a first-login change

A user flagged with a provisional password SHALL be redirected to the
profile page from any non-allowlisted path until the password is
changed; a successful change SHALL clear the flag.

#### Scenario: Flagged user is redirected away from the portal

- **WHEN** a flagged authenticated user requests `/painel/`
- **THEN** the response redirects to `/perfil/`

#### Scenario: Allowlisted paths remain reachable

- **WHEN** a flagged authenticated user requests an allowlisted path
  (`/perfil/`, `/login/`, `/logout/`, `/admin/`, `/static/`, `/health/`)
- **THEN** the request proceeds without the forced redirect

#### Scenario: Changing the password clears the flag

- **WHEN** a flagged user completes a successful password change
- **THEN** the provisional flag is cleared
- **AND** subsequent portal requests proceed without redirection

#### Scenario: Unflagged users are unaffected

- **WHEN** an authenticated user without the flag requests `/painel/`
- **THEN** the request proceeds without the forced redirect

### Requirement: Operators provision common users without choosing passwords

A management command SHALL create active common users (no staff, no
superuser) with a randomly generated provisional password printed
exactly once on stdout and the first-login flag set, and SHALL support
reissuing a provisional password for an existing user.

#### Scenario: Creating a common user

- **WHEN** the operator runs the create command for a new username
- **THEN** an active user exists without staff or superuser privileges
- **AND** stdout contains exactly one `temporary_password=<token>` line
- **AND** the user carries the first-login change flag
- **AND** the printed password authenticates the user

#### Scenario: Provisional password is not persisted in clear

- **WHEN** the create command finishes
- **THEN** the stored credential is only the hashed password
- **AND** no plaintext password is written to the database

#### Scenario: Reissuing a provisional password

- **WHEN** the operator runs the command in reset mode for an existing
  username
- **THEN** a new provisional password is printed once
- **AND** the first-login change flag is set again

#### Scenario: Duplicate username fails clearly

- **WHEN** the create command runs for an existing username
- **THEN** the command fails with an explicit error and no mutation
