# real-provider-cost Specification

## Purpose

Define a priorização do custo real do provider sobre estimativas e a persistência cumulativa por chunk/version da Fase 1.

## Requirements

### Requirement: Custo real do provider é priorizado sobre estimativa

O sistema SHALL extrair o custo faturado em USD da resposta da API do
provider LLM sempre que disponível, e usar estimativa por tokens apenas
como fallback.

#### Scenario: Provider retorna custo faturado

- **WHEN** a chamada LLM é concluída com sucesso
- **AND** a resposta contém custo faturado em USD (campo `cost`, `usage.cost`
  ou `pricing.total`)
- **THEN** o sistema persiste `cost_usd_reported` com o valor retornado
- **AND** o sistema também persiste `cost_usd_estimated` com o valor calculado
  localmente por tokens para auditoria

#### Scenario: Provider não retorna custo faturado

- **WHEN** a chamada LLM é concluída com sucesso
- **AND** a resposta NÃO contém custo faturado
- **THEN** o sistema persiste `cost_usd_reported` como `0.00`
- **AND** o sistema persiste `cost_usd_estimated` com o valor calculado
  localmente por tokens
- **AND** o sistema marca a origem do custo como `estimated`

### Requirement: Custo da Fase 1 é cumulativo por chunk

O sistema SHALL capturar tokens e custo em cada chamada da Fase 1 (um por
chunk/window) e acumular os valores no `SummaryPipelineRun`.

#### Scenario: Fase 1 com múltiplos chunks

- **WHEN** a Fase 1 processa 3 chunks com sucesso
- **AND** cada chunk retorna custo real do provider
- **THEN** o `SummaryPipelineRun.phase1_cost_total` é igual à soma dos custos
  reais dos 3 chunks
- **AND** `SummaryPipelineStepRun` da Fase 1 totaliza `input_tokens` e
  `output_tokens` de todos os chunks

#### Scenario: Fase 1 com chunk sem custo real

- **WHEN** um chunk da Fase 1 não retorna custo real do provider
- **THEN** esse chunk contribui com `cost_usd_estimated` para o total
- **AND** a soma final da Fase 1 reflete valores mistos (real + estimado)
  corretamente

### Requirement: Tokens da Fase 1 são persistidos por version

O sistema SHALL persistir `input_tokens` e `output_tokens` em cada
`AdmissionSummaryVersion` criada durante a Fase 1.

#### Scenario: Version criada com tokens

- **WHEN** um chunk da Fase 1 é concluído com sucesso
- **THEN** o `AdmissionSummaryVersion` correspondente registra `input_tokens`
  e `output_tokens` não-nulos
- **AND** os valores correspondem ao `usage` retornado pela API

#### Scenario: Version sem tokens (API não retornou usage)

- **WHEN** a API não retorna `usage` na resposta
- **THEN** o `AdmissionSummaryVersion` registra `input_tokens=0` e
  `output_tokens=0`
- **AND** o sistema não falha nem interrompe o pipeline
