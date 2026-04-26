# Tasks: ingestion-run-expanded-metrics-dashboard

## 1. Slice S1 — Contrato base de lifecycle no `IngestionRun`

- [x] 1.1 (RED) Criar testes para novos campos de lifecycle/falha no modelo (`queued_at`, `processing_started_at`, `failure_reason`, `timed_out`, `worker_label`).
- [x] 1.2 Criar migração para expansão do `IngestionRun` preservando compatibilidade com `started_at` legado.
- [x] 1.3 Implementar helpers de duração no modelo (fila, execução, total) com cobertura de testes.
- [x] 1.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh unit`, `./scripts/test-in-container.sh lint`.

## 2. Slice S2 — Instrumentação do worker e taxonomia de falha

- [x] 2.1 (RED) Criar/ajustar testes de integração do worker para validar lifecycle (`processing_started_at`/`finished_at`) e categorias de falha.
- [x] 2.2 Instrumentar `process_ingestion_runs` para preencher timestamps e limpar/preencher campos de falha conforme resultado.
- [x] 2.3 Implementar mapeamento determinístico de falha (`timeout`, `source_unavailable`, `invalid_payload`, `validation_error`, `unexpected_exception`) + `timed_out`.
- [x] 2.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh integration`, `./scripts/test-in-container.sh lint`.

## 3. Slice S3 — Métricas por estágio (`IngestionRunStageMetric`)

- [x] 3.1 (RED) Criar testes para persistência de estágios em sucesso, falha e skip.
- [x] 3.2 Criar modelo/migração `IngestionRunStageMetric` com índices e relação 1:N com `IngestionRun`.
- [x] 3.3 Instrumentar worker para registrar estágios críticos (`admissions_capture`, `gap_planning`, `evolution_extraction`, `ingestion_persistence`).
- [x] 3.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh integration`, `./scripts/test-in-container.sh lint`.

## 4. Slice S4 — Contrato de métricas aplicado ao `extract_census`

- [x] 4.1 (RED) Criar testes unitários do command `extract_census` com subprocess mockado para sucesso/erro/timeout.
- [x] 4.2 Atualizar command para preencher campos lifecycle/falha no `IngestionRun`.
- [x] 4.3 Registrar estágios do fluxo de censo no mesmo padrão operacional.
- [x] 4.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh unit`, `./scripts/test-in-container.sh lint`.

## 5. Slice S5 — Consulta operacional no Django Admin

- [x] 5.1 (RED) Criar testes de admin para listagem/filtros de `IngestionRun` e visualização de estágios.
- [x] 5.2 Implementar `apps/ingestion/admin.py` com `ModelAdmin` (list_display, filters, search, ordering, campos readonly).
- [x] 5.3 Implementar inline read-only de `IngestionRunStageMetric` no detalhe do run.
- [x] 5.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh integration`, `./scripts/test-in-container.sh lint`.

## 6. Slice S6 — Dashboard com cards de métricas de ingestão

- [x] 6.1 (RED) Criar/ajustar testes do dashboard para cards de métricas operacionais (janela padrão 24h, fallback vazio, CTA).
- [x] 6.2 Implementar agregações no dashboard (runs totais, success rate, timeout rate, duração média).
- [x] 6.3 Criar rota/view/template inicial da página de métricas (`services_portal:ingestion_metrics`) e ligar CTA no dashboard.
- [x] 6.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh unit`, `./scripts/test-in-container.sh lint`.

## 7. Slice S7 — Página detalhada de métricas com filtros

- [x] 7.1 (RED) Criar testes da página de métricas para filtros por período, status, intent e failure_reason.
- [x] 7.2 Implementar listagem detalhada de runs com colunas de lifecycle e resultados.
- [x] 7.3 Implementar resumo agregado sincronizado com dataset filtrado.
- [x] 7.4 Gate do slice: `./scripts/test-in-container.sh check`, `./scripts/test-in-container.sh unit`, `./scripts/test-in-container.sh integration`, `./scripts/test-in-container.sh lint`.

## 8. Slice S8 — Hardening final e fechamento do change

- [x] 8.1 Criar prompts detalhados por slice em `slice-prompts/SLICE-SX.md` (handoff zero-context + escopo + TDD + relatório obrigatório).
- [x] 8.2 Executar gate completo: `./scripts/test-in-container.sh quality-gate`.
- [x] 8.3 Validar markdown: `./scripts/markdown-lint.sh`.
- [x] 8.4 Consolidar relatórios obrigatórios `/tmp/sirhosp-slice-IRMD-SX-report.md`.
- [x] 8.5 Atualizar `tasks.md` com checklist final e preparar change para `/opsx:apply`.
