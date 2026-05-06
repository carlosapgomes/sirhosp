# Proposal

## Why

Hoje o custo exibido na UI para geração de resumos é **estimado** (calculado
localmente a partir de tokens, com tabela de preço fixa), e não o custo real
faturado pelo provider LLM (ex.: OpenRouter). A Fase 1 nunca exibe custo
porque os tokens não são salvos por chunk. A cotação USD/BRL está indisponível
porque o comando `sync_exchange_rates` falha silenciosamente (URL primária
inválida + parser do fallback incompatível). Além disso, há risco de a UI
mostrar custo do run errado quando há múltiplos runs da mesma internação.

## What Changes

- **Custo real do provider**: Fase 1 e Fase 2 passam a extrair custo faturado
  em USD da resposta da API quando disponível, com fallback para estimativa
  por tokens.
- **Fase 1 cumulativa**: tokens e custo passam a ser capturados por chunk e
  acumulados no `SummaryPipelineRun`.
- **Vínculo pipeline-run**: `SummaryPipelineRun` ganha FK para `SummaryRun`,
  e as views de status/leitura passam a consultar pelo run correto.
- **Câmbio USD/BRL funcional**: endpoint primário Frankfurter corrigido
  (`/v1/latest`), parser do fallback ExchangeRate-API adaptado para
  `conversion_rates`.
- **Transparência na UI**: badge indicando se custo é real ou estimado, e
  exibição do provedor/data da última cotação.

## Capabilities

### New Capabilities

- `real-provider-cost`: Extração de custo faturado em USD da resposta do
  provider LLM (OpenRouter / OpenAI-compatível) com fallback para estimativa
  por tokens.
- `provider-cost-exchange-health`: Transparência na UI sobre origem do custo
  (real vs estimado) e saúde da cotação USD/BRL.

### Modified Capabilities

- `summary-llm-traceability`: Custo por fase passa a ser `cost_usd_reported`
  (prioritário) + `cost_usd_estimated` (fallback), com persistência da fonte
  do custo. Pipeline run vincula-se diretamente ao SummaryRun.
- `admission-progressive-summary`: Fase 1 passa a capturar e acumular custo
  real por chunk. Pipeline run referenciável pelo SummaryRun de origem.

## Impact

- **apps/summaries/models.py**: novos campos em `SummaryPipelineStepRun`,
  `SummaryPipelineRun`, `AdmissionSummaryVersion`; nova FK `summary_run` em
  `SummaryPipelineRun`.
- **apps/summaries/services.py**: `execute_summary_run` e `call_llm_gateway`
  precisam retornar/persistir tokens e custo; `execute_two_phase_pipeline`
  passa a acumular custo real.
- **apps/summaries/llm_gateway.py**: `call_llm_gateway` e
  `call_llm_phase2_render` passam a extrair custo da resposta.
- **apps/summaries/views.py**: `run_status` e `summary_read` consultam
  pipeline por `SummaryRun`, não por `Admission`.
- **apps/summaries/management/commands/sync_exchange_rates.py**: correção de
  endpoint e parser.
- **Templates**: `run_status.html`, `summary_read.html`, `logs_admin.html` —
  novo badge de origem do custo.
- **Banco**: novas migrações (FK + campos de custo).
- **Sem novas dependências externas**: httpx e openai já estão no projeto.
