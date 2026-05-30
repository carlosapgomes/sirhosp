# SLICE-IWBO-S1: Worker label e métricas observadas do último batch

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como fonte principal de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md`
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md`
3. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/design.md`
5. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/specs/ingestion-run-observability/spec.md`
7. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/specs/ingestion-run-metrics-portal/spec.md`
8. `/projects/dev/sirhosp/openspec/specs/ingestion-run-observability/spec.md`
9. `/projects/dev/sirhosp/openspec/specs/ingestion-run-metrics-portal/spec.md`

**Implemente SOMENTE o Slice IWBO-S1 e PARE.**

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas em testes.

---

## Objetivo

Instrumentar o worker assíncrono para preencher `IngestionRun.worker_label` e
expor, na página de métricas de ingestão, indicadores observados do último
batch de censo finalizado:

- total de jobs por status;
- número de workers distintos observados;
- pico de concorrência observado por sobreposição de tentativas;
- concorrência média observada;
- throughput em jobs/minuto;
- duração média de processamento por job;
- duração média de tentativa ativa.

Este slice deve usar campos/tabelas existentes. **Não crie migration.**

---

## Contexto operacional

Foi observado empiricamente que batches com mais workers podem não ser mais
rápidos. O banco já registra batches, runs, attempts e stage metrics, mas a UI
não mostra de forma direta a eficiência por batch.

O campo `IngestionRun.worker_label` já existe no modelo, porém aparentemente
não está sendo preenchido. A primeira entrega deve torná-lo útil para batches
futuros e calcular métricas derivadas do último batch finalizado.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 6 arquivos**:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/ingestion/management/commands/process_ingestion_runs.py` | Resolver e persistir `worker_label` |
| `apps/services_portal/views.py` | Calcular métricas observadas do último batch |
| `apps/services_portal/templates/services_portal/ingestion_metrics.html` | Renderizar novos indicadores |
| `tests/unit/test_services_portal_ingestion_metrics.py` | Testes do helper/contexto de batch |
| `tests/integration/test_ingestion_worker_retries.py` | Teste de preenchimento de `worker_label` |
| `openspec/changes/ingestion-worker-batch-observability/tasks.md` | Marcar checklist do slice ao final |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio** no
relatório.

---

## Requisitos funcionais

### 1. Worker label

Adicionar uma função/helper no command `process_ingestion_runs` para gerar o
label operacional do worker.

Comportamento esperado:

1. se `SIRHOSP_WORKER_LABEL` estiver definido e não vazio, usar esse valor como
   base;
2. se não estiver definido, usar um fallback seguro baseado em hostname;
3. adicionar `pid` como sufixo para diferenciar processos quando aplicável;
4. nunca incluir dados de paciente, parâmetros clínicos ou credenciais;
5. preencher `run.worker_label` quando o run for assumido pelo worker.

Formato recomendado:

```text
<base>:<pid>
```

Exemplos aceitáveis:

```text
sirhosp-worker-7:1234
container-hostname:1234
```

A persistência deve acontecer no claim/transition para `running`, antes do
processamento real, sem alterar semântica de concorrência.

### 2. Métricas observadas do último batch

Estender `_get_latest_batch_failure_stats()` em `apps/services_portal/views.py`
sem remover chaves já existentes.

Adicionar chaves com fallback seguro para estado vazio:

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

Definições:

| Métrica | Definição |
| --- | --- |
| `runs_total` | total de `IngestionRun` ligados ao batch |
| `runs_succeeded` | runs do batch com `status="succeeded"` |
| `runs_failed` | runs do batch com `status="failed"` |
| `runs_active` | runs do batch com `status in ["queued", "running"]` |
| `observed_worker_count` | quantidade de `worker_label` distintos e não vazios |
| `observed_worker_labels` | lista ordenada dos labels distintos não vazios |
| `observed_peak_concurrency` | maior número de attempts sobrepostos |
| `observed_avg_concurrency` | soma das durações das attempts / duração de drain |
| `throughput_jobs_per_minute` | runs terminais / minutos de drain |
| `avg_processing_duration_seconds` | média de `finished_at - processing_started_at` |
| `avg_attempt_duration_seconds` | média de `attempt.finished_at - attempt.started_at` |

