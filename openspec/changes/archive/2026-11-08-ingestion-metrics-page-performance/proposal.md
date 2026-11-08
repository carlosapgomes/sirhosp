# Change Proposal: ingestion-metrics-page-performance

## Why

A página `/metrica-ingestao/` (métricas operacionais de ingestão, uso
admin) está lenta e com paginação quebrada. Medição direta na base atual
(cópia de produção com 2,1 M de `IngestionRun`, 2,1 M de
`IngestionRunAttempt` e 991 `CensusExecutionBatch`):

- cada abertura executa **187 queries** e leva **~4 s de backend**,
  materializando ~100 mil linhas em ORM para agregar métricas em Python;
- a view calcula agregados que **nem são exibidos** na aba/modo atual
  (ex.: estatísticas da aba de pacientes rodam na aba de execuções);
- a tabela de histórico recalcula métricas caras de concorrência e
  throughput (full scan de runs + attempts) **para cada um dos 20 batches
  da página**, a cada request;
- não há índice em `finished_at`/`status`/`intent`/`failure_reason` —
  cada filtro faz sequential scan em 2,1 M de linhas;
- a paginação renderiza **todos os números de página** (50 links no
  histórico), transbordando a viewport horizontalmente.

Valor operacional: a página existe para diagnóstico de ingestão pela
equipe técnica/gestão. Lenta, ela desestimula o monitoramento; com o
crescimento contínuo das tabelas, o custo por request só aumenta.

## What Changes

1. **Lazy por aba/modo (A):** calcular `batch_failure_stats` somente na
   aba `patients`; rodar a agregação global de runs e os `DISTINCTs` de
   filtro somente no modo detalhe (`?batch_id=`); remover do contexto as
   chaves mortas `runs` e `ingestion_stats` (não usadas pelo template).
2. **Histórico leve (B):** a tabela de histórico passa a exibir somente
   colunas baratas (ID, status, timestamps, duração, contagens de jobs
   via agregação SQL única); as métricas caras de eficiência
   (workers, pico, jobs/min, médias) mudam para o bloco de detalhe do
   batch selecionado.
3. **Paginação elidida (C):** `get_elided_page_range` nas duas
   paginações + defesa CSS (`flex-wrap`) contra overflow.
4. **Índices (D):** btree em `IngestionRun.finished_at` e
   `CensusExecutionBatch.finished_at` via migration concorrente.

## Scope

| Camada    | Arquivos esperados                                                                   |
| --------- | ------------------------------------------------------------------------------------ |
| Portal    | `apps/services_portal/views.py`                                                      |
| Template  | `apps/services_portal/templates/services_portal/ingestion_metrics.html`              |
| Modelo    | `apps/ingestion/models.py` (Meta.indexes)                                            |
| Migration | `apps/ingestion/migrations/0007_*.py` (concorrente)                                  |
| Testes    | `tests/unit/test_services_portal_ingestion_metrics.py`                               |
| Testes    | `tests/integration/test_services_portal_ingestion_metrics_failures_tab.py`           |
| Testes    | `tests/integration/test_patient_flow_findings_observability.py` (somente se afetado) |

## Non-Goals

- Não alterar regras de ingestão, retry, fechamento de batch, worker ou
  enfileiramento.
- Não alterar o dashboard (`dashboard.html` usa seu próprio
  `ingestion_stats` — fora de escopo).
- Não paginar/filtrar a tabela de pacientes com falha final (volume atual
  é baixo: ~20 linhas no último batch).
- Não introduzir cache, Redis, Celery, Prometheus ou qualquer
  infraestrutura nova (página de pouco uso, só admin).
- Não persistir tabela nova de métricas pré-agregadas (lever futuro só se
  voltar a doer — YAGNI).
- Não restringir a página a staff (`@staff_member_required` é sugestão
  separada, fora desta change).
- Não indexar `status`/`intent`/`failure_reason` (baixa seletividade,
  custo de escrita, ganho marginal para página admin).

## Assumptions

- Os números medidos na cópia de produção representam a escala real do
  problema; o crescimento das tabelas é contínuo.
- A página é de pouco uso e só interessa ao admin: otimizar custo por
  request importa mais que polimento de UI.
- `runs` e `ingestion_stats` no contexto de `ingestion_metrics` estão
  mortos (confirmado por grep — só `dashboard.html` usa seu próprio
  `ingestion_stats`).
- As colunas caras do histórico têm valor apenas comparativo pontual;
  movê-las para o detalhe não quebra nenhum fluxo operacional.

## Risks

- **Regressão visual de conteúdo:** mover colunas do histórico para o
  detalhe muda o HTML da aba runs. Mitigação: testes de conteúdo
  antes/depois por aba/modo (slice 002).
- **Migration concorrente sem precedente no repo:** primeira migration
  `atomic = False` + `AddIndexConcurrently`. Mitigação: slice dedicado
  com verificação de `sqlmigrate` e aplicação limpa no container de
  teste; deploy fora de pico.
- **Testes existentes acoplados às colunas antigas:** algum teste pode
  afirmar headers do histórico. Mitigação: worker faz grep e atualiza
  somente o acoplado ao contrato antigo (slice 002 declara).
