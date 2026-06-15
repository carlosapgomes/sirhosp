# Tasks: hospital-flow-pressure-dashboard

## 1. Slice S1 — Serviço de domínio: agregação estoque/fluxo/resíduo

- [x] 1.1 (RED) Criar testes unitários para
  `compute_hospital_flow(start, end, sector=None)` cobrindo: ADC com
  múltiplos snapshots/dia, inflow/outflow por fonte dedicada, líquido,
  delta_adc, resíduo, dia sem snapshot (ADC None), filtro por setor.
- [x] 1.2 Implementar `apps/census/flow_service.py` retornando lista de
  dicts/datas estruturada por dia, até os testes passarem (GREEN).
- [x] 1.3 (REFACTOR) Eliminar duplicação, nomear claramente, sem ampliar
  escopo.
- [x] 1.4 Gate: `./scripts/test-in-container.sh check`,
  `./scripts/test-in-container.sh unit`,
  `./scripts/test-in-container.sh lint`.

## 2. Slice S2 — View + URL + template tabela + sidebar

- [x] 2.1 (RED) Criar testes unitários da view `hospital_flow_view`
  cobrindo: autenticação obrigatória, janela default 90 dias, seletor
  30/90/180, contexto com séries do serviço, renderização da tabela.
- [x] 2.2 Implementar view em `apps/census/views.py` chamando o serviço
  (view fina, sem lógica de negócio).
- [x] 2.3 Adicionar rota `hospital_flow` em `apps/census/urls.py`.
- [x] 2.4 Criar `templates/census/hospital_flow.html` com tabela (ainda
  sem gráfico) e seletor de janela.
- [x] 2.5 Adicionar entrada "Fluxo Hospitalar" no
  `templates/includes/sidebar.html` após "Leitos", com `active_menu`.
- [x] 2.6 Gate: `./scripts/test-in-container.sh check`,
  `./scripts/test-in-container.sh unit`,
  `./scripts/test-in-container.sh lint`.

## 3. Slice S3 — Visualização Chart.js (barras divergentes + linha ADC)

- [x] 3.1 (RED) Ajustar testes da view para validar contexto JSON
  serializável para o Chart.js (labels, adm, altas_obitos, adc com null).
- [x] 3.2 Implementar bloco Chart.js no template (CDN 4.4.0, mesmo padrão
  de `daily_event_chart.html`): barras divergentes + linha ADC em eixo
  secundário, com `json_script` e `safeJSON`.
- [x] 3.3 Garantir gap honesto: ADC null renderizado como gap na linha.
- [x] 3.4 Gate: `./scripts/test-in-container.sh check`,
  `./scripts/test-in-container.sh unit`,
  `./scripts/test-in-container.sh lint`.

## 4. Slice S4 — Drill-down por setor

- [x] 4.1 (RED) Criar/ajustar testes cobrindo filtro `sector` na view e
  no serviço (ADC por setor, lista de setores no contexto).
- [x] 4.2 Estender serviço/view para alimentar seletor de setores e
  aplicar filtro (`sector=None` = hospital-total).
- [x] 4.3 Adicionar seletor (dropdown) no template que submete o filtro
  (HTMX ou GET simples, conforme padrão do projeto).
- [x] 4.4 Gate: `./scripts/test-in-container.sh check`,
  `./scripts/test-in-container.sh unit`,
  `./scripts/test-in-container.sh lint`.

## 5. Slice S5 — Painel de resíduo QC para admin

- [x] 5.1 (RED) Criar testes cobrindo: admin vê bloco de resíduo no
  contexto/template; não-admin não vê.
- [x] 5.2 Expor série de resíduo no contexto (admin-gated via
  `request.user.is_staff` ou `is_superuser`).
- [x] 5.3 Adicionar seção no template (abaixo do gráfico) com
  mini-gráfico ou tabela de resíduo + legenda curta, com cores de
  limiar (amarelo > 3%, vermelho > 5%).
- [x] 5.4 Gate: `./scripts/test-in-container.sh check`,
  `./scripts/test-in-container.sh unit`,
  `./scripts/test-in-container.sh lint`.

## 6. Fechamento do change

- [x] 6.1 Criar prompts detalhados por slice em
  `slice-prompts/SLICE-SX.md` (handoff zero-context + escopo + TDD +
  relatório obrigatório).
- [x] 6.2 Validar markdown: `./scripts/markdown-lint.sh` em todos os
  `.md` criados/alterados.
- [x] 6.3 Consolidar relatórios obrigatórios
  `/tmp/sirhosp-slice-HFPD-SX-report.md`.
- [x] 6.4 Preparar change para `/opsx:apply` ou execução por LLM
  executor com contexto zero.
