# Slice UPA-003 — Documentação do consumidor e aceite do contrato

## Identity

- Change: `sirhosp-upstream-api-v1`.
- Slice: `UPA-003`.
- Tasks: grupo 5 de `tasks.md` (itens 5.1–5.2) + item 6.1.
- Depende de: UPA-001 e UPA-002 aceitos (comportamento final).

## Objective

Publicar a documentação operacional da API para o time consumidor e
executar o checklist de aceite do contrato com evidência por item.

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/sirhosp-upstream-api-v1/proposal.md`.
- `openspec/changes/sirhosp-upstream-api-v1/design.md` (D3–D10, Migration).
- `openspec/changes/sirhosp-upstream-api-v1/specs/upstream-read-api/spec.md`.
- `apps/upstream_api/` final (comportamento real a documentar).
- `/projects/dev/hgproxy/docs/sirhosp-upstream-contract.md` (contrato v2
  do consumidor — referência externa, não versionada aqui).

Follow the repository engineering policy in `AGENTS.md` and preserve existing
conventions. Prefer the smallest correct change; avoid speculative
abstraction and unrelated refactoring.

## Requirements

| ID  | Requisito                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Evidência planejada                                                        |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| R1  | Doc do consumidor com os 2 endpoints, exemplos `curl`/Python, algoritmo de polling/dedup (`captured_at` + tie-break + semântica `no_snapshot`), códigos de erro e runbook de rotação do token                                                                                                                                                                                                                                                                                       | Cada comando documentado executado como escrito contra dev containerizado  |
| R2  | Contrato operacional registrado: rede interna com verificação por compose (hospital via `SIRHOSP_BIND_ADDRESS` restrito, prod genérico via firewall/proxy do operador com probe de alcance), responsabilidade do proxy, disciplina aditiva de campos, escopo 4–6 h e gaps de polling aceitos                                                                                                                                                                                        | Inspeção do doc final                                                      |
| R3  | Todos os `.md` tocados passam no lint do projeto                                                                                                                                                                                                                                                                                                                                                                                                                                    | `./scripts/markdown-lint.sh` verde                                         |
| R4  | Checklist de aceite executado ponta a ponta (auth e precedência fail-closed, fronteira de middlewares, ordenação exata de runs e linhas, atomicidade com ciclo em andamento, fotos vazia e ausente, linha inválida fail-closed, regra da meia-noite, identidade de setor, offsets, access output sanitizado e error output sanitizado-ou-ausente com query/path desconhecido/malformado/erro forçado, key-set exato da demografia, repeats idênticos) com evidência ligada por item | Relatório com item → evidência (reaproveita suítes + 1 passada e2e fresca) |

## Expected blast radius

Superfícies esperadas:

- `docs/upstream-api.md` (novo; se a convenção do projeto indicar outro
  local, justificar no relatório).
- Relatórios de evidência em `/tmp` (não versionados).

Superfícies sensíveis / fora de escopo sem escalada:

- Código Python, settings, env, gunicorn, docker: nenhuma alteração.
- Credenciais, tokens, URLs reais, nomes de sistemas da origem: nunca
  documentar valores reais (placeholders apenas).
- Dados reais de pacientes em exemplos, comandos ou evidências.

Arquivo adicional só com justificativa no relatório.

## Failing-before plan

Evidência before proporcional a slice de docs/aceite (sem RED de código):

1. Registrar que `docs/upstream-api.md` não existe e que nenhum comando
   documentado é hoje reproduzível pelo consumidor.
2. Executar a passada e2e fresca do checklist (R4) contra o estado atual e
   registrar cada item com sua evidência; qualquer item sem evidência é
   falha do slice, não lacuna aceita.

## Implementation constraints

- Este slice não altera código: se o checklist revelar bug ou divergência
  doc-vs-código, parar com `BLOCKED_NEEDS_DECISION` e evidência em vez de
  corrigir aqui.
- Exemplos com fixtures sintéticas apenas (`0000001`, nomes `PACIENTE
EXEMPLO`); nunca ecoar dado real mesmo que o ambiente local o contenha.
- Doc em português, comandos com `curl` e Python stdlib (sem dependência
  nova para o consumidor).
- Não prometer comportamento futuro (`?include_empty_beds`, v2,
  rate limit) como disponível; futuro fica em seção explícita de
  fora de escopo.

## Validation

### Focused validation

```bash
./scripts/markdown-lint.sh
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
```

Os gates de teste aqui são guards de regressão (nada deve ter mudado no
código); o núcleo do slice é documental + checklist.

### Project-required gates

Seguir `AGENTS.md`; o gate final do change (item 6.2 de `tasks.md`) é
dever do controller após este slice, não do worker.

### Runtime/verification evidence

Cada comando do doc executado como escrito contra dev containerizado,
com saidas conferidas; passada e2e fresca do checklist com item →
evidência. Sem Playwright; sem dados reais.

## Acceptance criteria

- [ ] R1: doc publicado com endpoints, exemplos, polling/dedup com
      tie-break e `no_snapshot`, erros e rotação; todos os comandos
      reproduzidos como escritos.
- [ ] R2: contrato operacional (rede interna com verificação por compose,
      proxy, aditividade, escopo 4–6 h, gaps aceitos) registrado no doc.
- [ ] R3: `./scripts/markdown-lint.sh` verde nos arquivos tocados.
- [ ] R4: checklist de aceite com evidência ligada por item, sem item
      presumido.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se qualquer item do checklist falhar ou
não tiver evidência, se doc e código divergirem, se for preciso dado real
para demonstrar algo, ou se surgir implicação nova de segurança,
privacidade ou compatibilidade.

## Evidence report

Caminho: `/tmp/sirhosp-slice-UPA-003-report.md`. Seguir relatório
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
Otherwise finish with `READY_FOR_REVIEW` and `REPORT_PATH=/tmp/sirhosp-slice-UPA-003-report.md`.
