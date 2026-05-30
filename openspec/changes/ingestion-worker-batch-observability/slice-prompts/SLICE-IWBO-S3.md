# SLICE-IWBO-S3: Detalhe de batch e execuções sob demanda

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
8. `/projects/dev/sirhosp/openspec/changes/ingestion-worker-batch-observability/slice-prompts/SLICE-IWBO-S2.md`

**Implemente SOMENTE o Slice IWBO-S3 e PARE.**

Pré-condição esperada: IWBO-S2 já adicionou tabela histórica paginada de
batches com links `?batch_id=<id>`.

Não leia nem exponha `.env`. Não imprima dados reais de pacientes. Use apenas
fixtures sintéticas em testes.

---

## Objetivo

Alterar a página `/metrica-ingestao/` para que a tabela de `Execuções` não
liste todos os jobs globalmente por padrão. A lista de jobs deve aparecer
somente quando o usuário seleciona um batch específico na tabela histórica,
abrindo:

```text
/metrica-ingestao/?batch_id=<id>
```

Nesse modo, a tabela de execuções deve mostrar **somente jobs daquele batch**.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 4 arquivos**:

| Arquivo | Ação esperada |
| --- | --- |
| `apps/services_portal/views.py` | Modo detalhe por `batch_id` e queryset de jobs filtrado |
| `apps/services_portal/templates/services_portal/ingestion_metrics.html` | Renderização condicional da tabela `Execuções` |
| `tests/unit/test_services_portal_ingestion_metrics.py` | Testes de default sem execuções globais e detalhe por batch |
| `openspec/changes/ingestion-worker-batch-observability/tasks.md` | Marcar checklist do slice ao final |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio** no
relatório.

---

## Requisitos funcionais

### 1. Visão padrão sem execuções globais

Quando o usuário acessa:

```text
/metrica-ingestao/
```

sem `batch_id`, a página deve:

- mostrar a tabela histórica de batches criada no IWBO-S2;
- não renderizar a tabela global de `Execuções`;
- mostrar orientação textual simples, por exemplo:

```text
Selecione um batch para ver as execuções detalhadas.
```

### 2. Detalhe de batch selecionado

Quando o usuário acessa:

```text
/metrica-ingestao/?batch_id=<id>
```

com batch existente, a página deve:

- carregar o `CensusExecutionBatch` selecionado;
- mostrar um resumo do batch selecionado;
- renderizar a tabela `Execuções` com `IngestionRun.objects.filter(batch_id=id)`;
- não incluir jobs de outros batches;
- manter link claro para voltar ao histórico sem `batch_id`.

### 3. Filtros dentro do batch

Os filtros existentes de `status`, `intent` e `failure_reason` podem continuar
existindo, mas quando `batch_id` estiver presente devem ser aplicados **dentro
do batch selecionado**, não na base global.

Exemplo:

```text
/metrica-ingestao/?batch_id=13&status=failed
```

Deve listar apenas jobs falhos do batch 13.

### 4. Batch inválido

Quando `batch_id` for inválido ou inexistente:

- não listar execuções globais como fallback;
- renderizar estado amigável ou 404 controlado;
- manter link para voltar ao histórico.

Preferência: estado amigável com HTTP 200 para manter simplicidade da tela, a
menos que o padrão do projeto favoreça 404.

### 5. Paginação de execuções do batch

Se a tabela de execuções do batch puder ficar grande, adicione paginação
server-side usando parâmetro separado, por exemplo:

```text
run_page=2
```

Não reutilize `batch_page`, que é da tabela histórica.

---

## Metodologia TDD

### RED 1 — default sem execuções globais

Crie teste que:

1. cria dois batches e runs em cada um;
2. acessa `/metrica-ingestao/` sem `batch_id`;
3. verifica que a tabela histórica aparece;
4. verifica que a tabela/lista global de `Execuções` não aparece;
5. verifica que há mensagem orientando selecionar um batch.

### RED 2 — detalhe lista somente jobs do batch

Crie teste que:

1. cria `batch_a` com run `A-ONLY` em parâmetro sintético ou label visível;
2. cria `batch_b` com run `B-ONLY`;
3. acessa `/metrica-ingestao/?batch_id=<batch_a.id>`;
4. verifica que `A-ONLY` aparece;
5. verifica que `B-ONLY` não aparece.

Use apenas identificadores sintéticos, nunca prontuários reais.

### RED 3 — filtros dentro do batch

Crie teste que:

1. cria no mesmo batch runs `succeeded` e `failed`;
2. acessa `?batch_id=<id>&status=failed`;
3. verifica que só o run falho do batch selecionado aparece.

### RED 4 — batch inválido

Crie teste que acessa `?batch_id=999999` e valida que:

- a resposta não lista execuções globais;
- há estado vazio/erro amigável;
- há link para voltar ao histórico.

### RED 5 — paginação de execuções, se implementada

Se adicionar paginação de execuções, crie teste com mais runs do que o page size
validando `run_page=2`.

### GREEN

Implemente o mínimo para passar os testes:

- parsing seguro de `batch_id`;
- selected batch no contexto;
- queryset de runs apenas quando há batch válido;
- renderização condicional da tabela;
- filtros aplicados dentro do batch.

### REFACTOR

Depois de verde:

- remover duplicação entre query global antiga e query por batch;
- manter nomes de contexto claros, por exemplo `selected_batch`,
  `selected_batch_runs`, `show_run_details`;
- preservar a tabela histórica do IWBO-S2;
- evitar fallback para todos os jobs em qualquer caminho de erro.

---

## Critérios de aceite

- [ ] `/metrica-ingestao/` sem `batch_id` não mostra execuções globais.
- [ ] A página orienta o usuário a selecionar um batch.
- [ ] `?batch_id=<id>` mostra somente jobs daquele batch.
- [ ] Filtros de status/intent/failure_reason atuam dentro do batch.
- [ ] Batch inválido não vaza/lista jobs globais.
- [ ] Há link para voltar ao histórico de batches.
- [ ] Nenhuma migration foi criada.
- [ ] Nenhum dado real/sensível foi exposto.
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

Se algum comando falhar, corrija a causa raiz. Não use
`<!-- markdownlint-disable -->`.

---

## Atualização de tasks

Ao final, marque em
`openspec/changes/ingestion-worker-batch-observability/tasks.md` os itens do
Slice IWBO-S3 realmente concluídos.

Não marque itens se os gates correspondentes não tiverem sido executados ou se
falharam.

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-IWBO-S3-report.md` com **exatamente** estas seções:

```markdown
# Relatório SLICE-IWBO-S3

## 1. Resumo
(2-3 frases sobre o que foi implementado)

## 2. Checklist de aceite
- [ ] visão padrão sem execuções globais
- [ ] detalhe por batch implementado
- [ ] filtros aplicados dentro do batch
- [ ] batch inválido não vaza execuções globais
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
(Explique limitações, especialmente se paginação de execuções não foi necessária)

## 7. Próximo passo sugerido
Rodar experimento operacional comparando 10, 12 e 15 workers sem batches sobrepostos
```

---

## Stop Rule

- **Não** crie nova rota se `?batch_id=<id>` atender ao requisito.
- **Não** crie migration.
- **Não** implemente gráficos, exportação ou persistência de agregados.
- **Não** altere worker, Compose ou systemd neste slice.
- Ao terminar, gere o relatório e **pare** para revisão humana.
