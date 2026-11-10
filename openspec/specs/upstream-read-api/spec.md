# upstream-read-api Specification

## Purpose

Expose the current inpatient census photo and patient demographics as an
authenticated read-only JSON API for internal upstream consumers, with
standardized errors and access logs free of clinical data.

## Requirements

### Requirement: Upstream API requires Bearer authentication

Every `/api/v1/` endpoint SHALL require `Authorization: Bearer <token>` and
compare the presented token against the configured upstream token in constant
time. Missing, malformed or unknown credentials MUST yield `401` with the
standard error body. When the upstream token is not configured, every
`/api/v1/` request MUST yield `500` with error code `internal_error`,
taking precedence over the `401` cases.

#### Scenario: Unconfigured token fails closed with precedence

- **WHEN** the upstream token setting is empty and a client calls any
  `/api/v1/` endpoint with absent, malformed or supplied credentials
- **THEN** the system responds `500` with error code `internal_error`

#### Scenario: Request without credentials is rejected

- **WHEN** the upstream token is configured and a client calls any
  `/api/v1/` endpoint without an `Authorization` header
- **THEN** the system responds `401` with error code `unauthorized`

#### Scenario: Request with wrong token is rejected

- **WHEN** the upstream token is configured and a client calls any
  `/api/v1/` endpoint with an unknown Bearer token
- **THEN** the system responds `401` with error code `unauthorized`

### Requirement: Current inpatients photo lists patients of the latest cycle

`GET /api/v1/inpatients/current` SHALL return `{captured_at, row_count,
patients}` for the latest eligible cycle. Runs order by minimum row
`captured_at` descending, then run primary key descending; rows order by
`setor`, `setor_codigo`, `leito`, `prontuario`, then row primary key
ascending. It lists patient rows only (non-empty `prontuario`);
`captured_at` is the photo identity used by consumers for deduplication.

#### Scenario: Consumer polls the current photo

- **WHEN** an authenticated client calls `GET /api/v1/inpatients/current`
- **THEN** the system responds `200` with the photo `captured_at`, a
  `row_count` equal to the number of returned patients, and one entry per
  inpatient of the latest completed cycle

#### Scenario: Consumer re-polls an unchanged photo

- **WHEN** an authenticated client polls again before a new cycle completes
- **THEN** the system responds `200` with the same `captured_at` and an
  identical payload

#### Scenario: Runs sharing a capture timestamp resolve deterministically

- **WHEN** two completed runs share one `captured_at`
- **THEN** the system serves the run with the greater primary key and
  never mixes rows from both

#### Scenario: Capture order wins over finish order

- **WHEN** one run captured earlier but finished later than another run
- **THEN** the system serves the run with the greater minimum row
  `captured_at`, ignoring `finished_at`

#### Scenario: Duplicate row keys order by primary key

- **WHEN** two rows share `setor`, `setor_codigo`, `leito` and
  `prontuario`
- **THEN** the row with the smaller primary key comes first, stably
  across polls

### Requirement: Cycle sequence orders photos totally

The photo SHALL include `cycle_seq`, the strictly increasing sequence
number of the served cycle (its run primary key as a JSON integer).
Consumers MAY order and deduplicate photos by (`captured_at`,
`cycle_seq`); equal pairs MUST be treated as the same photo.

#### Scenario: Distinct cycles share a captured_at

- **WHEN** two served photos share one `captured_at`
- **THEN** the later photo carries the greater `cycle_seq`

#### Scenario: Repeated poll keeps the same identity

- **WHEN** a client polls twice with no new completed cycle
- **THEN** both responses carry identical `captured_at` and `cycle_seq`

### Requirement: Photo exposes only completed cycles

The photo SHALL always correspond integrally to one census cycle whose run
has `status = succeeded` and holds at least one snapshot row. Rows from
`queued`, `running` or `failed` runs MUST never appear; every row of the
photo MUST share the photo `captured_at`.

#### Scenario: Poll during an ongoing extraction cycle

- **WHEN** an authenticated client polls while a new census cycle is still
  `running`
- **THEN** the system returns the previous completed photo, never a partial
  mix of cycles

#### Scenario: Latest cycle failed

- **WHEN** the most recent census cycle ended as `failed`
- **THEN** the system returns the latest `succeeded` photo instead of the
  failed cycle

### Requirement: Empty census photo is a valid response

A completed cycle with zero patients SHALL be served as `200` with
`patients: []` and `row_count: 0`, distinguishable from an error.

#### Scenario: Completed cycle without inpatients

- **WHEN** the latest completed cycle contains no patient rows
- **THEN** the system responds `200` with an empty `patients` array and
  `row_count` zero

### Requirement: Missing photo answers not found

When no succeeded census cycle with snapshot rows exists, the photo
endpoint SHALL respond `404` with error code `no_snapshot` instead of an
empty photo, so consumers never mistake absence of data for an empty
census.

#### Scenario: No completed cycle exists yet

- **WHEN** an authenticated client polls before any eligible cycle exists
- **THEN** the system responds `404` with error code `no_snapshot`

### Requirement: Patient rows carry the census identity contract

Each photo entry SHALL include `setor_codigo`, `setor`, `leito`,
`prontuario`, `nome`, `bed_status`, `especialidade`,
`source_admission_at` and `source_movement_at`. Sector identity is the pair
(`setor_codigo`, `setor`); `leito` may be empty; patient `nome` MUST be
non-empty; `bed_status` MUST be within the occupancy enum.

#### Scenario: Sectors share the same source code

