# Design: ingestion-run-expanded-metrics-dashboard

## Context

O `IngestionRun` já registra estado terminal e contadores de volume, porém a operação ainda carece de observabilidade de ciclo completo. Na prática, quando há lentidão, fila acumulada, timeout ou erro intermitente de conector, o diagnóstico exige leitura manual de logs e inspeção pontual de runs individuais.

A necessidade agora é dupla:

1. **Coletar métricas mais completas por run** (do enfileiramento até o término, incluindo falhas/timeout e etapas internas).
2. **Disponibilizar consulta operacional** para usuário de operação (dashboard + página dedicada) e para suporte técnico (Django Admin).

Restrições relevantes da fase 1:

- manter monólito Django + PostgreSQL;
- não introduzir Celery/Redis/stack externa de observabilidade;
- preservar simplicidade operacional e baixo custo de manutenção.

## Goals / Non-Goals

**Goals:**

- Tornar cada `IngestionRun` observável do início ao fim com timestamps e latências claras.
- Padronizar métricas entre intents existentes (`admissions_only`, `full_sync`, `census_extraction`).
- Expor visão agregada no portal (cards + drill-down) e visão operacional no admin.
- Manter rastreabilidade de motivo de falha/timeout sem depender de parsing manual de mensagem livre.

**Non-Goals:**

- Não substituir logs aplicacionais por tracing distribuído.
- Não criar pipeline de analytics externo (BI, data warehouse, Grafana).
- Não alterar semântica clínica de ingestão de eventos/internações.

## Decisions

### D1) Evoluir `IngestionRun` como fonte primária de métricas (em vez de criar ledger separado já no primeiro passo)

**Decisão**: adicionar campos de ciclo de vida e resultado diretamente em `IngestionRun`.

Campos-alvo (nomes finais podem variar na implementação):

- `queued_at` (momento de criação/enfileiramento)
- `processing_started_at` (momento em que worker assume o run)
- `finished_at` (já existente)
- `failure_reason` (enum operacional)
- `timed_out` (bool)
- `worker_label` (opcional: hostname/identificador do worker)

Métricas derivadas (não necessariamente persistidas):

- `queue_latency_seconds = processing_started_at - queued_at`
- `processing_duration_seconds = finished_at - processing_started_at`
- `total_duration_seconds = finished_at - queued_at`

**Alternativa considerada**: criar já uma tabela nova de métricas agregadas por run.
**Por que não agora**: aumenta complexidade de escrita e consistência transacional no worker sem necessidade imediata. Nesta fase, `IngestionRun` é suficiente como registro canônico.

### D2) Introduzir tabela auxiliar opcional para estágio (`IngestionRunStageMetric`)

**Decisão**: modelar métricas por etapa em relação 1:N com `IngestionRun`, para capturar início/fim/status de estágios críticos:

- `admissions_capture`
- `gap_planning`
- `evolution_extraction`
- `ingestion_persistence`

Campos-alvo:

- `stage_name`
- `started_at`
- `finished_at`
- `status` (`succeeded|failed|skipped`)
- `details_json` (contadores ou contexto pequeno)

**Alternativa considerada**: armazenar estágios em `JSONField` dentro do próprio `IngestionRun`.
**Por que não**: pior para consulta analítica/filtros e mais difícil de indexar para operação.

### D3) Taxonomia de falha operacional explícita

**Decisão**: normalizar categorias de falha para consulta e card de saúde:

- `timeout`
- `source_unavailable`
- `invalid_payload`
- `unexpected_exception`
- `validation_error`

`error_message` textual permanece para diagnóstico detalhado, mas dashboards usam categoria.

**Alternativa considerada**: manter só `error_message` livre.
**Por que não**: dificulta agregação confiável por tipo de problema.

### D4) Superfície de consulta em duas camadas

**Decisão**:

- **Camada 1 (Dashboard)**: cards simples (últimas 24h/7d) com KPIs operacionais:
  - runs concluídos;
  - taxa de sucesso;
  - tempo médio/p95 de execução;
  - percentual de timeout.
- **Camada 2 (Página de métricas)**: filtro por período, intent, status e failure_reason; tabela de runs e visão resumida por agregação.
- **Admin**: listagem e filtros para suporte com export rápido/manual.

**Alternativa considerada**: só admin sem UI de portal.
**Por que não**: não atende stakeholders operacionais não técnicos e reduz visibilidade diária.

### D5) Preservar simplicidade operacional da fase 1

**Decisão**: toda implementação permanece no stack atual (Django ORM + templates + PostgreSQL), sem infra extra.

**Como preserva simplicidade**:

- sem novos serviços de infraestrutura;
- sem agentes de coleta externos;
- sem pipeline assíncrono adicional além do worker já existente.

## Risks / Trade-offs

- **[Instrumentação incompleta em paths de erro]** → Mitigar com testes de integração cobrindo timeout, falha em estágio inicial e exceção inesperada.
- **[Aumento de escrita no banco por run]** → Mitigar mantendo número de estágios pequeno e payload de detalhes enxuto.
- **[Consultas lentas em janela longa]** → Mitigar com índices em `queued_at`, `processing_started_at`, `status`, `intent`, `failure_reason`.
- **[Confusão de semântica entre `started_at` legado e novos campos]** → Mitigar com migração de dados e documentação clara de depreciação/uso.

## Migration Plan

1. Criar migração para novos campos de `IngestionRun`.
2. (Se aprovado no slice) criar modelo `IngestionRunStageMetric` + índices.
3. Backfill mínimo para runs existentes:
   - `queued_at <- started_at` (quando aplicável);
   - `processing_started_at <- started_at` apenas quando não houver dado melhor.
4. Atualizar worker/commands para gravar os campos novos no fluxo normal e em falha.
5. Atualizar Django Admin com filtros/list_display.
6. Adicionar cards no dashboard + página detalhada de métricas.
7. Validar com testes e quality gate containerizado.

Rollback: remover leitura dos novos campos na UI/admin; manter migração reversível para o novo modelo auxiliar se necessário.

## Open Questions

1. P95 deve ser calculado em query SQL (percentile_cont) ou em Python na aplicação inicialmente?
2. Janela padrão dos cards: últimas 24h ou 7 dias?
3. Precisamos de retenção/purga de runs antigos nesta mesma change ou em change separado?
4. Página de métricas ficará em `services_portal` ou módulo dedicado (`apps/ingestion/views_metrics.py`)?
