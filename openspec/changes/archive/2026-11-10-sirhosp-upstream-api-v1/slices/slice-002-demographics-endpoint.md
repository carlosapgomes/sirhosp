# Slice UPA-002 — Demografia por prontuário

## Identity

- Change: `sirhosp-upstream-api-v1`.
- Slice: `UPA-002`.
- Tasks: grupo 4 de `tasks.md` (itens 4.1–4.2).
- Depende de: UPA-001 aceito (auth, envelope e logging sanitizado já
  protegem a URL com PHI antes de ela existir).

## Objective

Entregar `GET /api/v1/patients/{prontuario}` reutilizando auth, envelope
e logging do slice anterior, com o mapeamento wire exato e o key-set
allowlisted do contrato.

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/sirhosp-upstream-api-v1/proposal.md`.
- `openspec/changes/sirhosp-upstream-api-v1/design.md` (D4, D5, D7, D9).
- `openspec/changes/sirhosp-upstream-api-v1/specs/upstream-read-api/spec.md`.
- `apps/upstream_api/` de UPA-001 (auth, envelope, urls, logger).
- `apps/patients/models.py` (`Patient`: todos os campos demográficos).

Follow the repository engineering policy in `AGENTS.md` and preserve existing
conventions. Prefer the smallest correct change; avoid speculative
abstraction and unrelated refactoring.

## Requirements

| ID  | Requisito                                                                                                                                                                                                                                                         | Evidência planejada                                                                 |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| R1  | Demografia resolve `patient_source_key` em `source_system "tasy"`, com echo do `prontuario`, escalares verbatim pela tabela D4, `phones`/`address` aninhados, `date_of_birth` `YYYY-MM-DD`, `""` preservado, `null` só onde nullable, e `updated_at` para refresh | Integration do payload completo campo a campo                                       |
| R2  | Resposta contém exatamente as 19 chaves allowlisted, sem `id`, `source_system`, `created_at` ou qualquer extra                                                                                                                                                    | Integration de key-set exato (rejeita extra e falta)                                |
| R3  | Prontuário inexistente retorna `404` com `patient_not_found` no envelope                                                                                                                                                                                          | Integration do 404                                                                  |
| R4  | Auth, envelope e logging de UPA-001 reutilizados sem duplicação; método não-GET autenticado retorna `405`, não autenticado retorna `401`; linha de access log da demografia sai sanitizada                                                                        | Integration de método + teste de não-duplicação por inspeção + access log capturado |

## Expected blast radius

Superfícies esperadas:

- `apps/upstream_api/` (view, serialização pelo mapeamento D4, rota — só
  adição).
- `tests/unit/test_upstream_*.py` e `tests/integration/test_upstream_*.py`
  (extensão).

Superfícies sensíveis / fora de escopo sem escalada:

- Comportamento de UPA-001 (foto, auth, envelope, logger): reutilizar,
  não alterar.
- `apps/patients` (leitura via ORM apenas), migrations, extração, portal,
  middlewares, composes, gunicorn/docker.
- Normalização de valores (`gender`, telefones, `""` → ausência) é do
  consumidor, por contrato.

Arquivo adicional só com justificativa no relatório.

## Failing-before plan

1. Teste que chama `GET /api/v1/patients/0000001` autenticado falha
   (rota não existe).
2. Teste de `404` para prontuário inexistente falha (rota não existe).
3. Teste de método não-GET falha (rota não existe).
4. Teste do mapeamento aninhado `phones`/`address` e do key-set exato
   falha (serialização não existe).

## Implementation constraints

- Reutilizar o decorator/helper de auth, o envelope e o logger de UPA-001;
  qualquer divergência de comportamento entre endpoints é bug.
- Lookup restrito a `source_system "tasy"`; serialização verbatim pelo
  mapeamento D4 com exatamente as 19 chaves, sem mapear `""` para `null`
  nem normalizar texto.
- Auth antes do roteamento de método: sem credencial válida, sempre `401`
  (ou `500` com setting ausente, por precedência fail-closed).
- Não tocar na query da foto, no setting do token, no envelope
  compartilhado ou no logger salvo para correção de bug do próprio slice
  (justificar).
- Nenhuma migration; nenhuma dependência nova.

## Validation

### Focused validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

### Project-required gates

Seguir `AGENTS.md`; gates finais do change rodam após todos os slices.
Nenhum `.md` deve ser tocado neste slice.

### Runtime/verification evidence

Requests reais contra instância containerizada com fixtures sintéticas:
`200` com payload e key-set conferidos contra D4, `404` com envelope para
prontuário inexistente, `405` para POST autenticado, `401` para POST sem
token, access log da demografia sanitizado. Sem Playwright; sem dados
reais.

## Acceptance criteria

- [ ] R1: lookup em `tasy`, echo do `prontuario`, escalares verbatim,
      `phones`/`address` pelo mapeamento D4, `""` preservado, `null` só onde
      nullable, `updated_at` presente.
- [ ] R2: exatamente as 19 chaves allowlisted, sem internos do modelo nem
      extras.
- [ ] R3: `404` com código `patient_not_found` no envelope padrão.
- [ ] R4: auth/envelope/logger compartilhados sem duplicação; `405`
      autenticado / `401` sem token; access log sanitizado; foto de UPA-001
      inalterada (suíte verde).

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se houver contradição
proposal/spec/design, necessidade de alterar UPA-001 além de adição,
migration, normalização de valores, lookup fora de `tasy`, key-set
divergente do allowlisted, expansão material, ou risco novo de
privacidade/integridade.

## Evidence report

Caminho: `/tmp/sirhosp-slice-UPA-002-report.md`. Seguir relatório
obrigatório de `AGENTS.md` (requirements → evidence, RED/GREEN, arquivos,
comandos/exit, verification, desvios, riscos). Sem dados reais.

## Worker handoff

Implement only this approved slice.
Treat the slice and referenced OpenSpec artifacts as the implementation contract.
Reconstruct context from the listed files; do not rely on prior conversation.
Follow the repository engineering policy.
Produce failing-before evidence, implement the smallest correct change, run focused validation, and produce the required evidence report.
Do not update `tasks.md`, commit, push, merge, archive, or start another slice.
If a new decision is required, stop with `BLOCKED_NEEDS_DECISION` and evidence.
Otherwise finish with `READY_FOR_REVIEW` and `REPORT_PATH=/tmp/sirhosp-slice-UPA-002-report.md`.
