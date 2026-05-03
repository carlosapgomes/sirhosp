# Change Proposal: discharge-chart-weekend-weekday-insights

## Why

A página `/painel/altas/` já exibe série diária de altas com barras e médias
móveis. Porém, hoje não há indicação visual rápida de sazonalidade por dia da
semana no gráfico principal.

Na prática operacional, duas perguntas aparecem com frequência:

1. as oscilações observadas estão associadas a fins de semana?
2. qual é a média típica de altas por dia da semana?

Sem essas pistas, o usuário precisa inferir manualmente no eixo temporal ou
usar exportações externas.

## What Changes

1. Destacar visualmente barras de sábado e domingo no gráfico principal
   (`/painel/altas/`) usando tons específicos, mantendo dias úteis no tom atual.
2. Adicionar um segundo gráfico na mesma página, abaixo do atual, com
   **média de altas por dia da semana** (Seg..Dom), calculada a partir do
   mesmo período selecionado em `?dias=N`.
3. Preservar o comportamento atual do gráfico principal:
   - período padrão e seletor de período;
   - exclusão do dia corrente da série;
   - linhas de média móvel já existentes.

## Scope

- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/discharge_chart.html`
- `tests/unit/test_services_portal_dashboard.py`

## Non-Goals

- Não criar nova rota/página para o gráfico semanal.
- Não alterar pipeline de ingestão de altas.
- Não introduzir nova dependência frontend/backend.
- Não trocar a estratégia das médias móveis existentes.

## Risks

- Poluição visual se contraste de cores for excessivo.
- Interpretação ambígua se a legenda não explicitar fim de semana.
- Média semanal distorcida quando há poucos dias de histórico para algum
  weekday.

## Mitigations

- Manter paleta próxima ao padrão atual e adicionar legenda explícita.
- Fixar ordem Seg..Dom no gráfico de médias.
- Exibir zero apenas para weekdays sem dados no período, com testes cobrindo
  esse caso.

## Capabilities

### Modified Capabilities

- `daily-discharge-tracking`: amplia visualização do gráfico com destaque de
  fim de semana e novo resumo estatístico por dia da semana na mesma página.

## Impact

- Melhor leitura de padrão semanal sem exigir nova navegação.
- Menor custo cognitivo para identificar comportamento de sábado/domingo.
- Visão complementar agregada para decisão operacional diária.
