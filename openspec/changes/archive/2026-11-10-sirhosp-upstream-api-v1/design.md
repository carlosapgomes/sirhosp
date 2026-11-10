# Design

## Context

See `proposal.md` for motivation. Current state shaping this design:

- `CensusSnapshot` has a single writer
  (`apps/census/management/commands/extract_census.py`), which persists all
  rows of a cycle plus the `succeeded` run transition inside one
  `transaction.atomic()` block. Readers can never observe a half-persisted
  cycle, but the portal (`/beds/`) resolves the photo via bare
  `Max("captured_at")` without checking run status.
- `CensusSnapshot.ingestion_run` is a nullable FK to `IngestionRun`, whose
  `status` cycles through `queued`/`running`/`succeeded`/`failed` across many
  intents (`census_extraction`, `admissions_only`, `demographics_only`,
  `full_sync`, `official_census_extraction`, ...).
- `Patient` holds all demographic fields with `""` for absent strings and
  `NULL` only where the column is nullable (`date_of_birth`); `gender` stores
  free Portuguese text (`"Masculino"`, `"Feminino"`, ...).
- There is no machine-auth infrastructure; the portal uses Django session
  auth. Serving runs under gunicorn via `docker/gunicorn-wrapper.sh` with
  default access logging (full request path).
- `TIME_ZONE = America/Bahia`, `USE_TZ = True`: Django datetimes serialize
  with an explicit offset via `isoformat()`.

## Goals / Non-Goals

**Goals:**

- Read-only JSON surface with zero business transformation (1:1 mirror).
- Atomicity by construction: the photo always equals one completed cycle.
- Auth and logging that fail closed and leak no clinical data.
- Zero changes to extraction, existing models, portal behavior, workers
  and infra design (bounded additions only: one middleware allowlist
  entry, one env var per compose file, one logger class).

**Non-Goals:**

- No generic API framework, versioning machinery or SDK generation.
- No pagination, filtering or query language beyond the two fixed reads.
- No persistence of API usage, audit trail table or per-consumer quotas.

## Decisions

### D1 — Isolated app owns the upstream surface

Create one new app (e.g. `apps/upstream_api/`) holding URLs, views,
authentication helper, error envelope and tests. Alternative (views spread
across `apps/census` and `apps/patients`) was rejected: a single reviewable
boundary keeps portal session auth decoupled from machine auth, makes the
PHI-export surface explicit, and lets future versions grow without touching
clinical apps.

### D2 — Django puro, sem DRF ou django-ninja

Two fixed `JsonResponse` views with a decorator need no serializer,
renderer or router machinery. This honors the AGENTS.md rule against heavy
dependencies without an explicit ADR and keeps the dependency footprint at
zero. Revisit only if the surface grows query/pagination needs.

### D3 — Photo resolved by latest succeeded run, not by bare Max

The photo query resolves the latest `IngestionRun` with
`intent = census_extraction`, `status = succeeded` and at least one
`CensusSnapshot` row, ordered by minimum row `captured_at` descending and
then run primary key descending, then reads rows by that
`ingestion_run_id` ordered by `setor`, `setor_codigo`, `leito`,
`prontuario` and then row primary key, all ascending.
`IngestionRun.finished_at` is deliberately not used: it is nullable and
records processing end, while the photo identity is capture time. The
served run's primary key is additionally exposed as `cycle_seq` (JSON
integer, v1.1 additive field requested by the hgproxy consumer), giving a
wall-clock-independent total order key: equal (`captured_at`, `cycle_seq`)
pairs denote the same photo. This is defense in depth over the
already-atomic persistence: it excludes `running`/`failed` rows by
construction, ignores legacy rows with a null run, and cannot merge two
cycles even under a theoretical `captured_at` collision. Bare
`Max("captured_at")` (the `/beds/` approach) stays a portal detail and is
not reused here. Residual risk: two distinct runs sharing one
`captured_at` would make the consumer no-op the second photo; with
microsecond timestamps and hour-long cycles this is accepted as
negligible, and the run tie-break keeps serving deterministic. When no
eligible run exists, the endpoint answers `404 no_snapshot` (never an
empty photo), so absence of data is distinguishable from an empty census.

