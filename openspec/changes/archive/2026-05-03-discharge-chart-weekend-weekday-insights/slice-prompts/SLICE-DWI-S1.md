# SLICE DWI-S1 — Destaque de sábado/domingo no gráfico principal

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/proposal.md`
4. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/design.md`
5. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/tasks.md`
6. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/specs/daily-discharge-tracking/spec.md`
7. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-DWI-S1.md`

## Objetivo do slice

Implementar destaque visual de sábado/domingo nas barras do gráfico principal
em `/painel/altas/`, sem alterar rota, período nem médias móveis existentes.

## Escopo permitido (máx 3 arquivos)

- `tests/unit/test_services_portal_dashboard.py`
- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/discharge_chart.html`

## Escopo proibido

- criar novos arquivos fora dos 3 listados;
- alterar URLconf;
- alterar modelos/migrations/commands;
- alterar regras de cálculo das médias móveis existentes.

## TDD obrigatório

1. **RED**: ajustar testes para falhar exigindo:
   - `chart_data.weekend_flags` no contexto;
   - tamanho igual a `labels`;
   - marcação correta de sábado/domingo em dataset sintético conhecido;
   - presença no HTML/JS de uso da metadata para colorização por barra.
2. **GREEN**: implementar em view + template.
3. **REFACTOR**: limpar nomes e manter legibilidade.

## Requisitos funcionais congelados

1. `chart_data.weekend_flags` deve ser lista booleana alinhada por índice com
   `labels` e `counts`.
2. Sábado e domingo devem usar tons diferentes de dia útil no dataset de
   barras.
3. Legenda textual deve indicar a convenção de cores.
4. Séries `sma7`, `ema7`, `sma30` devem permanecer presentes.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-DWI-S1-report.md`

Validar markdown:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-DWI-S1-report.md
```

## Stop rule

Ao concluir:

- pare imediatamente;
- entregue caminho do relatório;
- não inicie DWI-S2.
