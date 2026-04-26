# SLICE-S5 — Hardening final + contrato de chunking

## Handoff de entrada (contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-first-missing-patient-flow/proposal.md`
4. `openspec/changes/admission-first-missing-patient-flow/design.md`
5. `openspec/changes/admission-first-missing-patient-flow/tasks.md`
6. specs da change:
   - `openspec/changes/admission-first-missing-patient-flow/specs/evolution-ingestion-on-demand/spec.md`
   - `openspec/changes/admission-first-missing-patient-flow/specs/ingestion-run-observability/spec.md`
7. este arquivo `slice-prompts/SLICE-S5.md`

## Pré-condição de branch

Executar e registrar no relatório:

```bash
git checkout feature/admission-first-missing-patient-flow
git fetch origin
git status --short --branch
```

## Objetivo do slice

Consolidar regressão final e formalizar cobertura de chunking (`<= 15 dias/chunk`) para períodos longos (`> 29 dias`).

## Escopo permitido (somente)

- `automation/source_system/medical_evolution/path2.py` (apenas se necessário)
- testes relacionados a extractor/chunking
- ajustes mínimos em docs/tasks desta change

## Escopo proibido

- novas features de UI
- mudanças de fluxo admission-first já fechadas em S1-S4

## Limite de alteração

Máximo: **6 arquivos**.
Se precisar exceder, **parar** e reportar bloqueio.

## Protocolo anti-drift (obrigatório)

1. Implementar **somente este slice**.
2. Foco em contrato de chunking + fechamento da change.
3. Sem refactors amplos.

## TDD obrigatório

1. **RED**: testes de fragmentação de janela longa falhando.
2. **GREEN**: chunking determinístico e limite de 15 dias garantidos.
3. **REFACTOR**: limpeza sem mudar semântica.

## Gates obrigatórios S5

Executar e registrar **todos** os comandos com exit code:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh integration`
4. `./scripts/test-in-container.sh lint`
5. `./scripts/test-in-container.sh typecheck`
6. `./scripts/markdown-lint.sh` (se houver `.md` alterado)

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-AFMF-S5-report.md` contendo obrigatoriamente:

1. Resumo do slice.
2. Checklist de aceite.
3. Lista de arquivos alterados.
4. **Snippet before/after para cada arquivo alterado**.
5. Tabela de **todos os comandos executados** (incluindo RED) com comando, objetivo, exit code e status.
6. Seção explícita "Testes executados no slice" com lista completa dos testes rodados e resultado.
7. Consolidação final da change e recomendação de próximo passo (archive).

Não incluir dados sensíveis. Parar ao concluir.
