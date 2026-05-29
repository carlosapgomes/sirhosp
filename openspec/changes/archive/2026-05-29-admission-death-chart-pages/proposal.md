# Change Proposal: admission-death-chart-pages

## Why

O dashboard já mostra os totais de altas, admissões e óbitos para a última data
com dados disponíveis. Ao clicar nesses números, o usuário acessa páginas de
listagem com filtro por data. Hoje, porém, apenas a página de altas oferece uma
opção para análise visual em página dedicada de gráficos.

Essa assimetria dificulta responder rapidamente perguntas operacionais simples:

1. como admissões e óbitos variam ao longo dos últimos dias?
2. existe padrão por dia da semana para admissões ou óbitos?
3. a leitura visual dessas séries está disponível sem exportação manual?

A mudança amplia a mesma experiência já validada em altas para admissões e
óbitos, com escopo deliberadamente enxuto.

## What Changes

1. Criar página dedicada de gráficos para admissões, acessível a partir da
   listagem de admissões.
2. Criar página dedicada de gráficos para óbitos, acessível a partir da
   listagem de óbitos.
3. Em cada nova página, renderizar somente os dois primeiros gráficos já usados
   conceitualmente em altas:
   - série diária em barras;
   - média por dia da semana em barras.
4. Reaproveitar dados já persistidos em `DailyAdmissionCount` e
   `DailyDeathCount`.
5. Manter seletor de período compatível com o padrão da página de altas
   (`30`, `60`, `90`, `180`, `365` dias), com padrão de `90` dias.

## Scope

- `apps/services_portal/views.py`
- `apps/services_portal/urls.py`
- templates de listagem de admissões e óbitos
- novo template genérico ou templates dedicados para gráficos de admissões e
  óbitos
- testes unitários do portal
- artefatos OpenSpec desta change

## Non-Goals

- Não alterar ingestão, parsing ou persistência de admissões/óbitos.
- Não criar novas tabelas, migrations ou comandos de atualização.
- Não reproduzir na fase inicial os gráficos adicionais de altas, como
  distribuição horária por especialidade e tabela de resumo.
- Não alterar o comportamento do clique nos cards do dashboard: os cards podem
  continuar abrindo as listagens por data.
- Não introduzir nova dependência frontend/backend.

## Assumptions

- As novas rotas serão `/painel/admissoes/` e `/painel/obitos/`, seguindo o
  padrão existente `/painel/altas/`.
- O primeiro gráfico das novas páginas será uma série diária em barras simples,
  sem obrigatoriedade de médias móveis no MVP desta feature.
- O link para gráficos será exibido nas páginas de listagem de admissões e
  óbitos, de modo análogo ao botão existente na listagem de altas.

## Risks

- Duplicação de lógica entre os três tipos de evento se a implementação copiar
  a view de altas sem parametrização mínima.
- Ambiguidade visual se os títulos ou legendas não diferenciarem claramente
  altas, admissões e óbitos.
- Séries esparsas de óbitos podem produzir gráfico semanal pouco informativo.

## Mitigations

- Extrair helpers pequenos e testáveis para montar dados de série diária e
  média por dia da semana a partir de qualquer modelo diário compatível.
- Usar títulos e labels específicos por evento: `Admissões por Dia`,
  `Média de Admissões por Dia da Semana`, `Óbitos por Dia` e
  `Média de Óbitos por Dia da Semana`.
- Preservar estados vazios claros e sem scripts quebrados.

## Capabilities

### Added Capabilities

- `daily-operational-event-charts`: visualização diária e por dia da semana
  para contadores operacionais de admissões e óbitos.

### Modified Capabilities

- `services-portal-navigation`: adiciona navegação das listagens de admissões e
  óbitos para suas páginas dedicadas de gráficos.

## Impact

- Diretoria e gestão de leitos passam a comparar visualmente admissão, alta e
  óbito com menor custo cognitivo.
- Qualidade e prontuários ganham leitura rápida de sazonalidade semanal em
  eventos críticos.
- A mudança permanece compatível com a simplicidade operacional da fase 1,
  usando apenas Django templates, Chart.js já empregado e dados já existentes.
