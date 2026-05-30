# Design: ingestion-worker-batch-observability

## Context

O projeto já possui uma base útil para observabilidade:

- `IngestionRun` registra lifecycle, status, intent, timestamps e
  `worker_label`.
- `IngestionRunAttempt` registra início/fim de cada tentativa.
- `CensusExecutionBatch` agrupa os runs de um ciclo de censo.
- A página `services_portal:ingestion_metrics` já exibe métricas agregadas e
  dados do último batch finalizado.

O problema atual não é ausência total de dados, mas falta de duas leituras
operacionais na interface:

1. qual executor assumiu cada job;
2. como comparar batches sob diferentes níveis de concorrência.

## Goals / Non-Goals

### Goals

- Preencher `worker_label` de forma automática quando um worker assume um run.
- Calcular métricas observadas do último batch finalizado sem criar nova
  infraestrutura.
- Expor métricas na UI para apoiar decisão sobre quantidade ótima de workers.
- Adicionar tabela histórica paginada de batches em cronologia reversa.
- Mostrar execuções/jobs apenas como detalhe de um batch selecionado.
- Preservar compatibilidade com batches históricos.

### Non-Goals

- Não criar scheduler novo nem alterar systemd/Compose.
- Não persistir amostras temporais de workers ativos neste slice.
- Não implementar gráficos históricos por batch neste change.
- Não mudar semântica de retries, falha final ou fechamento de batch.

## Decisions

### D1) Usar `worker_label` existente em `IngestionRun`

**Decisão:** preencher `worker_label` no claim do run, dentro do fluxo do
`process_ingestion_runs`.

Fonte sugerida, em ordem:

1. variável de ambiente `SIRHOSP_WORKER_LABEL`, se definida;
2. hostname do container/máquina;
3. PID do processo como sufixo para reduzir ambiguidade.

Formato recomendado:

```text
<hostname>:<pid>
```

Se `SIRHOSP_WORKER_LABEL` existir, usar:

```text
<SIRHOSP_WORKER_LABEL>:<pid>
```

O objetivo é identificação operacional, não identidade clínica ou sensível.

### D2) Não criar migração neste slice

**Decisão:** usar campos e tabelas já existentes.

`worker_label` já existe em `IngestionRun`; métricas de concorrência podem ser
calculadas por sobreposição dos intervalos de `IngestionRunAttempt` do batch.
Isso reduz risco e acelera a entrega.

### D3) Calcular concorrência observada por intervalos de tentativa

**Decisão:** estimar concorrência por sweep-line sobre eventos:

```text
attempt.started_at  => +1
attempt.finished_at => -1
```

Ordenar eventos de mesmo timestamp processando término antes de início. O pico
é o maior valor acumulado.

A concorrência média observada é:

```text
sum(attempt.finished_at - attempt.started_at) / batch_drain_seconds
```

Onde `batch_drain_seconds` é `batch.finished_at - batch.enqueue_finished_at`
quando disponível.

### D4) Expor métricas como parte do helper existente do último batch

**Decisão:** estender `_get_latest_batch_failure_stats()` em vez de criar nova
view ou rota.

Esse helper já localiza o último batch finalizado e alimenta a aba de pacientes
na tela de métricas. O slice deve acrescentar chaves no contexto, mantendo as
chaves atuais para não quebrar templates/testes existentes.

Chaves sugeridas:

```python
{
    "runs_total": 0,
    "runs_succeeded": 0,
    "runs_failed": 0,
    "runs_active": 0,
    "observed_worker_count": 0,
    "observed_worker_labels": [],
    "observed_peak_concurrency": 0,
    "observed_avg_concurrency": 0.0,
    "throughput_jobs_per_minute": 0.0,
    "avg_processing_duration_seconds": 0,
    "avg_attempt_duration_seconds": 0,
}
```

Para estado vazio (`has_batch=False`), retornar zeros/listas vazias para todas
as novas chaves.

### D5) UI textual simples em vez de gráfico

**Decisão:** adicionar cards/tabela compacta na tela existente.

Primeira versão deve priorizar clareza operacional:

