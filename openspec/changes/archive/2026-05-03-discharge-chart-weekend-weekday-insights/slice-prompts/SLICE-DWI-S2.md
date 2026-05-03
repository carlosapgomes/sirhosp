# SLICE DWI-S2 — Gráfico de média por dia da semana abaixo do atual

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/proposal.md`
4. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/design.md`
5. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/tasks.md`
6. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/specs/daily-discharge-tracking/spec.md`
7. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-DWI-S2.md`

## Objetivo do slice

Adicionar um segundo gráfico na mesma página `/painel/altas/`, abaixo do
atual, exibindo média de altas por dia da semana (Seg..Dom) baseada no mesmo
período `?dias=N`.

## Escopo permitido (máx 3 arquivos)

- `tests/unit/test_services_portal_dashboard.py`
- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/discharge_chart.html`

## Escopo proibido

- criar nova rota ou nova página;
- alterar seleção de período já existente;
- alterar models/migrations;
- introduzir bibliotecas novas.

## TDD obrigatório

1. **RED**: criar/ajustar testes cobrindo:
   - presença de `weekday_avg` no contexto com chaves `labels`, `values`,
     `counts`;
   - ordem fixa `Seg, Ter, Qua, Qui, Sex, Sáb, Dom`;
   - média correta por weekday em fixture determinística;
   - presença do segundo canvas no HTML (id `weekdayAverageChart`).
2. **GREEN**: implementar helper de agregação na view e renderização do
   segundo gráfico no template.
3. **REFACTOR**: manter helpers pequenos e sem duplicação.

## Requisitos funcionais congelados

1. O novo gráfico deve ficar abaixo do gráfico principal na mesma página.
2. A média semanal deve usar exatamente o mesmo recorte de dias que alimenta o
   gráfico principal (até ontem).
3. Tooltip do gráfico semanal deve incluir média e quantidade de observações
   (`n`) do weekday.
4. Ordem visual no eixo X deve ser Seg..Dom, independentemente da presença de
   dados para todos os dias.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-DWI-S2-report.md`

Validar markdown:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-DWI-S2-report.md
```

## Stop rule

Ao concluir:

- pare imediatamente;
- entregue caminho do relatório;
- não inicie DWI-S3.
