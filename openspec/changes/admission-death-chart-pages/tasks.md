# Tasks: admission-death-chart-pages

## Convenções desta change

- Prefixo de slice: `ADC` (Admission/Death Charts).
- Execução estrita: 1 slice por vez, com TDD (`red -> green -> refactor`).
- Cada slice deve ter prompt próprio em `slice-prompts/SLICE-ADC-SX.md`.
- Cada slice gera relatório obrigatório em
  `/tmp/sirhosp-slice-ADC-SX-report.md`.
- Se precisar extrapolar escopo/limite de arquivos, parar e reportar bloqueio.

## Slice ADC-S1 — Backend e rotas dos gráficos de admissões/óbitos

**Objetivo vertical:** expor páginas autenticadas com contexto de gráfico diário
e média semanal, ainda que o template inicial seja mínimo.

**Escopo máximo:** 2 arquivos de código + 1 arquivo de teste.

- [x] 1.1 (RED) Adicionar testes em `tests/unit/test_services_portal_dashboard.py`
      para:
  - `services_portal:admission_chart` exige autenticação;
  - `services_portal:death_chart` exige autenticação;
  - usuário autenticado recebe HTTP 200 nas duas rotas;
  - contexto de admissões usa `DailyAdmissionCount`;
  - contexto de óbitos usa `DailyDeathCount`;
  - `?dias=30` limita a série retornada.
- [x] 1.2 Implementar rotas em `apps/services_portal/urls.py`:
  - `painel/admissoes/` → `admission_chart`;
  - `painel/obitos/` → `death_chart`.
- [x] 1.3 Implementar em `apps/services_portal/views.py`:
  - helper genérico para parse de período e montagem de `chart_data`;
  - helper genérico ou reaproveitamento seguro de `_weekday_average`;
  - views `admission_chart` e `death_chart` com metadados textuais.
- [x] 1.4 Criar template mínimo compartilhado apenas para permitir render 200,
      se necessário para fechar o slice.
- [x] 1.5 Gate ADC-S1:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
- [x] 1.6 Gerar `/tmp/sirhosp-slice-ADC-S1-report.md`.

## Slice ADC-S2 — Template compartilhado com dois gráficos de barras

**Objetivo vertical:** entregar a experiência visual completa nas novas páginas.

**Escopo máximo:** 2 templates + 1 arquivo de teste + ajustes mínimos em view
se necessários.

- [x] 2.1 (RED) Adicionar testes para HTML das páginas:
  - presença do canvas do gráfico diário;
  - presença do canvas da média por dia da semana quando há dados;
  - estado vazio sem canvas quebrado quando não há registros;
  - títulos específicos para admissões e óbitos.
- [x] 2.2 Implementar template compartilhado
      `apps/services_portal/templates/services_portal/daily_event_chart.html`:
  - breadcrumb para Dashboard;
  - seletor de período `30`, `60`, `90`, `180`, `365`;
  - card do gráfico diário em barras;
  - card da média por dia da semana em barras;
  - mensagens de estado vazio.
- [x] 2.3 Implementar JavaScript Chart.js parametrizado por `json_script`:
  - dataset label específico (`Admissões` ou `Óbitos`);
  - tooltip da média semanal com valor e `n` de observações;
  - degradação segura quando Chart.js ou dados não estiverem disponíveis.
- [x] 2.4 Gate ADC-S2:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
- [x] 2.5 Gerar `/tmp/sirhosp-slice-ADC-S2-report.md`.

## Slice ADC-S3 — Navegação a partir das listagens e hardening final

**Objetivo vertical:** tornar a feature descobrível nas páginas onde o usuário
já consulta admissões e óbitos por data.

**Escopo máximo:** 2 templates + 1 arquivo de teste.

- [x] 3.1 (RED) Adicionar testes para navegação:
  - `admission_list.html` contém link para `services_portal:admission_chart`;
  - `death_list.html` contém link para `services_portal:death_chart`;
  - os links não removem o seletor de data nem o botão de retorno ao dashboard.
- [x] 3.2 Atualizar `admission_list.html` com botão
      `Ver gráfico de admissões`.
- [x] 3.3 Atualizar `death_list.html` com botão `Ver gráfico de óbitos`.
- [x] 3.4 Revisar estados vazios/esparsos e consistência dos labels.
- [x] 3.5 Gate ADC-S3:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
  - `./scripts/markdown-lint.sh`
- [x] 3.6 Gerar `/tmp/sirhosp-slice-ADC-S3-report.md`.

## Stop Rule

- Implementar somente o slice atual.
- Parar ao final de cada slice e aguardar aprovação humana.
- Não avançar de slice sem relatório completo e gates verdes.