- **WHEN** the photo contains distinct sectors reusing one `setor_codigo`
- **THEN** each (`setor_codigo`, `setor`) pair remains a distinct entry and
  rows are never collapsed by code alone

#### Scenario: Patient without a bed assignment

- **WHEN** the source lists a patient with no bed
- **THEN** the entry keeps the non-empty `prontuario` and `nome` with an
  empty `leito`

### Requirement: Invalid patient rows fail the photo closed

A photo containing a patient row (non-empty `prontuario`) with an empty
`nome` SHALL be refused with `500` and error code `internal_error`. The
system MUST NOT omit the row or invent a name.

#### Scenario: Source row lacks the patient name

- **WHEN** the latest completed cycle holds a patient row with an empty
  `nome`
- **THEN** the photo endpoint responds `500` with error code
  `internal_error`

### Requirement: Source timestamps keep minute precision or null

`source_admission_at` and `source_movement_at` SHALL carry the real
source timestamp with minute precision when the source informed the time,
and `null` otherwise. The system MUST never fabricate midnight or any
other default time.

#### Scenario: Source informed only the admission date

- **WHEN** a patient row has a date-only admission value from the source
- **THEN** the entry exposes `source_admission_at: null`

### Requirement: Timestamps use explicit offsets

Every timestamp in API responses SHALL be ISO 8601 with an explicit offset
(`Z` or `±HH:MM`); civil dates SHALL be `YYYY-MM-DD`. Naive timestamps
MUST never be emitted.

#### Scenario: Photo and demographics carry zoned timestamps

- **WHEN** an authenticated client reads the photo or a demographic record
- **THEN** every timestamp includes an explicit offset and `date_of_birth`
  is `YYYY-MM-DD` or `null`

### Requirement: Demographics mirror the patient record

`GET /api/v1/patients/{prontuario}` SHALL resolve `patient_source_key`
within `source_system "tasy"`, echo the queried `prontuario`, and return
the exact shape: scalar fields verbatim; `phones` as
`{home, cellular, contact}` from the three phone columns; `address` as
`{street, number, complement, neighborhood, city, state, postal_code}`
from the matching columns; plus `updated_at` for refresh decisions.

#### Scenario: Known patient demographics are returned

- **WHEN** an authenticated client requests an existing `prontuario`
- **THEN** the system responds `200` with the record above and absent
  strings as empty strings

#### Scenario: Unknown prontuario is not found

- **WHEN** an authenticated client requests a `prontuario` with no patient
- **THEN** the system responds `404` with error code `patient_not_found`

#### Scenario: Nested objects map from flat columns

- **WHEN** an authenticated client requests an existing `prontuario`
- **THEN** each `phones` and `address` key equals its stored column value,
  with absent strings preserved as empty strings

### Requirement: Demographic responses carry exactly the allowlisted keys

Responses SHALL contain exactly these top-level keys: `prontuario`,
`name`, `social_name`, `date_of_birth`, `gender`, `gender_identity`,
`mother_name`, `father_name`, `race_color`, `birthplace`, `nationality`,
`marital_status`, `education_level`, `profession`, `cns`, `cpf`,
`phones`, `address`, `updated_at`. No model-internal field (`id`,
`source_system`, `created_at`) MUST appear.

#### Scenario: Response key set is exact

- **WHEN** an authenticated client requests an existing `prontuario`
- **THEN** the response holds exactly the allowlisted keys with values
  from the mapped columns

### Requirement: API errors use a standard envelope

Error responses SHALL use
`{"error": {"code": "<code>", "message": "<message>"}}` with `401`
`unauthorized`, `404` `patient_not_found` or `no_snapshot`, `400`
`bad_request` and `500` `internal_error`. Server errors MUST NOT leak stack
traces or internals;
responses MUST carry `Cache-Control: no-store`.

#### Scenario: Unexpected failure stays generic

- **WHEN** an authenticated request triggers an internal failure
- **THEN** the system responds `500` with error code `internal_error` and
  no stack trace

### Requirement: Access logs carry no clinical data

Access and application logging for `/api/v1/` SHALL record method,
sanitized route and status only. Every `/api/v1/*` request target,
including query strings and unmatched or malformed paths, MUST be reduced
to a fixed route pattern before logging. Every emitted record MUST be
sanitized; an error record MAY be absent under suppression, but MUST
never carry raw data or identifiers.

#### Scenario: Demographics request is logged sanitized

- **WHEN** an authenticated client requests one patient demographic record
- **THEN** the access log entry contains no name or `prontuario` and keeps
  method, sanitized route and status

#### Scenario: Query strings and unknown API paths stay sanitized

- **WHEN** requests hit `/api/v1/` paths carrying a query string or an
  unmatched route
- **THEN** the access entries keep method, sanitized route and status with
  no raw path, query or identifier

#### Scenario: Framework error output stays sanitized

- **WHEN** an `/api/v1/` request fails outside the view (unknown route,
  malformed request, or forced server error)
- **THEN** every emitted access or error record keeps method, sanitized
  route and status with no raw target, query or identifier, and any
  suppressed error record is proven absent

### Requirement: Upstream reads never mutate server state

All `/api/v1/` endpoints SHALL be side-effect free. Repeating any `GET`
against an unchanged database MUST return an identical payload and MUST
NOT create, update or delete any row.

#### Scenario: Repeated reads are identical and side-effect free

- **WHEN** an authenticated client repeats the same `GET` without an
  intervening write
- **THEN** the system returns a byte-identical payload and persists nothing
