# SLICE-IWBO-S2: Tabela histórica paginada de batches

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como fonte principal de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md`
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md`
3. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/design.md`
5. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/specs/ingestion-run-metrics-portal/spec.md`
7. `/projects/dev/sirhosp/openspec/specs/ingestion-run-metrics-portal/spec.md`

**Implemente SOMENTE o Slice IWBO-S2 e PARE.**

Pré-condição esperada: IWBO-S1 pode já ter criado helpers de métricas do último
batch. Se IWBO-S1 ainda não estiver implementado, implemente neste slice apenas
o mínimo necessário para calcular métricas da tabela histórica sem alterar o
worker.

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas em testes.

---

## Objetivo

Adicionar à página `/metrica-ingestao/` uma tabela histórica paginada de
`CensusExecutionBatch`, em cronologia reversa, para comparar batches de censo.

A visão padrão da página deve priorizar essa tabela histórica. A tabela deve
ter links no ID e/ou na linha do batch apontando para o modo de detalhe:

```text
/metrica-ingestao/?batch_id=<id>
```

O modo de detalhe completo das execuções será implementado no Slice IWBO-S3.
Neste slice, o requisito é a tabela histórica paginada e os links corretos.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 4 arquivos**:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/services_portal/views.py` | Query/helper de histórico de batches + paginação |
| `apps/services_portal/templates/services_portal/ingestion_metrics.html` | Renderizar tabela histórica e paginação |
| `tests/unit/test_services_portal_ingestion_metrics.py` | Testes da tabela, ordenação e paginação |
| `openspec/changes/ingestion-worker-batch-observability/tasks.md` | Marcar checklist do slice ao final |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio** no
relatório.

---

## Requisitos funcionais

### 1. Tabela histórica

Na visão padrão de `/metrica-ingestao/`, renderizar uma tabela com batches
finalizados ordenados do mais recente para o mais antigo.

Ordenação recomendada:

```python
CensusExecutionBatch.objects.filter(
    finished_at__isnull=False,
).order_by("-finished_at", "-id")
```

Colunas mínimas:

- `Batch ID`;
- `Status`;
- `Início`;
- `Fim`;
- `Duração`;
- `Jobs` total;
- `Sucesso`;
- `Falha`;
- `Workers observados`;
- `Pico concorrência`;
- `Jobs/min`;
- `Média por job`;
- `Média por tentativa`.

Use nomes em português na UI.

### 2. Métricas por batch

Reutilize helpers existentes se IWBO-S1 já tiver implementado cálculo de
métricas observadas. Se não houver helper reutilizável, crie helper pequeno em
`apps/services_portal/views.py`.

O helper deve calcular somente para os batches da página corrente.

Definições:

| Métrica | Definição |
| --- | --- |
| jobs total | total de `IngestionRun` ligados ao batch |
| sucesso | runs do batch com `status="succeeded"` |
| falha | runs do batch com `status="failed"` |
| workers observados | labels distintos e não vazios em `IngestionRun.worker_label` |
| pico concorrência | maior número de `IngestionRunAttempt` sobrepostos |
| jobs/min | runs terminais / minutos de drain |
| média por job | média de `finished_at - processing_started_at` |
| média por tentativa | média de `attempt.finished_at - attempt.started_at` |

A janela de drain é:

```text
batch.enqueue_finished_at -> batch.finished_at
```

Se não houver dados suficientes, renderizar `—` ou `0` de forma consistente,
sem erro.

### 3. Paginação

Adicionar paginação server-side para a tabela de batches.

Recomendação:

- usar `django.core.paginator.Paginator`;
- page size entre 10 e 25 batches;
- parâmetro `batch_page` para evitar conflito futuro com paginação de jobs;
- preservar querystring relevante quando navegar páginas, se aplicável.

### 4. Link para detalhe

O ID do batch e/ou a linha deve apontar para:

```text
?batch_id=<id>
```

O Slice IWBO-S3 implementará a renderização completa das execuções desse batch.
Neste slice, o link deve existir e ser testável no HTML.

---

## Metodologia TDD

### RED 1 — tabela e ordenação

Em `tests/unit/test_services_portal_ingestion_metrics.py`, crie teste que:

1. cria três `CensusExecutionBatch` finalizados com `finished_at` diferentes;
2. acessa `reverse("services_portal:ingestion_metrics")`;
3. verifica que a resposta contém os IDs dos batches;
4. verifica que o mais recente aparece antes do mais antigo no HTML ou no
   contexto.

### RED 2 — métricas por batch

Crie teste com batch sintético, runs e attempts sintéticos validando que o
contexto da tabela contém valores calculados para:

- total de jobs;
- sucessos/falhas;
- workers observados;
- pico de concorrência;
- jobs/min;
- média por job;
- média por tentativa.

### RED 3 — paginação

Crie teste com mais batches do que o page size e valide:

- página 1 contém batches mais recentes;
- página 2 contém batches mais antigos;
- controles de paginação aparecem no HTML.

### RED 4 — link para detalhe

Crie teste validando que o HTML contém `batch_id=<id>` para pelo menos um batch.

### GREEN

Implemente o mínimo para passar os testes:

- helper/query de histórico;
- paginação;
- contexto para template;
- tabela e links no HTML.

### REFACTOR

Depois de verde:

- manter helpers pequenos;
- evitar N+1 grosseiro no número de batches da página;
- não calcular métricas para batches fora da página;
- preservar comportamento existente que não faz parte do slice.

---

## Critérios de aceite

- [ ] `/metrica-ingestao/` mostra tabela histórica de batches finalizados.
- [ ] Ordenação é cronologia reversa, mais recente primeiro.
- [ ] Tabela tem paginação server-side.
- [ ] Métricas comparativas são calculadas por batch da página corrente.
- [ ] ID/linha do batch contém link com `batch_id=<id>`.
- [ ] Nenhuma migration foi criada.
- [ ] Nenhum dado real/sensível foi exposto.
- [ ] Arquivos alterados respeitam o limite deste slice.

---

## Gates de validação

Execute **nesta ordem**:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Se algum comando falhar, corrija a causa raiz. Não use
`<!-- markdownlint-disable -->`.

---

## Atualização de tasks

Ao final, marque em
`openspec/changes/ingestion-worker-batch-observability/tasks.md` os itens do
Slice IWBO-S2 realmente concluídos.

Não marque itens se os gates correspondentes não tiverem sido executados ou se
falharam.

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-IWBO-S2-report.md` com **exatamente** estas seções:

