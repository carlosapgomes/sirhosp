# Change Proposal: ingestion-worker-batch-observability

## Why

A operação do processamento de censo precisa comparar a eficiência de batches
com diferentes quantidades de workers. Hoje o banco já guarda timestamps de
batch, runs, tentativas e estágios, mas a interface não mostra de forma direta
quantos workers realmente atuaram no lote, qual foi a concorrência observada,
qual foi o throughput e se a duração média por job aumentou.

A investigação manual dos 13 primeiros lotes mostrou que 20 workers não trouxe
ganho claro frente a 10-15 workers, e que dois batches sobrepostos podem
contaminar a leitura. Para tornar a próxima rodada de experimentos confiável,
precisamos instrumentar os workers e expor métricas agregadas por batch sem
introduzir infraestrutura externa.

## What Changes

1. Preencher `IngestionRun.worker_label` no momento em que um worker assume um
   run da fila.
2. Calcular métricas operacionais derivadas dos dados existentes:
   - total de jobs por status;
   - workers distintos observados;
   - pico de concorrência observado por sobreposição de tentativas;
   - concorrência média observada;
   - throughput em jobs/minuto;
   - duração média de processamento por job;
   - duração média de tentativa ativa.
3. Expor essas métricas inicialmente no bloco do último batch e, em seguida,
   numa tabela histórica paginada de batches em cronologia reversa.
4. Reorganizar `/metrica-ingestao/` para priorizar comparação de batches; a
   tabela de `Execuções` deixa de listar todos os jobs globalmente e passa a
   aparecer apenas quando o usuário abre o detalhe de um batch específico.
5. Cobrir o comportamento com testes TDD, mantendo a coordenação atual via
   PostgreSQL e management command.

## Scope

| Camada | Arquivos esperados |
| --- | --- |
| Worker | `apps/ingestion/management/commands/process_ingestion_runs.py` |
| Portal | `apps/services_portal/views.py` |
| Template | `apps/services_portal/templates/services_portal/ingestion_metrics.html` |
| Testes | `tests/unit/test_services_portal_ingestion_metrics.py` |
| Testes | `tests/integration/test_ingestion_worker_retries.py` ou novo teste focado |
| UI histórica | Tabela paginada de batches em `/metrica-ingestao/` |
| Detalhe | Execuções filtradas por `batch_id` ao clicar em um batch |

## Non-Goals

- Não introduzir Prometheus, Grafana, OpenTelemetry, Celery ou Redis.
- Não persistir uma tabela nova de amostras de workers neste slice.
- Não tentar reconstruir `worker_label` dos batches históricos já processados.
- Não alterar a lógica clínica de ingestão, retry, batch closure ou enfileiramento.
- Não alterar o número de workers nos arquivos Compose/deploy.
- Não criar gráficos ou exportação CSV/Excel do histórico neste change.

## Assumptions

- O campo `IngestionRun.worker_label` já existe e pode ser preenchido sem
  migração.
- `IngestionRunAttempt.started_at` e `finished_at` são suficientes para estimar
  concorrência observada do batch.
- Quando o ambiente definir `SIRHOSP_WORKER_LABEL`, esse valor deve ser usado;
  caso contrário, um fallback baseado em hostname/processo é aceitável.
- Métricas de batches antigos continuam parcialmente disponíveis, mas sem
  workers distintos observados se `worker_label` estiver vazio.

## Risks

- Concorrência estimada por intervalos de tentativa é uma aproximação, não uma
  medição de CPU ou sessão Playwright real.
- `worker_label` pode não ser amigável se o ambiente não fornecer nome do
  container; por isso o fallback deve ser estável e seguro.
- Cálculo em Python sobre muitos batches pode ficar caro se aplicado em janelas
  longas; a tabela histórica deve usar paginação e limitar o número de batches
  calculados por página.

## Mitigations

- No primeiro slice, limitar o cálculo ao último batch finalizado exibido na UI.
- Na tabela histórica, paginar batches e calcular métricas somente para a página
  corrente.
- Usar consultas enxutas e valores derivados em memória apenas para batches
  exibidos.
- Documentar no próprio nome das métricas que são valores observados/estimados.
- Manter slices pequenos, sem migração, e validar em container.

## Capabilities

### Modified Capabilities

- `ingestion-run-observability`: workers passam a identificar o executor que
  assumiu cada run.
- `ingestion-run-metrics-portal`: página de métricas passa a exibir indicadores
  de batch úteis para comparar experimentos de quantidade de workers, incluindo
  histórico paginado e detalhe sob demanda das execuções de um batch.

## Impact

- Operação poderá comparar lotes futuros e antigos com 10, 12, 15 ou 20
  workers sem depender de percepção subjetiva.
- A UI passará a mostrar sinais de saturação: queda de throughput, aumento de
  duração média por tentativa/job e diferença entre workers distintos e pico de
  concorrência.
- O banco permanece a fonte única de observabilidade operacional, sem nova
  infraestrutura.
