# Design: admission-death-chart-pages

## Current State

A avaliação do código atual mostrou:

- `apps/services_portal/views.py` possui `discharge_chart`, com rota
  `painel/altas/`, template `discharge_chart.html` e dados de
  `DailyDischargeCount`.
- A página de altas contém mais do que o escopo pedido: gráfico diário com
  barras e linhas de média móvel, média por dia da semana, distribuição horária
  por especialidade e tabela de resumo.
- `admission_list` e `death_list` já existem e consultam, respectivamente,
  `DailyAdmissionCount` e `DailyDeathCount`.
- Os templates `admission_list.html` e `death_list.html` não têm botão para
  gráficos; `discharge_list.html` tem botão `Ver gráfico de altas`.
- Os modelos `DailyAdmissionCount` e `DailyDeathCount` têm a mesma forma mínima
  necessária para séries diárias: `date`, `count`, `raw_data`, timestamps e
  relação com registros detalhados.
- Não há necessidade de migration para esta feature.

## Goals / Non-Goals

### Goals

1. Adicionar página autenticada de gráficos de admissões.
2. Adicionar página autenticada de gráficos de óbitos.
3. Incluir em cada página:
   - gráfico de barras por dia;
   - gráfico de barras com média por dia da semana.
4. Reaproveitar seletor de período e padrão visual já familiares na página de
   altas.
5. Evitar duplicação excessiva extraindo helpers puros para construir o
   contrato view-template.

### Non-Goals

- Reimplementar a página de altas neste change.
- Adicionar gráficos horários ou por especialidade para admissões/óbitos.
- Adicionar médias móveis obrigatórias às novas páginas.
- Alterar modelos, extrações ou comandos de ingestão.
- Criar endpoint JSON separado.

## Decisions

### 1) Rotas dedicadas sob `/painel/`

Serão adicionadas rotas:

- `/painel/admissoes/` → `admission_chart`
- `/painel/obitos/` → `death_chart`

A escolha mantém coerência com `/painel/altas/` e separa gráficos das listagens
existentes `/admissoes/` e `/obitos/`.

### 2) Links nas listagens

As páginas de listagem passarão a oferecer botão secundário:

- `Ver gráfico de admissões` em `admission_list.html`;
- `Ver gráfico de óbitos` em `death_list.html`.

O clique nos números do dashboard pode continuar levando às listagens filtradas
pela última data disponível, conforme comportamento descrito pelo usuário.

### 3) Helper genérico para séries diárias

Criar helper privado, por exemplo `_daily_count_chart_context`, recebendo:

- modelo diário (`DailyAdmissionCount` ou `DailyDeathCount`);
- número de dias solicitado;
- rótulos/títulos específicos;
- nome da URL de retorno para listagem.

O helper deve:

1. parsear `?dias=N` com fallback para `90`;
2. buscar até `N` registros anteriores ao dia corrente, em ordem cronológica;
3. montar `chart_data.labels` e `chart_data.counts`;
4. montar `weekday_avg` em ordem fixa Seg..Dom;
5. incluir `period_options` e metadados textuais para o template.

### 4) Template compartilhado preferencial

Preferir um template compartilhado, por exemplo
`services_portal/daily_event_chart.html`, parametrizado por contexto:

- `page_title`;
- `daily_chart_title`;
- `weekday_chart_title`;
- `empty_message`;
- `list_url_name` ou URL resolvida no backend;
- `chart_data`;
- `weekday_avg`.

Isso evita duplicar JavaScript e facilita manter consistência visual entre
admissões e óbitos.

### 5) Contrato de dados view-template

`chart_data`:

- `labels: list[str]` no formato `dd/mm/YYYY`;
- `counts: list[int]`;
- `dataset_label: str` (`Admissões` ou `Óbitos`).

`weekday_avg`:

- `labels: ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']`;
- `values: list[float]`;
- `counts: list[int]`;
- `has_data: bool`.

Metadados:

- `dias: int`;
- `period_options: list[int]`;
- `list_url: str`;
- `list_link_label: str`.

### 6) Estado vazio e séries esparsas

Quando não houver registros no período:

- a página deve retornar HTTP 200;
- o gráfico diário deve mostrar mensagem de ausência de dados;
- o gráfico semanal não deve renderizar canvas quebrado;
- `weekday_avg` deve conter zeros e `has_data=False`.

Quando houver poucos dias ou buckets semanais vazios:

- valores ausentes por weekday devem ser `0.0`;
- `counts` deve explicitar `0` para buckets sem observação.

## TDD Strategy

1. RED para rotas autenticadas:
   - anônimo redireciona;
   - usuário autenticado acessa admissões e óbitos com HTTP 200.
2. RED para contrato de contexto:
   - `chart_data.labels/counts` respeita `?dias=`;
   - `weekday_avg.labels` fica em ordem Seg..Dom;
   - médias são calculadas corretamente para fixture determinística.
3. RED para navegação:
   - listagem de admissões contém link para gráfico;
   - listagem de óbitos contém link para gráfico.
4. GREEN com helpers genéricos e template compartilhado.
5. Refactor controlado para nomes, pequenas duplicações e estados vazios.

## Files Expected to Change

- `apps/services_portal/views.py`
- `apps/services_portal/urls.py`
- `apps/services_portal/templates/services_portal/admission_list.html`
- `apps/services_portal/templates/services_portal/death_list.html`
- `apps/services_portal/templates/services_portal/daily_event_chart.html`
- `tests/unit/test_services_portal_dashboard.py`

## Risks and Trade-Offs

- **Duplicação versus refactor da página de altas:** este change não deve
  refatorar a página de altas para reduzir risco. A generalização deve focar as
  novas páginas.
- **Óbitos são naturalmente esparsos:** manter mensagem clara e média semanal
  com `n` no tooltip reduz risco de interpretação exagerada.
- **Chart.js via CDN:** a página de altas já usa esse padrão; manter o mesmo
  evita nova dependência operacional.
