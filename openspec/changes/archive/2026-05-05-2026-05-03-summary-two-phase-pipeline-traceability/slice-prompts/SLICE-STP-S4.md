# SLICE STP-S4 — Câmbio USD/BRL (modelo + command diário)

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/proposal.md`
4. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/design.md`
5. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/tasks.md`
6. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/specs/summary-llm-traceability/spec.md`
7. `openspec/changes/2026-05-03-summary-two-phase-pipeline-traceability/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-STP-S4.md`

## Objetivo

Criar infraestrutura de cotação USD/BRL com fonte primária sem API key e
fallback com API key.

## Escopo permitido (máx 5 arquivos)

- `apps/summaries/models.py`
- `apps/summaries/migrations/*` (somente nova migração)
- `apps/summaries/management/commands/sync_exchange_rates.py`
- `apps/summaries/exchange_rates.py`
- `tests/unit/test_exchange_rate_sync_command.py`

## Escopo proibido

- UI de logs/status;
- orquestração de resumo;
- CRUD de prompts.

## Estratégia de execução (TDD + clean code)

1. **RED:** testes do command (primária, fallback, sem API key, retenção).
2. **GREEN:** implementar modelo + command + helper.
3. **REFACTOR:** separar responsabilidades (fetch/parsing/persistência).

## Critérios de sucesso

- modelo `ExchangeRateSnapshot` persistindo taxa, provider e data;
- command diário atualiza cotação do dia;
- fallback só roda com `SUMMARY_EXCHANGE_FALLBACK_API_KEY`;
- sem API key de fallback, comando mantém comportamento seguro;
- helper retorna cotação mais recente disponível.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-STP-S4-report.md`

Validar markdown do relatório:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-STP-S4-report.md
```

## Stop rule

Ao concluir este slice:

1. pare imediatamente;
2. entregue caminho do relatório + resumo curto;
3. não avance para `STP-S5`.
