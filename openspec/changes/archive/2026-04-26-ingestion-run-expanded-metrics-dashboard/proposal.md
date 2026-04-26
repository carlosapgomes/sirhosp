# ingestion-run-expanded-metrics-dashboard

## Why

Hoje o `IngestionRun` já registra status e contadores básicos, mas ainda não dá visibilidade completa do ciclo operacional de cada execução (tempo em fila, tempo de processamento por etapa, motivo categorizado de falha/timeout, throughput e tendências). Isso limita diagnóstico rápido de gargalos, acompanhamento de estabilidade e prestação de contas operacional no portal.

Também falta uma superfície de consulta pensada para operação: hoje o status é centrado por run individual. Para gestão diária, precisamos visão agregada (cards) e navegação para detalhe (filtros por período/tipo/status), sem depender só de inspeção técnica ad hoc.

## What Changes

- Expandir o modelo operacional de `IngestionRun` para capturar métricas de ciclo completo:
  - timestamps separados de enfileiramento/início/fim;
  - latências derivadas (fila, execução, total);
  - classificação de falha (incluindo timeout) e metadados de execução.
- Introduzir métricas por estágio de execução (admissions capture, gap planning, extraction, ingest), com duração e resultado por etapa.
- Padronizar persistência de métricas em todos os caminhos de execução já existentes (full sync, admissions-only, census extraction).
- Expor consulta operacional:
  - via Django Admin (listagem, filtros, busca e ordenação por métricas-chave);
  - via portal (cards simples no dashboard + página dedicada com filtros e tabelas de métricas).
- Adicionar navegação explícita do dashboard para a página de métricas de ingestão.

## Scope / Non-Goals / Risks

### Scope

- Observabilidade operacional de runs de ingestão no banco e no portal.
- Consulta de métricas em nível agregado e em nível de run.
- Sem alterar a arquitetura assíncrona atual (PostgreSQL + management commands).

### Non-Goals

- Não introduzir stack de observabilidade externa (Prometheus/Grafana/OTel) neste change.
- Não migrar para Celery/Redis.
- Não redesenhar o fluxo clínico de ingestão (extração, deduplicação, reconciliação).

### Main Risks

- Incremento de complexidade no worker ao instrumentar múltiplas etapas.
- Risco de inconsistência de métricas em caminhos de erro não cobertos por testes.
- Risco de consulta pesada no portal sem filtros/índices mínimos para período/status.

## Capabilities

### New Capabilities

- `ingestion-run-metrics-portal`: visão operacional de métricas de ingestão no portal (cards de resumo no dashboard e página detalhada com filtros por período, intent e status).
- `ingestion-run-metrics-admin`: consulta operacional no Django Admin para runs e estágios, com foco em suporte/diagnóstico.

### Modified Capabilities

- `ingestion-run-observability`: ampliação dos requisitos de métricas de run para cobrir ciclo completo (fila -> execução -> término), motivos categorizados de falha e métricas por estágio.

## Impact

- `apps/ingestion/models.py` e migrações: novos campos de métricas e possivelmente modelo auxiliar de estágios.
- `apps/ingestion/management/commands/process_ingestion_runs.py`: instrumentação de timestamps, durações e failure reason.
- `apps/census/management/commands/extract_census.py`: padronização das métricas de execução no mesmo contrato operacional.
- `apps/ingestion/admin.py` (novo/ajustes): list_display, filtros e busca por métricas.
- `apps/services_portal/views.py` + templates do dashboard: cards de resumo de métricas.
- Nova rota/template para página detalhada de métricas operacionais.
- Testes unitários/integrados para persistência de métricas, filtros e renderização de visão operacional.
