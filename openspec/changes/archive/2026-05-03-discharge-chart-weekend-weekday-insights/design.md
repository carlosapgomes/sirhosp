# Design: discharge-chart-weekend-weekday-insights

## Context

Atualmente, a view `discharge_chart` entrega para o template:

- `labels` (datas);
- `counts` (barras de altas);
- `sma7`, `ema7`, `sma30`.

O template renderiza um único Chart.js (barras + linhas), sem distinção visual
entre weekdays e sem agregação por dia da semana.

## Goals / Non-Goals

### Goals

1. Diferenciar barras de sábado/domingo no gráfico principal.
2. Exibir um segundo gráfico com média de altas por dia da semana na mesma
   página, abaixo do gráfico principal.
3. Reaproveitar o mesmo recorte de período já selecionado em `?dias=N`.
4. Manter compatibilidade com dados vazios e autenticação já existente.

### Non-Goals

- alterar rota `/painel/altas/`;
- alterar origem dos dados (`DailyDischargeCount`);
- alterar modelos/migrations;
- criar endpoint/API separado.

## Decisions

### 1) Weekend highlight via metadados por barra

A view passará a serializar, por ponto da série:

- `is_weekend`: `True` para sábado/domingo;
- `weekday_short`: abreviação opcional para uso futuro em tooltip
  (`seg`, `ter`, `qua`, `qui`, `sex`, `sáb`, `dom`).

No frontend, o dataset de barras usará arrays de cor por índice:

- weekday: cor atual (azul translúcido);
- sábado: tom distinto 1;
- domingo: tom distinto 2.

Isso evita múltiplos datasets e preserva alinhamento com médias móveis.

### 2) Agregação de média por dia da semana no backend

A agregação será feita em Python na própria `discharge_chart`, a partir da
lista `entries_recent` já consultada para o gráfico principal.

Estratégia:

1. inicializar buckets Seg..Dom;
2. acumular soma e quantidade por weekday;
3. calcular média arredondada em 1 casa decimal;
4. gerar arrays para o template em ordem fixa Seg..Dom.

Formato no contexto:

- `weekday_avg.labels`: `['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']`
- `weekday_avg.values`: `[float, ...]`
- `weekday_avg.counts`: quantidade de observações por weekday no período.

### 3) Segundo gráfico abaixo do atual

No mesmo template, após o card do gráfico principal, será incluído novo card
com `<canvas id="weekdayAverageChart">`.

- tipo: `bar`;
- eixo X: Seg..Dom;
- eixo Y: média de altas;
- cor: paleta discreta com destaque moderado para sábado/domingo;
- tooltip: incluir `n` de observações (`weekday_avg.counts[index]`).

### 4) Comportamento com dados vazios

Se não houver `chart_data.counts`, ambos os gráficos não devem quebrar.
A página segue mostrando estado vazio atual. O segundo gráfico só renderiza
quando houver `weekday_avg.values` com algum ponto > 0 ou observações > 0.

## Data contract (view -> template)

`chart_data` (existente + novo):

- `labels: list[str]`
- `counts: list[int]`
- `sma7: list[float | None]`
- `ema7: list[float | None]`
- `sma30: list[float | None]`
- `weekend_flags: list[bool]`
- `weekday_short: list[str]`

`weekday_avg` (novo):

- `labels: list[str]` (Seg..Dom)
- `values: list[float]`
- `counts: list[int]`

## TDD strategy

1. RED (view): testes de contexto para `weekend_flags`, `weekday_avg.labels`,
   `weekday_avg.values` e ordem Seg..Dom.
2. GREEN (view): implementar helpers puros no backend.
3. RED (template): testes de conteúdo HTML/JS para presença do segundo canvas
   e uso de `weekend_flags` no dataset de barras.
4. GREEN (template): implementar JS e legenda.
5. REFACTOR: limpar nomes de helpers e reduzir duplicação.

## Risks and trade-offs

- **Risco de semântica visual fraca**: se as cores forem muito próximas.
  Mitigação: legenda explícita com "dia útil", "sábado", "domingo".
- **Risco de média enganosa com pouca amostra**: p.ex., período curto.
  Mitigação: tooltip com `n` por weekday.
- **Risco de regressão no gráfico atual**: mitigado por testes de contexto já
  existentes e novos asserts para chaves antigas (`sma7`, `ema7`, `sma30`).
