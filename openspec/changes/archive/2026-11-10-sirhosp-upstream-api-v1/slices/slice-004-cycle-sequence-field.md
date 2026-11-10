# Slice UPA-004 — Campo de sequência do ciclo v1.1 (aditivo)

## Identity

- Change: `sirhosp-upstream-api-v1`.
- Slice: `UPA-004`.
- Tasks: grupo 7 de `tasks.md` (itens 7.1–7.2).
- Depende de: UPA-001, UPA-002 e UPA-003 aceitos (adiciona um campo ao
  payload da foto, sem mudar comportamento existente).

## Objective

Expor `cycle_seq` (pk do run servido, inteiro JSON) na foto de internados
como chave de dedupe/ordenação independente de relógio, e documentá-lo,
sem alterar nenhum comportamento existente.

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/sirhosp-upstream-api-v1/proposal.md`.
- `openspec/changes/sirhosp-upstream-api-v1/design.md` (D3).
- `openspec/changes/sirhosp-upstream-api-v1/specs/upstream-read-api/spec.md`
  (foto + "Cycle sequence orders photos totally").
- `apps/upstream_api/` final (serialização da foto em `views.py`,
  query em `photo.py`).
- `docs/upstream-api.md` (exemplos de payload a atualizar).
- `/projects/dev/hgproxy/docs/sirhosp-upstream-contract.md` (referência
  externa: o consumidor ignora o campo por enquanto).

Follow the repository engineering policy in `AGENTS.md` and preserve existing
conventions. Prefer the smallest correct change; avoid speculative
abstraction and unrelated refactoring.

## Requirements

| ID  | Requisito                                                                                                                                                                          | Evidência planejada                                             |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| R1  | Foto inclui `cycle_seq` inteiro igual ao pk do run elegível servido; ciclos distintos com mesmo `captured_at` têm `cycle_seq` distintos; poll repetido sem ciclo novo repete o par | Unit da query/serialização + integration do payload             |
| R2  | Nenhum comportamento existente muda: mesmos status, envelope, ordenação, logs, 404/500 e key-set da demografia                                                                     | Suítes de UPA-001/UPA-002 re-executadas verdes (focadas)        |
| R3  | Doc atualizado (payload, dedup por par, `cycle_seq` como chave futura) com blocos afetados reexecutados como escritos + lint verde                                                 | Re-execução dos blocos alterados + `./scripts/markdown-lint.sh` |

## Expected blast radius

Superfícies esperadas:

- `apps/upstream_api/views.py` (ou serializador da foto — só adição da
  chave).
- `tests/unit/test_upstream_api_*.py` e
  `tests/integration/test_upstream_api_photo_http.py` (extensão).
- `docs/upstream-api.md` (exemplos de payload da foto + § de dedup).

Superfícies sensíveis / fora de escopo sem escalada:

- Query de elegibilidade/ordenação, auth, envelope, demografia, logging,
  middlewares, composes, settings, gunicorn.
- Qualquer mudança de semântica de `captured_at` ou do algoritmo de
  polling; valor do campo fora do pk do run servido.

Arquivo adicional só com justificativa no relatório.

## Failing-before plan

1. Teste que espera `cycle_seq` no payload da foto falha (chave não
   existe).
2. Teste de dois ciclos com mesmo `captured_at` falha no `cycle_seq`
   distinto (chave não existe).
3. Bloco de doc alterado diverge do output servido até o código existir
   (registrar antes/depois).

## Implementation constraints

- `cycle_seq` é exatamente o pk do run elegível servido, inteiro JSON;
  nunca derivar de timestamp nem inventar sequência própria.
- Aditivo puro: nenhum status, código de erro, ordem, log ou doc além do
  payload/dedup muda; se qualquer teste existente quebrar por
  comportamento (não por payload esperado), parar com `BLOCKED`.
- Não expor pk de linhas, runs não elegíveis ou qualquer outro
  identificador interno.
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

Mais re-execução containerizada dos blocos de doc alterados.

### Project-required gates

Seguir `AGENTS.md`; o gate final da change será re-executado pelo
controller após este slice (código muda ⇒ resultados anteriores não
comprovam o estado final).

### Runtime/verification evidence

Requests reais contra instância containerizada: foto com `cycle_seq`
presente e inteiro, dois polls do mesmo estado com par idêntico,
`cycle_seq` distintos entre ciclos com mesmo `captured_at`. Sem
Playwright; sem dados reais.

## Acceptance criteria

- [ ] R1: `cycle_seq` presente, inteiro, igual ao pk servido; distinto
      entre ciclos com mesmo `captured_at`; par idêntico em repeats.
- [ ] R2: suítes de UPA-001/UPA-002 verdes, sem mudança de comportamento.
- [ ] R3: doc atualizado com exemplos executados como escritos; lint verde.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se qualquer teste existente quebrar por
mudança de comportamento, se o pk não puder ser exposto (ex.: restrição
de identificador interno), se for preciso mudar semântica de ordenação
ou dedup, ou se surgir risco novo de privacidade/integridade.

## Evidence report

Caminho: `/tmp/sirhosp-slice-UPA-004-report.md`. Seguir relatório
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
Otherwise finish with `READY_FOR_REVIEW` and `REPORT_PATH=/tmp/sirhosp-slice-UPA-004-report.md`.