```markdown
# Relatório SLICE-IWBO-S2

## 1. Resumo
(2-3 frases sobre o que foi implementado)

## 2. Checklist de aceite
- [ ] tabela histórica de batches criada
- [ ] cronologia reversa validada
- [ ] paginação implementada
- [ ] links `batch_id=<id>` implementados
- [ ] nenhum dado real/sensível exposto
- [ ] nenhuma migration criada
- [ ] limite de arquivos respeitado

## 3. Arquivos alterados
(Lista de paths exatos)

## 4. Fragmentos antes/depois
(Para cada arquivo alterado, cole trechos relevantes antes/depois)

## 5. Comandos executados e resultados
(Cole a saída resumida de cada comando de validação)

## 6. Riscos e pendências
(Explique que o detalhe completo de execuções fica para IWBO-S3)

## 7. Próximo passo sugerido
SLICE-IWBO-S3: detalhe de batch e execuções sob demanda
```

---

## Stop Rule

- **Não** altere o worker neste slice, exceto se IWBO-S1 não existir e for
  indispensável para testes de métricas; nesse caso, pare e reporte bloqueio.
- **Não** crie migration.
- **Não** implemente gráficos ou exportação.
- **Não** implemente a página completa de execuções por batch; isso é IWBO-S3.
- Ao terminar, gere o relatório e **pare** para revisão humana.