Use `batch.enqueue_finished_at -> batch.finished_at` como janela de drain. Se
não houver drain válido, retorne zero para métricas que dependem dele.

Para cálculo de pico por overlap, use algoritmo sweep-line:

```text
attempt.started_at  => +1
attempt.finished_at => -1
```

Em timestamps iguais, processe término (`-1`) antes de início (`+1`) para não
inflar artificialmente o pico.

### 3. UI

Atualizar `ingestion_metrics.html` para exibir os novos indicadores no bloco já
existente do último batch.

Rótulos mínimos esperados no HTML:

- `Workers observados`
- `Concorrência observada`
- `Jobs/min`
- `Média por job`
- `Média por tentativa`

Se não houver batch finalizado, manter o estado vazio atual sem erro.

---

## Metodologia TDD

### RED 1 — worker label

Adicione teste que falhe inicialmente garantindo que um run processado pelo
command recebe `worker_label` não vazio.

Sugestão:

- usar fixture sintética de `IngestionRun(status="queued")`;
- usar `monkeypatch.setenv("SIRHOSP_WORKER_LABEL", "test-worker")`;
- executar o menor caminho possível do worker já coberto nos testes existentes;
- assertar que `run.worker_label` contém `test-worker`.

Se o teste de integração completo ficar pesado, crie um teste unitário focado
no helper de label e um teste menor no claim, mas não altere comportamento de
produção para facilitar teste.

### RED 2 — métricas de batch

Em `tests/unit/test_services_portal_ingestion_metrics.py`, crie testes para:

1. estado sem batch retorna as novas chaves com zero/lista vazia;
2. batch sintético com attempts sobrepostos calcula:
   - workers distintos;
   - pico de concorrência;
   - concorrência média;
   - throughput;
   - média por job;
   - média por tentativa;
3. template renderiza os rótulos mínimos.

Use timestamps sintéticos com `timezone.now()` e `timedelta`. Não use dados
reais.

### GREEN

Implementar o mínimo para passar os testes:

- helper de label no command;
- persistência de `worker_label` no claim;
- extensão do helper de stats;
- renderização no template.

### REFACTOR

Depois de verde:

- manter funções pequenas e legíveis;
- evitar queries N+1 desnecessárias;
- manter compatibilidade com chaves existentes do contexto;
- preservar ordenação e filtros atuais da página.

---

## Critérios de aceite

- [ ] `worker_label` é preenchido para runs assumidos pelo worker.
- [ ] `SIRHOSP_WORKER_LABEL` é respeitado quando definido.
- [ ] Último batch finalizado expõe métricas de workers/concorrência/throughput.
- [ ] Estado sem batch finalizado continua renderizando sem erro.
- [ ] Template exibe os rótulos mínimos definidos neste prompt.
- [ ] Nenhuma migration foi criada.
- [ ] Nenhum dado real/sensível foi exposto em testes, logs ou relatório.
- [ ] Arquivos alterados respeitam o limite deste slice.

---

## Gates de validação

Execute **nesta ordem**:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Se algum comando falhar, corrija a causa raiz. Não use suppressions sem
justificativa forte. Não use `<!-- markdownlint-disable -->`.

---

## Atualização de tasks

Ao final, marque em
`openspec/changes/ingestion-worker-batch-observability/tasks.md` os itens do
Slice IWBO-S1 realmente concluídos.

Não marque itens se os gates correspondentes não tiverem sido executados ou se
falharam.

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-IWBO-S1-report.md` com **exatamente** estas seções:

```markdown
# Relatório SLICE-IWBO-S1

## 1. Resumo
(2-3 frases sobre o que foi implementado)

## 2. Checklist de aceite
- [ ] worker_label preenchido pelo worker
- [ ] métricas observadas do último batch calculadas
- [ ] UI renderiza novos indicadores
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
(Explique limitações, especialmente que worker_label não é retroativo)

## 7. Próximo passo sugerido
(Sugira experimento operacional: 10-12 workers por 3 batches sem sobreposição)
```

---

## Stop Rule

- **Não** altere Compose, systemd ou número de workers neste slice.
- **Não** crie migration.
- **Não** implemente gráficos ou histórico de todos os batches.
- **Não** mude lógica clínica ou semântica de retry/batch closure.
- Ao terminar, gere o relatório e **pare** para revisão humana.
