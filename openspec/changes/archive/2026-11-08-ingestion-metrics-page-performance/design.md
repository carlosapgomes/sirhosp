# Design: ingestion-metrics-page-performance

## Contexto

`ingestion_metrics` (`apps/services_portal/views.py`) sempre calcula três
blocos caros, independente da aba/modo:

1. `_build_filtered_queryset()` + 3 `DISTINCT` globais (janela de runs);
2. `_get_latest_batch_failure_stats()` (último batch + findings);
3. `_get_batch_history_context()` → `_compute_batch_metrics()` × 20
   (sweep-line de concorrência sobre todos os attempts de cada batch).

Medição (base com 2,1 M runs / 991 batches): 187 queries, ~4 s backend,
~0,9 s só de SQL. O template (`ingestion_metrics.html`) não usa `runs`
nem `ingestion_stats`, e só usa `batch_failure_stats` na aba `patients`.

Decisões abaixo são o contrato; workers não as reinterpretam.

## Decisões

### D1 — Lazy por aba/modo, sem mudar conteúdo visível

- `batch_failure_stats`: calcular somente quando `tab == "patients"`.
- `_build_filtered_queryset()` + `DISTINCT` de `status`/`intent`/
  `failure_reason`: calcular somente no modo detalhe
  (`show_batch_detail == True`), único que renderiza o formulário de
  filtros e os cards `selected_batch_stats`.
- Remover do contexto as chaves mortas `runs` e `ingestion_stats`.
- Conteúdo HTML de cada aba/modo permanece byte-equivalente em dados
  (modulo timestamps de "agora"); aba `patients` e modo detalhe
  inalterados nesta etapa.
- O contrato de apresentação do requisito de latest-batch passa a ser
  explicitamente a aba `patients` (+ detalhe por batch em D3) — ver
  delta spec. Nenhum comportamento visível muda; apenas onde o contrato
  permite que os dados apareçam.

### D2 — Histórico leve: colunas baratas + 1 agregação

Colunas mantidas no histórico (deriváveis do próprio batch ou de 1
agregação SQL por página):

- Batch ID, Status (inclui apresentação derivada de findings),
  Início, Fim, Duração (janela de drain, já é campo calculado do batch),
  Jobs, Sucesso, Falha.

Colunas removidas do histórico (movidas ao detalhe, D3):

- Workers, Pico, Jobs/min, Méd/job, Méd/tent.

Contagens Jobs/Sucesso/Falha passam a vir de **uma única query agregada**
por página (`GROUP BY batch_id, status` sobre os batches da página),
nunca de scans por batch. O agregado de findings
(`_summarize_batch_findings`, 1 query/página) permanece. Page size 20 e
ordenação `-finished_at, -id` inalterados.

### D3 — Métricas caras vivem no detalhe do batch

O modo `?batch_id=` ganha um bloco de eficiência do lote reutilizando
`_compute_batch_metrics(selected_batch)` (1 batch por vez, custo
aceitável sob demanda): workers observados, pico e média de
concorrência, throughput, médias por job/tentativa. Valores idênticos
aos que o histórico exibia (mesmo helper). Tabela de runs (50/página) e
filtros do detalhe inalterados.

### D4 — Opções de filtro continuam globais (custo residual aceito)

Os dropdowns de status/intent/falha continuam calculados sobre todos os
runs finalizados (3 `DISTINCT`), agora somente no modo detalhe. Escopar
ao batch mudaria as opções visíveis (decisão de produto não aprovada).
Custo residual (~0,5 s no modo detalhe, página admin) documentado e
aceito.

### D5 — Paginação elidida + defesa CSS

- View calcula `get_elided_page_range()` para o histórico e para os runs
  do detalhe e expõe no contexto (template itera o range elidido e
  renderiza `…` como item desabilitado).
- `<nav>` das paginações recebe `flex-wrap` (e `justify-content-center`
  mantido) para nunca estourar a viewport mesmo em casos limite.
- Parâmetros de querystring existentes preservados nos links
  (`batch_id`, `run_page`/`batch_page`, filtros, `tab`).

### D6 — Índices concorrentes em `finished_at`

- `Meta.indexes`: btree em `IngestionRun.finished_at` e
  `CensusExecutionBatch.finished_at`.
- Migration dedicada, `atomic = False`, `AddIndexConcurrently`
  (primeiro uso no repo — sem `RunPython`, sem alteração de dados).
- Explicitamente fora: índices em `status`/`intent`/`failure_reason`
  (D4 explica o residual; seletividade baixa não justifica custo de
  escrita em 2,1 M de linhas).

## Orçamento de queries (alvo)

- Default (`tab=runs`, sem batch): o histórico emite **zero queries que
  carreguem runs ou attempts por batch** (página de batches + 1
  agregação de contagens + 1 agregado de findings + overhead fixo de
  auth/contexto). Alvo prático: < 20 queries (hoje: 187).
- Testes devem afirmar a **ausência de scans por batch** (ex.: nenhuma
  query contra a tabela de attempts; contagens vindas do agregado),
  não comparar contagens K-vs-2K — o nº de queries já é fixo por batch
  hoje (`.iterator()` varre linhas, não emite queries extras). Um bound
  explícito com comentário de regressão é aceitável como segunda
  asserção.

## Impacto por camada

- **Domínio clínico:** nenhum — página é observabilidade operacional
  admin; nenhum dado clínico muda de semântica ou exposição.
- **Scraping/ingestão:** nenhum — workers, retry e fechamento de batch
  intocados.
- **Banco:** 2 índices btree novos (criação `CONCURRENTLY`, sem lock de
  escrita prolongado); eliminação de ~170 queries e ~100 mil
  materializações ORM por pageview; nenhum change de dados.
- **Operação (fase 1):** preserva simplicidade — sem cache, sem Redis,
  sem tabela nova, sem worker novo. Deploy da migration fora de pico por
  precaução (tabela com 2,1 M linhas).

## Alternativas consideradas e rejeitadas

- **Pré-agregar métricas no fechamento do batch:** definitivo, mas
  adiciona escrita/estado para página de baixo uso — YAGNI agora.
- **Reduzir page size do histórico:** não resolve; o custo é o deep scan
  por batch, não o nº de linhas.
- **Cache de página/fragmento:** invalidação acoplada ao ciclo de batch;
  complexidade injustificada para uso admin esporádico.
