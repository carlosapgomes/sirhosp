# provider-cost-exchange-health Specification

## ADDED Requirements

### Requirement: UI indica origem do custo (real vs estimado)

O sistema SHALL exibir um indicador visual da origem de cada valor de custo
apresentado ao usuário.

#### Scenario: Custo real exibe badge verde

- **WHEN** o `SummaryPipelineRun` tem `phase1_cost_total` ou
  `phase2_cost_total` preenchido com custo real do provider
- **THEN** a UI exibe badge "Real (provider)" em verde ao lado do valor

#### Scenario: Custo estimado exibe badge amarelo

- **WHEN** o custo foi calculado por estimativa de tokens (provider não
  retornou custo)
- **THEN** a UI exibe badge "Estimado" em amarelo ao lado do valor

#### Scenario: Custo zero com fase reutilizada não exibe badge

- **WHEN** a Fase 1 foi reutilizada (`phase1_reused=True`)
- **THEN** a UI exibe badge "Reutilizado" (azul) em vez de badge de origem
  de custo

### Requirement: UI exibe saúde da cotação USD/BRL

O sistema SHALL exibir o status da cotação USD/BRL na página de status do
resumo.

#### Scenario: Cotação disponível

- **WHEN** existe ao menos um `ExchangeRateSnapshot` no banco
- **THEN** a UI exibe "USD → BRL: R$ X,XX (via <provider> em <data>)"
- **AND** a conversão BRL é calculada com a taxa mais recente

#### Scenario: Cotação indisponível

- **WHEN** não existe nenhum `ExchangeRateSnapshot` no banco
- **THEN** a UI exibe "(câmbio indisponível)" em amarelo
- **AND** os valores BRL são exibidos como "---"