### D4 — Faithful 1:1 mirroring, normalization left to the consumer

The API serializes model values verbatim: empty strings stay empty strings,
`NULL` stays `null`, `gender` stays free Portuguese text. Rationale: every
transformation is a bug and drift surface; contract v2 explicitly assigns
normalization (`male`/`female` enum, phone lists, absence mapping) to the
consumer, which already implements it. The only structural mapping is the
exact wire shape required by contract v2, resolved within
`source_system "tasy"` (the sole source the pipeline writes):

| Wire key                                                                                       | Model column                                                                                           |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `prontuario`                                                                                   | echo of the queried `patient_source_key`                                                               |
| `name`                                                                                         | `Patient.name`                                                                                         |
| `social_name`                                                                                  | `Patient.social_name`                                                                                  |
| `date_of_birth`                                                                                | `Patient.date_of_birth`                                                                                |
| `gender`                                                                                       | `Patient.gender`                                                                                       |
| `gender_identity`                                                                              | `Patient.gender_identity`                                                                              |
| `mother_name`                                                                                  | `Patient.mother_name`                                                                                  |
| `father_name`                                                                                  | `Patient.father_name`                                                                                  |
| `race_color`                                                                                   | `Patient.race_color`                                                                                   |
| `birthplace`                                                                                   | `Patient.birthplace`                                                                                   |
| `nationality`                                                                                  | `Patient.nationality`                                                                                  |
| `marital_status`                                                                               | `Patient.marital_status`                                                                               |
| `education_level`                                                                              | `Patient.education_level`                                                                              |
| `profession`                                                                                   | `Patient.profession`                                                                                   |
| `cns`                                                                                          | `Patient.cns`                                                                                          |
| `cpf`                                                                                          | `Patient.cpf`                                                                                          |
| `phones.home` / `phones.cellular` / `phones.contact`                                           | `phone_home` / `phone_cellular` / `phone_contact`                                                      |
| `address.street` / `number` / `complement` / `neighborhood` / `city` / `state` / `postal_code` | `street` / `address_number` / `address_complement` / `neighborhood` / `city` / `state` / `postal_code` |
| `updated_at`                                                                                   | `Patient.updated_at`                                                                                   |

Never emitted: `id`, `source_system`, `created_at`, `patient_source_key`
as such (it only appears as the `prontuario` echo).

### D5 — Static Bearer token with fail-closed semantics

Setting `SIRHOSP_UPSTREAM_API_TOKEN` (env-backed, minimum 32 random bytes),
compared with `secrets.compare_digest` against the
`Authorization: Bearer <token>` header. Alternatives rejected: Django
session auth (browser-oriented, CSRF-bound), database token tables
(migration + admin surface for one consumer), OAuth2 client credentials
(operational overkill for same-host server-to-server). If the setting is
absent or empty, every `/api/v1/` request fails closed (`500`
`internal_error`, never an open gate), so a misconfigured deploy cannot
silently serve PHI unauthenticated; this takes precedence over the `401`
cases (a request with both a missing setting and a missing header answers
`500`). The variable is wired into the enumerated environments of both
`compose.prod.yml` (web service) and `compose.hospital.yml` (shared
app environment), since host `.env` alone does not reach the container.

### D6 — Sanitized access logging (R8, option 1)

