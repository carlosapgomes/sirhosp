# Tasks

## Slices

- S1 — App isolado, auth, foto de internados e logging sanitizado — Contract: `slices/slice-001-photo-endpoint.md` (tasks 1.1–1.4, 2.1–2.3, 3.1–3.2)
- S2 — Demografia por prontuário — Contract: `slices/slice-002-demographics-endpoint.md` (tasks 4.1–4.2)
- S3 — Documentação do consumidor e aceite do contrato — Contract: `slices/slice-003-consumer-docs-acceptance.md` (tasks 5.1–5.2, 6.1)
- S4 — Campo de sequência do ciclo v1.1 (aditivo) — Contract: `slices/slice-004-cycle-sequence-field.md` (tasks 7.1–7.2)
- Final gate (item 6.2) é dever do controller após todos os slices aceitos, conforme `AGENTS.md` §12 — não é slice de worker.

## 1. App scaffold, auth and error envelope

Slice: S1 — Contract: `slices/slice-001-photo-endpoint.md`

- [x] 1.1 Create the isolated Django app with `/api/v1/` URL wiring, wire `SIRHOSP_UPSTREAM_API_TOKEN` into the `compose.prod.yml` web environment and the `compose.hospital.yml` shared app environment, and verify `./scripts/test-in-container.sh check` passes with the new routes registered
- [x] 1.2 Implement the Bearer token setting with fail-closed behavior (`500` taking precedence over every `401` case when unconfigured) and constant-time comparison, and verify unit tests cover the full matrix of missing, malformed and supplied credentials combined with missing and present settings
- [x] 1.3 Implement the shared JSON error envelope (`401`/`404` including `no_snapshot`/`400`/`500`) with `Cache-Control: no-store` and verify unit tests assert the exact body shape and the absence of stack traces
- [x] 1.4 Exempt `/api/v1/` from browser-oriented middleware (`csrf_exempt` on API views plus the password-change allowlist entry) and verify tests through the real middleware stack prove unauthenticated unsafe requests answer `401`, authenticated ones answer `405`, and portal protections stay intact

## 2. Current inpatients photo endpoint

Slice: S1 — Contract: `slices/slice-001-photo-endpoint.md`

- [x] 2.1 Implement the latest-eligible-run photo query (run with `intent = census_extraction`, `status = succeeded` and at least one snapshot row, ordered by minimum row `captured_at` descending then run primary key descending) and verify unit tests prove `running`/`failed` cycles, rowless runs and null-run rows never surface, capture order wins over finish order, and `captured_at` ties resolve by primary key
- [x] 2.2 Implement `GET /api/v1/inpatients/current` serializing the 1:1 census row contract ordered by `setor`, `setor_codigo`, `leito`, `prontuario` then row primary key ascending, with invalid patient rows (empty `nome`) failing the whole photo with `500`, and verify integration tests assert field presence, patient-only default, sector-pair identity, empty `leito` handling, duplicate-key ordering stability and offset timestamps
- [x] 2.3 Cover photo edge cases (empty photo returns `200` with `patients: []`, missing photo returns `404 no_snapshot`, repeated polls return identical payloads) and verify the new tests pass via `./scripts/test-in-container.sh unit`

## 3. Sanitized logging (R8)

Slice: S1 — Contract: `slices/slice-001-photo-endpoint.md`

- [x] 3.1 Implement the gunicorn logger sanitizer that reduces every `/api/v1/*` request target (matched routes, unmatched or malformed paths, any query string) to a fixed route pattern, and verify unit tests assert no raw path, query, name or `prontuario` survives in the emitted line
- [x] 3.2 Wire the sanitizer into the gunicorn config and application logging, and verify in-container that real photo, query-string, unknown-path, malformed-request and forced-error requests each produce an access record with method, sanitized route and status only, with error output sanitized or proven absent under suppression and no raw target, query or identifier in any emitted record

## 4. Patient demographics endpoint

Slice: S2 — Contract: `slices/slice-002-demographics-endpoint.md`

- [x] 4.1 Implement `GET /api/v1/patients/{prontuario}` resolving `patient_source_key` within `source_system "tasy"` and returning exactly the allowlisted key set with the specified column mapping, and verify integration tests assert every mapped value plus `updated_at` and reject any extra or missing top-level key
- [x] 4.2 Cover unknown `prontuario` (`404 patient_not_found`) and invalid-method handling, and verify the new tests pass via `./scripts/test-in-container.sh integration`

## 5. Consumer documentation

Slice: S3 — Contract: `slices/slice-003-consumer-docs-acceptance.md`

- [x] 5.1 Document the two endpoints with `curl`/Python examples, the polling and dedup algorithm (`captured_at` identity plus tie-break and `no_snapshot` semantics), error codes and the token rotation runbook, and verify every documented command runs as written against a containerized dev instance
- [x] 5.2 Record the operational contract (internal network only with per-compose verification: hospital via restricted `SIRHOSP_BIND_ADDRESS`, generic prod via operator-owned firewall or reverse proxy with reachability probe; additive-fields discipline; 4–6 h use-case scope and accepted polling gaps) and verify `./scripts/markdown-lint.sh` passes on all touched `.md` files

## 7. Cycle sequence field (v1.1, additive)

Slice: S4 — Contract: `slices/slice-004-cycle-sequence-field.md`

- [x] 7.1 Expose `cycle_seq` (served run primary key as JSON integer) in the photo payload with unit and integration tests proving presence, integer type, equality with the served run and distinct values across same-`captured_at` cycles, and verify via `./scripts/test-in-container.sh unit`
- [x] 7.2 Update `docs/upstream-api.md` payload examples and dedup guidance for `cycle_seq`, re-run the affected documented blocks as written in a containerized dev instance, and verify `./scripts/markdown-lint.sh` passes

## 6. Final integration gate

Item 6.1 → Slice S3 (`slices/slice-003-consumer-docs-acceptance.md`). Item 6.2 → controller final gate (`AGENTS.md` §12), executado pelo controller após todos os slices aceitos.

- [x] 6.1 Execute the contract acceptance checklist end to end (auth and fail-closed precedence, middleware boundary, exact run and row ordering, atomicity during an ongoing cycle, empty and missing photos, invalid-row fail-closed, midnight rule, sector identity, offsets, sanitized access output and sanitized-or-absent error output including query strings, unknown paths, malformed requests and forced errors, exact demographic key set, idempotent repeats) and verify each item has linked evidence
- [x] 6.2 Run `./scripts/test-in-container.sh quality-gate` plus `./scripts/test-in-container.sh integration` on the final state and verify both pass with no pending human decision
