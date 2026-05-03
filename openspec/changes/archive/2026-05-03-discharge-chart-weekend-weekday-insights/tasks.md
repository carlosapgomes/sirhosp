# Tasks: discharge-chart-weekend-weekday-insights

## Convenções desta change

- Prefixo de slice: `DWI` (Discharge Weekday Insights).
- Execução estrita: 1 slice por vez, com TDD (`red -> green -> refactor`).
- Cada slice gera relatório obrigatório em
  `/tmp/sirhosp-slice-DWI-SX-report.md`.
- Se precisar extrapolar escopo/limite de arquivos, parar e reportar bloqueio.

## Slice DWI-S1 — Destaque de sábado/domingo no gráfico principal

**Objetivo vertical:** habilitar leitura imediata de fim de semana no gráfico de
barras existente.

**Escopo máximo:** 3 arquivos.

- [x] 1.1 (RED) Ajustar `tests/unit/test_services_portal_dashboard.py` para
      validar:
  - presença de `chart_data.weekend_flags` com mesmo tamanho de `labels`;
  - flags corretas para amostra conhecida contendo sábado/domingo;
  - resposta da página contém sinal de uso de cores por barra no JS.
- [x] 1.2 Implementar em `apps/services_portal/views.py`:
  - geração de `weekend_flags` por data;
  - (opcional) `weekday_short` para tooltip/futuro.
- [x] 1.3 Implementar em
      `apps/services_portal/templates/services_portal/discharge_chart.html`:
  - cores diferentes para sábado/domingo no dataset de barras;
  - atualização da legenda para explicar tons.
- [x] 1.4 Gate DWI-S1:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
- [x] 1.5 Gerar `/tmp/sirhosp-slice-DWI-S1-report.md`.

## Slice DWI-S2 — Gráfico de média por dia da semana abaixo do atual

**Objetivo vertical:** adicionar novo gráfico agregador Seg..Dom na mesma
página `/painel/altas/`.

**Escopo máximo:** 3 arquivos.

- [x] 2.1 (RED) Expandir `tests/unit/test_services_portal_dashboard.py` para
      validar:
  - contexto com `weekday_avg.labels`, `weekday_avg.values`,
    `weekday_avg.counts`;
  - ordem fixa Seg..Dom;
  - cálculo correto das médias por weekday para dataset conhecido;
  - presença do segundo canvas no HTML (`weekdayAverageChart`).
- [x] 2.2 Implementar backend em `apps/services_portal/views.py`:
  - helper de agregação por weekday;
  - inclusão de `weekday_avg` no contexto.
- [x] 2.3 Implementar frontend em
      `apps/services_portal/templates/services_portal/discharge_chart.html`:
  - novo card abaixo do gráfico principal;
  - Chart.js bar para `weekday_avg`;
  - tooltip com média e `n` do weekday.
- [x] 2.4 Gate DWI-S2:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
- [x] 2.5 Gerar `/tmp/sirhosp-slice-DWI-S2-report.md`.

## Slice DWI-S3 — Hardening, estados vazios e gate final

**Objetivo vertical:** consolidar robustez da página com dados escassos/vazios
sem regressão da UX atual.

**Escopo máximo:** 3 arquivos.

- [x] 3.1 (RED) Ajustar testes em
      `tests/unit/test_services_portal_dashboard.py` para cenários:
  - sem dados (`DailyDischargeCount` vazio) mantém página estável;
  - período curto (ex.: 15 dias) sem alguns weekdays não quebra;
  - `weekday_avg.counts` coerente com período filtrado.
- [x] 3.2 Ajustar implementação em `views.py`/template para fallback robusto
      do segundo gráfico quando não houver observações suficientes.
- [x] 3.3 Gate DWI-S3:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
  - `./scripts/markdown-lint.sh`
- [x] 3.4 Gerar `/tmp/sirhosp-slice-DWI-S3-report.md`.

## Stop Rule

- Implementar somente o slice atual.
- Parar ao final e aguardar aprovação humana.
- Não avançar de slice sem relatório completo e gates verdes.