Two layers: (a) API application code logs method, route pattern and status
only, never parameters, query strings or bodies; (b) a small custom
gunicorn logger class reduces every `/api/v1/*` request target — matched
routes, unmatched or malformed paths, and any query string — to a fixed
route pattern before emitting the access line (e.g. any demographics path
becomes one constant; query strings are dropped entirely). Alternative
(document-and-accept identifiers in the access log) was rejected by
explicit operator decision. Framework error output is enforced, not assumed: the slice proves with
containerized tests that unknown-route 404s, malformed requests and
forced view failures emit sanitized access output. If the deployed stack
is found to log raw targets on any error path, the slice wires
suppression or sanitization there instead of documenting an assumption.
Contract rule: every emitted access or error record MUST be sanitized;
an access record is expected for every request, while an error record
MAY be absent when suppression is the chosen protection — absence is
then proven by the containerized tests, and no emitted record ever
carries raw data. The dev server stays out of scope (synthetic data only); any
external proxy in front of gunicorn is the operator's documented
responsibility. This turns "no PHI in logs" into structural enforcement
rather than reviewer memory.

### D7 — Fixed response conventions

`application/json; charset=utf-8`, `Cache-Control: no-store`, ISO 8601 with
offset for datetimes, `YYYY-MM-DD` for civil dates, and the single error
envelope `{"error": {"code", "message"}}`. `no-store` matches the consumer
side and prevents intermediary caching of PHI.

### D8 — No rate limiting in v1

Expected load is one photo poll per 2 h plus dozens of demographic reads
per day over an internal link. Throttling machinery would be speculative
tooling; revisit if a second consumer or abusive pattern appears.

### D9 — API bypasses browser-oriented middleware

API views are exempt from `CsrfViewMiddleware` (`csrf_exempt`, the standard
Django pattern for token-authenticated APIs) so an unauthenticated unsafe
request still answers `401` and an authenticated one answers `405` instead
of Django's `403`. The `/api/v1/` prefix joins the allowlist of
`RequirePasswordChangeMiddleware` (same precedent as `/health/` and
`/admin/`), so a flagged portal session can never redirect a machine call.
Portal protections stay intact: the exemptions are path-scoped to the API
and covered by tests through the real middleware stack.

### D10 — Invalid source rows fail the photo closed

The pipeline permits a `CensusSnapshot` row with a non-empty `prontuario`
and an empty `nome`, which the external contract forbids. The API refuses
the whole photo with `500 internal_error` in that case: omitting the row
would silently corrupt the consumer roster, and inventing a name is
forbidden. One bad row failing the photo is the intended fail-closed
trade-off; the generic error triggers operator attention without leaking
which row is bad.

## Risks / Trade-offs

- [Token rotation needs a restart] → Mitigation: single consumer and
  documented rotation runbook (new token, restart, confirm `401` on old).
  No silent dual-token window in v1 by design.
- [Polling gap hides short stays and missed photos] → Accepted by contract
  v2 for the 4–6 h laboratory use case; `captured_at` lets the consumer
  detect staleness explicitly.
- [Gunicorn logger only provable in container] → Mitigation: unit test the
  sanitizer plus an integration check of the emitted access line via the
  containerized gate, not host-only runs.
- [One invalid source row fails the whole photo] → Accepted D10 trade-off:
  a loud generic `500` beats a silently corrupt roster; source rows are
  otherwise validated by the existing extraction gates.
- [Middleware exemptions could drift] → Mitigation: path-scoped
  exemptions with tests through the real stack; portal CSRF and password
  enforcement keep their own suites green.
- [New PHI egress to a second system] → Mitigation: internal network,
  long token, `no-store`, sanitized logs, additive-only contract
  discipline (new fields require a new change).

## Migration Plan

- Deploy is additive: with the setting absent the endpoints fail closed,
  so code can ship before the token exists.
- Go-live: operator generates the token, stores it in the deploy env
  (consumed via the new compose entries), delivers it to the consumer team
  out of band, and verifies with the documented `curl` probes (`401`
  without token, `200` with token) plus the per-compose network check:
  hospital compose via restricted `SIRHOSP_BIND_ADDRESS`, generic prod
  compose via operator-owned firewall or reverse proxy with a reachability
  probe.
- Rollback: unset the env (fail closed) or revert the change; no data
  migration exists in either direction.
- Consumer onboarding doc ships in the same change with example requests
  and the polling/dedup algorithm.
