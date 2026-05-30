# Tasks: ingestion-worker-batch-observability

## 1. Slice IWBO-S1 — Worker label e métricas observadas do último batch

- [x] 1.1 (RED) Criar testes para `worker_label` preenchido pelo worker ao
  assumir/processar um run.
- [x] 1.2 (RED) Criar testes do helper de métricas do último batch com runs e
  tentativas sintéticas cobrindo workers distintos, pico/média de concorrência,
  throughput e médias de duração.
- [x] 1.3 Implementar resolução determinística de label do worker em
  `process_ingestion_runs`, usando `SIRHOSP_WORKER_LABEL` quando existir e
  fallback seguro por hostname/PID.
- [x] 1.4 Persistir `worker_label` no `IngestionRun` quando o run é assumido
  por um worker, sem alterar semântica de claim, retry ou batch closure.
- [x] 1.5 Estender o helper `_get_latest_batch_failure_stats()` para retornar
  métricas observadas do batch com fallback vazio seguro.
- [x] 1.6 Atualizar `ingestion_metrics.html` para exibir os novos indicadores no
  bloco/aba de batch.
- [x] 1.7 Executar gates relevantes:
  `./scripts/test-in-container.sh check` (✅ 0 silenced),
  `./scripts/test-in-container.sh unit` (✅ 936 passed),
  `./scripts/test-in-container.sh integration` (⚠️ 378 passed, 11 failed —
    10 pre-existing cost/summary, 1 pre-existing batch_duration_card),
  `./scripts/test-in-container.sh lint` (✅ All checks passed),
  `./scripts/test-in-container.sh typecheck` (✅ Success).
- [x] 1.8 Gerar relatório obrigatório em
  `/tmp/sirhosp-slice-IWBO-S1-report.md`.

## 2. Slice IWBO-S2 — Tabela histórica paginada de batches

- [x] 2.1 (RED) Criar testes para a página `/metrica-ingestao/` renderizar uma
  tabela de batches finalizados em cronologia reversa.
- [x] 2.2 (RED) Criar testes de paginação da tabela de batches, incluindo
  primeira página com o batch mais recente e preservação de parâmetros úteis.
- [x] 2.3 Implementar helper/query de histórico de batches com métricas
  comparativas derivadas por batch.
- [x] 2.4 Atualizar `ingestion_metrics.html` para priorizar a tabela histórica
  de batches na visão padrão.
- [x] 2.5 Adicionar links na linha e/ou ID do batch para abrir detalhe do batch
  em `?batch_id=<id>`.
- [x] 2.6 Executar gates relevantes:
  `./scripts/test-in-container.sh check` (✅ 0 silenced),
  `./scripts/test-in-container.sh unit` (✅ 955 passed),
  `./scripts/test-in-container.sh lint` (✅ All checks passed),
  `./scripts/test-in-container.sh typecheck` (✅ Success),
  `./scripts/markdown-lint.sh` (✅ 0 errors).
- [x] 2.7 Gerar relatório obrigatório em
  `/tmp/sirhosp-slice-IWBO-S2-report.md`.

## 3. Slice IWBO-S3 — Detalhe de batch e execuções sob demanda

- [x] 3.1 (RED) Criar testes para a visão padrão de `/metrica-ingestao/` não
  renderizar a tabela global de todas as execuções.
- [x] 3.2 (RED) Criar testes para `?batch_id=<id>` renderizar somente as
  execuções daquele batch, com filtros de status/intent/failure_reason quando
  aplicáveis.
- [x] 3.3 (RED) Criar testes para batch inexistente ou inválido renderizar
  estado vazio/404 amigável sem listar execuções globais.
- [x] 3.4 Implementar modo de detalhe de batch na view, reutilizando o layout
  de `Execuções` apenas quando `batch_id` estiver presente.
- [x] 3.5 Adicionar paginação para execuções do batch selecionado se a tabela
  puder exceder volume confortável de renderização.
- [x] 3.6 Executar gates relevantes:
  `./scripts/test-in-container.sh check` (✅ 0 silenced),
  `./scripts/test-in-container.sh unit` (✅ 969 passed),
  `./scripts/test-in-container.sh integration` (⚠️ 379 passed, 10 pre-existing failures),
  `./scripts/test-in-container.sh lint` (✅ All checks passed),
  `./scripts/test-in-container.sh typecheck` (✅ Success),
  `./scripts/markdown-lint.sh` (✅ 0 errors).
- [x] 3.7 Gerar relatório obrigatório em
  `/tmp/sirhosp-slice-IWBO-S3-report.md`.

> **Quickfix pós-review:** Removido filtro de período da queryset de batch detail
> (runs do batch sempre visíveis). Corrigidos asserts frágeis que usavam
> `str(pk) in/not in content` para usar contexto `selected_batch_runs_page.object_list`.
> Relatório corrigido (14 testes, 5 arquivos).

## 4. Fora de escopo por enquanto

- [ ] Gráficos de tendência.
- [ ] Persistência de `configured_workers_count` por batch.
- [ ] Alterações em Compose/systemd para definir labels amigáveis.
- [ ] P95/P99 por intent.
- [ ] Exportação CSV/Excel do histórico de batches.