- workers observados;
- pico/média de concorrência;
- jobs/minuto;
- média por job/tentativa;
- total de jobs com sucesso/falha.

Gráficos ficam para change futura; histórico tabular entra em slice separado.

### D6) Histórico paginado de batches como visão padrão

**Decisão:** transformar a visão padrão de `/metrica-ingestao/` em uma tabela
histórica de batches finalizados, ordenada por `finished_at desc` ou, como
fallback, `started_at desc`.

A tabela deve permitir comparação rápida entre lotes, com colunas como:

- ID do batch;
- status;
- início e fim;
- duração;
- total de jobs;
- jobs com sucesso/falha;
- workers observados;
- pico/média de concorrência;
- jobs/minuto;
- média por job;
- média por tentativa.

A tabela deve ser paginada. O cálculo de métricas derivadas deve ser limitado
aos batches da página corrente para evitar custo desnecessário.

### D7) Execuções somente sob demanda por batch

**Decisão:** a tabela global de `Execuções` não deve aparecer na visão padrão.
Ela passa a ser renderizada apenas quando a URL contém um batch selecionado,
por exemplo:

```text
/metrica-ingestao/?batch_id=13
```

Ao clicar na linha ou no ID do batch na tabela histórica, o usuário abre o
modo de detalhe daquele batch. Nesse modo, a página mostra:

- resumo do batch selecionado;
- execuções/jobs filtradas por `batch_id`;
- filtros opcionais de status, intent e failure_reason aplicados somente ao
  batch selecionado;
- link claro para voltar ao histórico de batches.

Essa abordagem evita uma nova rota no primeiro momento e mantém o fluxo simples
para o usuário.

## Metrics Semantics

| Métrica | Fonte | Observação |
| --- | --- | --- |
| Workers observados | `IngestionRun.worker_label` distinto por batch | Só funciona para batches novos após este slice |
| Pico de concorrência | sobreposição de `IngestionRunAttempt` | Estimativa operacional |
| Concorrência média | soma das durações de tentativas / drain do batch | Pode ser menor que workers configurados se houver espera externa |
| Jobs/minuto | runs terminais / minutos de drain | Inclui todos os intents do batch |
| Média por job | `processing_started_at` até `finished_at` | Inclui retries/backoff dentro do run |
| Média por tentativa | `attempt.started_at` até `attempt.finished_at` | Aproxima tempo ativo real |
| Página histórica | `CensusExecutionBatch` paginado | Ordenação reversa, cálculo só por página |
| Detalhe de execuções | `IngestionRun.batch_id` | Nunca listar todos os jobs globalmente por padrão |

## Test Strategy

- Teste unitário do helper de batch para estado vazio.
- Teste unitário do helper com runs/tentativas sintéticas validando:
  - workers distintos;
  - pico de concorrência;
  - média de concorrência;
  - throughput;
  - médias de duração.
- Teste do worker garantindo que um run processado recebe `worker_label`.
- Teste de template garantindo que a tela renderiza os novos rótulos.
- Testes da tabela histórica validando ordenação reversa e paginação.
- Testes do modo detalhe validando que execuções são filtradas por `batch_id`.
- Testes garantindo que a visão padrão não renderiza a lista global de jobs.

## Rollout

1. Aplicar IWBO-S1 para preencher `worker_label` e exibir métricas do último
   batch.
2. Aplicar IWBO-S2 para disponibilizar histórico paginado de batches.
3. Aplicar IWBO-S3 para mover `Execuções` para detalhe sob demanda por batch.
4. Rodar um batch com 10-12 workers sem sobreposição.
5. Verificar se `worker_label` aparece preenchido nos runs do batch.
6. Comparar a tabela histórica antes de testar 12, 15 ou 20 workers.

## Open Questions

1. Vale definir `SIRHOSP_WORKER_LABEL` explicitamente no Compose/deploy em um
   slice futuro para melhorar legibilidade?
2. P95 por intent deve entrar neste mesmo fluxo ou em um slice posterior?
3. A URL `?batch_id=<id>` é suficiente ou vale criar rota dedicada
   `/metrica-ingestao/batches/<id>/` em change futura?
