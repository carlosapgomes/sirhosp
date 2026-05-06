# Tasks

## 1. Slice STC-S1 — Descoberta técnica (pesquisa, sem código)

- [x] 1.1 Inspecionar resposta real do OpenRouter (fase 1 e fase 2) para mapear campo de custo faturado
- [x] 1.2 Consultar documentação oficial do Frankfurter (`frankfurter.dev`) para endpoint atual
- [x] 1.3 Consultar documentação oficial do ExchangeRate-API (`exchangerate-api.com`) para schema de resposta atual
- [x] 1.4 Documentar contrato de parsing no report do slice (campo exato, tipo, exemplo)

## 2. Slice STC-S2 — Fase 2: custo real do provider

- [x] 2.1 Alterar `call_llm_phase2_render` para extrair `cost_usd_reported` da resposta da API
- [x] 2.2 Adicionar `cost_usd_estimated` (mantendo cálculo atual como fallback)
- [x] 2.3 Adicionar campo `cost_is_reported` (bool) no retorno
- [x] 2.4 Migration: adicionar `cost_usd_reported`, `cost_usd_estimated`, `cost_is_reported` em `SummaryPipelineStepRun`
- [x] 2.5 Atualizar `execute_two_phase_pipeline` para persistir novos campos na fase 2
- [x] 2.6 Testes unitários: resposta com custo real, resposta sem custo (fallback)
- [x] 2.7 Testes de integração: pipeline com custo real na fase 2
- [x] 2.8 Rodar quality gate (`./scripts/test-in-container.sh quality-gate`)

## 3. Slice STC-S3 — Fase 1: custo cumulativo por chunk

- [x] 3.1 Alterar `call_llm_gateway` para retornar `input_tokens`, `output_tokens`, `cost_usd_reported`, `cost_usd_estimated`
- [x] 3.2 Adicionar campos `input_tokens`, `output_tokens`, `cost_usd_reported`, `cost_usd_estimated` em `AdmissionSummaryVersion` (migration)
- [x] 3.3 Alterar `execute_summary_run` para persistir tokens e custo em cada `AdmissionSummaryVersion`
- [x] 3.4 Migration: renomear `SummaryPipelineStepRun.cost_total` → `cost_usd_reported`, adicionar `cost_usd_estimated`
- [x] 3.5 Atualizar `execute_two_phase_pipeline` para usar soma de `cost_usd_reported` dos versions na fase 1
- [x] 3.6 Testes unitários: `_compute_phase1_cost_from_tokens` com soma multi-chunk
- [x] 3.7 Testes de integração: run com 3 chunks → fase1 total = soma dos 3 custos
- [x] 3.8 Rodar quality gate

## 4. Slice STC-S4 — Vínculo PipelineRun → SummaryRun

- [x] 4.1 Migration: adicionar FK `summary_run` em `SummaryPipelineRun` (nullable)
- [x] 4.2 Alterar `execute_two_phase_pipeline` para preencher `summary_run` na criação
- [x] 4.3 Alterar `run_status` view para consultar pipeline por `summary_run=run`
- [x] 4.4 Alterar `summary_read` view para consultar pipeline por `summary_run=run`
- [x] 4.5 Testes de integração HTTP: 2 runs da mesma admissão, garantir custo correto por página
- [x] 4.6 Rodar quality gate

## 5. Slice STC-S5 — Câmbio USD/BRL: correção de providers

- [x] 5.1 Corrigir `_DEFAULT_PRIMARY_URL` para `api.frankfurter.dev/v1/latest?...`
- [x] 5.2 Corrigir parser do fallback: `data["rates"]["BRL"]` → `data["conversion_rates"]["BRL"]`
- [x] 5.3 Melhorar logs de erro com detalhe da causa (HTTP status, chave ausente)
- [x] 5.4 Testes unitários: primary OK, primary 404 + fallback OK, ambos falham
- [x] 5.5 Executar `sync_exchange_rates` no container dev para validar
- [x] 5.6 Rodar quality gate

## 6. Slice STC-S6 — Transparência na UI

- [x] 6.1 Template `run_status.html`: adicionar badge "Real"/"Estimado" por fase
- [x] 6.2 Template `run_status.html`: exibir provider e data da última cotação
- [x] 6.3 Template `logs_admin.html`: adicionar coluna/badge de origem do custo
- [x] 6.4 View `run_status`: passar `cost_is_reported` e `latest_rate_info` ao contexto
- [x] 6.5 Testes de integração HTTP: renderização dos badges nos estados (real, estimado, reutilizado)
- [x] 6.6 Rodar quality gate
