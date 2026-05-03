# SLICE DWI-S3 — Hardening de estados vazios + gate final

## Handoff de entrada (executor com contexto zero)

Leia obrigatoriamente, nesta ordem:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/proposal.md`
4. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/design.md`
5. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/tasks.md`
6. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/specs/daily-discharge-tracking/spec.md`
7. `openspec/changes/2026-05-03-discharge-chart-weekend-weekday-insights/slice-prompts/REPORT-TEMPLATE.md`
8. este arquivo `SLICE-DWI-S3.md`

## Objetivo do slice

Garantir robustez da página em cenários de dados vazios/esparsos e concluir a
change com validação completa.

## Escopo permitido (máx 3 arquivos)

- `tests/unit/test_services_portal_dashboard.py`
- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/discharge_chart.html`

## Escopo proibido

- alterar componentes fora da página `/painel/altas/`;
- alterar rotas;
- alterar pipeline de ingestão;
- adicionar novos templates/arquivos além dos 3 permitidos.

## TDD obrigatório

1. **RED**: adicionar cenários de teste para:
   - `DailyDischargeCount` vazio;
   - período curto com weekdays ausentes;
   - coerência de `weekday_avg.counts` com dados do período.
2. **GREEN**: ajustar fallback de renderização para evitar scripts quebrados e
   mensagens ambíguas.
3. **REFACTOR**: remover condicionais redundantes e manter clareza do template.

## Requisitos funcionais congelados

1. A página deve continuar renderizando sem erro quando não houver dados.
2. O segundo gráfico não deve disparar erro JS em datasets vazios.
3. O comportamento de autenticação e seletor de período deve permanecer
   inalterado.

## Gates obrigatórios

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh integration`
- `./scripts/test-in-container.sh lint`
- `./scripts/test-in-container.sh typecheck`
- `./scripts/markdown-lint.sh`

## Relatório obrigatório

Gerar: `/tmp/sirhosp-slice-DWI-S3-report.md`

Validar markdown:

```bash
./scripts/markdown-lint.sh /tmp/sirhosp-slice-DWI-S3-report.md
```

## Stop rule

Ao concluir:

- pare imediatamente;
- entregue caminho do relatório;
- não continue para outras changes.
