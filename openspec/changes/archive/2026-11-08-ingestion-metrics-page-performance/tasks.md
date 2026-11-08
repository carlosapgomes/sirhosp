# Tasks: ingestion-metrics-page-performance

Execução sequencial S1 → S2 → S3 → S4 (cada slice parte de um commit
aceito; S3 depende de S2 porque o teste de elisão com 150+ batches só é
barato com o histórico leve).

- [x] S1 — Lazy por aba/modo + remover contexto morto
      Contract: `slices/slice-001-lazy-tab-computation.md`
- [x] S2 — Histórico leve + eficiência no detalhe do batch
      Contract: `slices/slice-002-lightweight-batch-history.md`
- [x] S3 — Paginação elidida sem overflow
      Contract: `slices/slice-003-elided-pagination.md`
- [x] S4 — Índices concorrentes em `finished_at`
      Contract: `slices/slice-004-finished-at-indexes.md`

## Comandos de verificação (quando houver execução Python)

```bash
uv run pytest -q tests/unit/test_services_portal_ingestion_metrics.py
uv run pytest -q tests/integration/test_services_portal_ingestion_metrics_failures_tab.py
./scripts/test-in-container.sh quality-gate
```
