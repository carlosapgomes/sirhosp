# SLICE-S3 — CI usando o mesmo entrypoint containerizado

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/containerized-test-standardization/proposal.md`
4. `openspec/changes/containerized-test-standardization/design.md`
5. `openspec/changes/containerized-test-standardization/tasks.md`
6. `openspec/changes/containerized-test-standardization/specs/developer-quality-gates/spec.md`
7. `/tmp/sirhosp-slice-CTS-S2-report.md`
8. este arquivo `slice-prompts/SLICE-S3.md`

## Pré-condição de branch

Obrigatório estar na branch da change (mesma da S1/S2).

## Objetivo do slice

Adicionar pipeline CI para executar os quality gates com o mesmo contrato local (`scripts/test-in-container.sh`).

## Escopo permitido (somente)

- `.github/workflows/quality-gate.yml` (novo)
- `README.md` (se necessário para badge/instrução CI)
- `AGENTS.md` (somente se necessário para apontar comando oficial em CI)

## Escopo proibido

- Mudança em regras de domínio
- Mudanças no compose base fora do necessário para CI
- Refactors amplos de documentação

## Limite de alteração

Máximo: **5 arquivos**.

## Regras obrigatórias deste slice

1. CI deve chamar o mesmo script usado localmente.
2. Pipeline deve executar teardown/cleanup ao final (inclusive em falha).
3. Coletar logs úteis quando gate falhar.

## TDD obrigatório (quando aplicável)

1. **RED**: validar ausência de workflow ativo para quality gate.
2. **GREEN**: criar workflow com job executando `./scripts/test-in-container.sh quality-gate`.
3. **REFACTOR**: simplificar passos mantendo legibilidade.

## Gates obrigatórios S3

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh quality-gate`
2. validação YAML do workflow (ferramenta disponível no ambiente)

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-CTS-S3-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S4).

Pare ao concluir.
