# Design

## Context

O SIRHOSP gera resumos clínicos em duas fases (Fase 1: base canônica por
chunks; Fase 2: render final). Hoje o custo exibido é calculado localmente
com tabela fixa de preço por token — não reflete o valor real faturado pelo
provider.

O comando `sync_exchange_rates` está quebrado (URL primária 404, parser de
fallback incompatível), e não há agendamento automático. A UI mostra
"(câmbio indisponível)" porque a tabela `ExchangeRateSnapshot` está vazia.

Além disso, `SummaryPipelineRun` referenceia `Admission` mas não `SummaryRun`,
criando risco de leak de custo entre runs distintos da mesma internação.

## Goals / Non-Goals

**Goals:**

- Extrair custo real faturado (USD) da resposta do provider LLM.
- Persistir custo por chunk na Fase 1 e acumular no pipeline.
- Vincular `SummaryPipelineRun` ao `SummaryRun` original.
- Corrigir providers de câmbio USD/BRL.
- Exibir origem do custo (real vs estimado) na UI.

**Non-Goals:**

- Não alterar o fluxo do usuário (gerar/atualizar/regenerar resumo).
- Não trocar de provider LLM nem de endpoint de câmbio.
- Não introduzir Celery, Redis ou microserviços.
- Não alterar a política de retenção de snapshots de câmbio.

## Decisions

### D1: Contrato de custo unificado

Todo step run e version passa a ter dois campos de custo:

- `cost_usd_reported`: custo faturado retornado pelo provider (prioritário).
- `cost_usd_estimated`: custo calculado localmente por tokens (fallback).

O campo legado `cost_total` (existente em `SummaryPipelineStepRun`) será
**substituído** por `cost_usd_reported` com migration que copia valor
existente e depois renomeia. `cost_usd_estimated` será adicionado.

**Alternativa considerada:** manter `cost_total` como está e adicionar
flag `cost_is_estimated`. Rejeitada porque:

- perderíamos o valor estimado quando o real existe.
- não teríamos os dois valores lado a lado para auditoria.

### D2: Extração do custo real — campo `usage` da OpenAI/OpenRouter

OpenRouter e OpenAI-compatíveis retornam custo no objeto `usage` da resposta:

```json
{
  "usage": {
    "prompt_tokens": 500,
    "completion_tokens": 300,
    "total_tokens": 800,
    "completion_tokens_details": {...},
    "prompt_tokens_details": {...}
  }
}
```

**OpenRouter** adicionalmente inclui `cost` no campo raiz ou em headers
personalizados. O campo mais comum é `usage.cost` (em USD, string ou number).
O gateway tentará extrair nesta ordem:

1. `completion.cost` (campo raiz — OpenRouter)
2. `completion.usage.cost` (aninhado)
3. `completion.pricing.total` (variação)
4. Fallback → estimativa por tokens

Se o valor vier como string, converte para Decimal.

### D3: Captura de custo na Fase 1 (multi-chunk)

Hoje `call_llm_gateway` retorna apenas conteúdo + `_meta`. Será estendido
para retornar também `input_tokens`, `output_tokens`, `cost_usd` (real),
`cost_usd_estimated` (estimado).

O `execute_summary_run` passará esses valores para `AdmissionSummaryVersion`
no momento da criação. Cada version ganha campos `input_tokens`,
`output_tokens`, `cost_usd_reported`, `cost_usd_estimated`.

A pipeline soma os valores de todos os versions para preencher
`SummaryPipelineRun.phase1_cost_total`.

### D4: Vínculo PipelineRun → SummaryRun (FK explícita)

`SummaryPipelineRun` ganha `summary_run = ForeignKey(SummaryRun, null=True)`.
Na criação da pipeline (`execute_two_phase_pipeline`), o `run` é vinculado.

Views `run_status` e `summary_read` passam a consultar:

```python
pipeline_run = SummaryPipelineRun.objects.filter(
    summary_run=run  # em vez de admission=run.admission
).first()
```

**Alternativa considerada:** usar `OneToOneField`. Rejeitada porque um
SummaryRun pode não ter pipeline (execução legada sem `--pipeline`) e um
pipeline pode ser retentado (embora raro, FK permite).

### D5: Correção dos providers de câmbio

**Provider de câmbio:**

- **Frankfurter (primário):** URL `.../latest` retorna 404. Correção: trocar para `.../v1/latest`.
- **ExchangeRate-API (fallback):** Espera `data["rates"]["BRL"]`. Correção: esperar `data["conversion_rates"]["BRL"]`.

Ambos funcionam sem `follow_redirects` — são endpoints diretos.

### D6: Transparência na UI

Dois novos elementos visuais:

1. **Badge de origem do custo**: "Real (provider)" verde / "Estimado" amarelo.
   Aparece ao lado de cada valor de custo (Fase 1, Fase 2, Total).
2. **Saúde do câmbio**: data e provider da última cotação disponível.
   Aparece no card de custo da página de status.

## Risks / Trade-offs

- **[Risco] Provider pode não retornar custo**: mitigado com fallback para
  estimativa por tokens (comportamento atual como safety net).
- **[Risco] Migrations com rename de campo**: backup implícito via migration
  reversível do Django. Campo legado `cost_total` será renomeado, não
  deletado.
- **[Risco] Agendamento do câmbio depende de systemd/cron externo**: vamos
  documentar o `sync_exchange_rates` no README e no deploy/README.md.
- **[Trade-off] Dois campos de custo aumentam superfície do modelo**: aceito
  em troca de rastreabilidade completa (real vs estimado).

## Migration Plan

1. **Migrations**: novas migrations para FK `summary_run`, campos
   `cost_usd_reported`, `cost_usd_estimated`, `input_tokens`, `output_tokens`
   em `AdmissionSummaryVersion`. Rename `cost_total` → `cost_usd_reported`
   em `SummaryPipelineStepRun` (com data migration copiando valor).
2. **Deploy**: migration automática no startup do container (já configurado).
3. **Rollback**: migrations são reversíveis. Dados de custo podem ser
   recalculados via reexecução do pipeline se necessário.
4. **Agendamento**: após deploy, configurar `systemd timer` ou entrada em
   `run_due_jobs` para `sync_exchange_rates` diário.

## Open Questions

- **Q1**: OpenRouter retorna `cost` em qual campo exato? Verificar no Slice S1
  com chamada real.
- **Q2**: O campo `cost` do OpenRouter é string ou number? A resposta real
  determinará a conversão (Decimal(str) vs Decimal).
- **Q3**: O endpoint Frankfurter `/v1/latest` é estável ou pode mudar?
  Documentação oficial será consultada no Slice S1.
