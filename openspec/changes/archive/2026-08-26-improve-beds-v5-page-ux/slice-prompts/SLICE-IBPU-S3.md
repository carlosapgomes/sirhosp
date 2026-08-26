# IBPU-S3 — Fim do N+1 com orçamento de queries

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos do change `improve-beds-v5-page-ux`, os relatórios
   `/tmp/sirhosp-slice-IBPU-S1-report.md` e
   `/tmp/sirhosp-slice-IBPU-S2-report.md` e seus diffs;
3. `apps/census/occupancy.py` — `resolve_exact_measurement`,
   `build_units_presentation`, `_catalog_components`, `_v5_units`,
   `_v5_unmapped_units` e o uso de `measurement.catalog.groups` /
   `definition.memberships`;
4. `apps/census/views.py` — caminho até `resolve_exact_measurement` e
   `build_units_presentation`;
5. `tests/unit/test_bed_status_view.py` — helpers de medição v5 e testes de
   renderização autenticada;
6. seção "D6 — Fim do N+1 com orçamento de queries" do `design.md`.

Entrada esperada: com S1 e S2 completos, a página v5 está correta e completa,
mas a renderização autenticada executa uma query por grupo do catálogo e uma
por membership (padrão N+1): a auditoria de produção do CIPOO-S6 mediu ~140
queries para 42 unidades/43 grupos. `resolve_exact_measurement` já faz
`select_related("catalog")` e `prefetch_related("groups")` (grupos da
medição), porém o grafo do catálogo (`catalog.groups.all()` e
`definition.memberships.all()`, consumido por `_catalog_components` e
`_v5_units`) não é prefetched.

Este slice corrige exclusivamente o custo de queries. Não altera
comportamento, cálculo persistido, catálogo, modelos, migrations, template
nem branches v1–v4.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer falha implica `INCOMPLETE`, sem tasks/commit/push.

1. Registre `BASE_REF=$(git rev-parse HEAD)`, árvore limpa e matriz
   requisito→arquivo→teste.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`, com exit code
   e passed/failed/errors. Falha bloqueia.
3. Meça e registre no relatório a contagem de queries atual da página (ver
   RED) antes de qualquer edição — este número é a evidência do problema.
4. Testes RED primeiro; ao menos um teste novo deve falhar pelo motivo
   esperado (crescimento linear de queries) antes da implementação.
5. GREEN mínimo em até 3 arquivos rastreados; sem refactor fora do escopo.
6. Rode as inspeções `rg` obrigatórias, depois todos os gates oficiais e
   Markdown lint.
7. Final exit 0, zero failures/errors e passed >= baseline.
8. Relatório completo; somente então tasks 3.x, commit/push e STOP.

## Objetivo vertical

A página `/beds` autenticada, com medição v5 exact-run, executa um número de
queries que não cresce com o número de grupos/memberships do catálogo,
comprovado por teste de orçamento automatizado. Nenhuma mudança visível de
comportamento; todos os testes de S1/S2 e de regressão permanecem verdes.

## Requisitos funcionais

### R1 — Teste de orçamento de queries

Criar teste que renderiza `/beds` autenticado (mesmo caminho dos testes
atuais) duas vezes com dados sintéticos independentes:

- cenário A: medição v5 exact-run cujo catálogo tem **4 grupos**, cada um com
  1 membership (mais snapshots/censo suficientes para a página renderizar);
- cenário B: medição v5 exact-run mais recente com catálogo de **12 grupos**,
  cada um com 1 membership.

Capturar o número de queries de cada renderização (por exemplo,
`django.test.utils.CaptureQueriesContext` ou `django_assert_num_queries` do
pytest-django) e exigir `queries_B - queries_A <= 8`. Com o N+1 atual, a
diferença é aproximadamente 2 × (12 − 4) = 16, portanto o teste falha (RED).
Registrar no relatório as contagens A/B antes e depois da correção.

### R2 — Prefetch no caminho exact-run

Eliminar o padrão N+1 acrescentando prefetch de
`catalog__groups__memberships` no ponto mais estreito e correto do caminho
da página — candidato natural: o queryset de `resolve_exact_measurement`,
que já faz `select_related("catalog").prefetch_related("groups")`. Se a
implementação provar que o ponto correto é outro (por exemplo, na view),
justifique no relatório com medições. É proibido: desligar o teste,
aumentar a folga do orçamento além de 8, cache global ou manual de objetos,
duplicar consultas por unidade.

### R3 — Comportamento inalterado

Nenhuma mudança de renderização, valores, ordenação ou conteúdo. Todos os
testes existentes (unit + integration) permanecem verdes sem edição de
expectativas. Se algum teste precisar mudar, o slice está incompleto — trate
como bloqueio.

### R4 — Sem danos a outros consumidores

`resolve_exact_measurement` pode ter outros consumidores além da página
`/beds`. Verificar com `rg` e, se o prefetch adicionado representar custo
desnecessário a outro fluxo, preferir o ponto que atenda somente à página,
documentando a decisão. Nada de measurement nova é criada; nada é recalculado.

## Arquivos esperados e limite

Máximo **3 arquivos rastreados**:

1. `apps/census/occupancy.py` — prefetch (ou ajuste equivalente comprovado);
2. `apps/census/views.py` — somente se o ponto correto do prefetch ficar na
   view (justificar);
3. `tests/unit/test_bed_status_view.py` — teste de orçamento.

Se precisar de quarto arquivo ou alterar model/migration/template/catalog,
pare e reporte bloqueio.

## TDD obrigatório

### RED

1. Escrever o teste de orçamento (R1) e rodá-lo: deve falhar com
   `queries_B - queries_A` ≈ 16 > 8, provando o crescimento linear.
2. Registrar no relatório a saída do teste com as contagens reais medidas.

RED que passa antes da implementação não prova nada: aumente o número de
grupos do cenário B ou corrija o teste.

### GREEN

Acrescentar o prefetch e rodar o teste: `queries_B - queries_A` deve cair
para dentro da folga (idealmente 0–2). Rodar a suíte completa.

### REFACTOR

Nenhum além de manter o código limpo; este slice é cirúrgico. Não refatorar
funções vizinhas.

## Checks de inspeção obrigatórios

```bash
rg -n "resolve_exact_measurement" apps/ tests/ | grep -v test_release
rg -n "prefetch_related" apps/census/occupancy.py apps/census/views.py
rg -n "catalog__groups__memberships" apps/census/occupancy.py \
  apps/census/views.py
rg -n "CaptureQueriesContext|django_assert_num_queries|assertNumQueries" \
  tests/unit/test_bed_status_view.py
```

Interpretação obrigatória: listar todos os consumidores de
`resolve_exact_measurement` e confirmar que o prefetch não altera o
comportamento deles; o prefetch novo deve existir em exatamente um ponto; o
teste de orçamento deve capturar queries do request autenticado completo.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate improve-beds-v5-page-ux --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] Teste de orçamento automatizado (4 vs 12 grupos, folga ≤ 8) passando.
- [ ] Contagens A/B medidas e registradas antes (≈16 de diferença) e depois.
- [ ] Prefetch em um único ponto, sem cache manual.
- [ ] Zero mudança de comportamento; nenhum teste editado.
- [ ] Consumidores de `resolve_exact_measurement` auditados por `rg`.
- [ ] Até 3 arquivos e todos os gates verdes.

### Condições automáticas de INCOMPLETO

- baseline/RED/gates ausentes ou falhos;
- teste de orçamento não falhou antes da correção (RED não real);
- contagens antes/depois não registradas no relatório;
- folga do orçamento aumentada além de 8 para fazer passar;
- teste desligado, pulado ou convertido em smoke sem contagem;
- qualquer expectativa de teste existente editada para passar;
- comportamento/valores de renderização mudaram;
- prefetch duplicado em mais de um ponto ou cache manual introduzido;
- consumidor externo de `resolve_exact_measurement` quebrado;
- quarto arquivo sem bloqueio prévio;
- relatório ausente ou passed final menor que baseline.

## Gates de autoavaliação

1. Quais foram as contagens A/B antes e depois, com os comandos exatos?
2. Por que o ponto escolhido para o prefetch é o mais estreito e correto?
3. Quais outros consumidores usam `resolve_exact_measurement` e por que não
   foram afetados?
4. Por que a folga de 8 é suficiente e não frágil em CI?
5. Qual evidência prova zero mudança de comportamento?
6. O teste captura o request autenticado completo (login + GET `/beds`)?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-IBPU-S3-report.md` com status, BASE_REF, matriz
requisito→arquivo→teste, medição de queries antes/depois com números reais e
comandos, evidência RED/GREEN, snippets antes/depois, inspeções `rg` e
interpretação (incluindo a lista de consumidores), baseline versus final
(exit, passed, failed, errors), gates, Markdown lint, arquivos alterados e
justificativas, riscos e `Handoff para verificador` R1–R4 com comandos
exatos de rerun. Nunca incluir dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete improve-beds-v5-page-ux
change, the S1/S2 reports and diffs, and SLICE-IBPU-S3.md. Implement ONLY S3
under the mandatory DeepSeek4-Flash protocol: BASE_REF, official container
baseline, measure and record the current authenticated /beds query counts
first, then write a real RED query-budget test (4-group catalog vs 12-group
catalog, difference <= 8) proving linear growth, then fix the catalog
groups/memberships N+1 with a single prefetch at the narrowest correct
point (candidate: resolve_exact_measurement), with no behavior change, no
edited expectations, no manual caches and no widened budget. Audit every
resolve_exact_measurement consumer with rg. Run all official gates and
Markdown lint. On any failure report INCOMPLETE without tasks/commit.
Otherwise create /tmp/sirhosp-slice-IBPU-S3-report.md with before/after
query counts, RED/GREEN evidence, snippets, gates, rerun commands and
verifier handoff; mark only 3.x in tasks.md, commit, push, reply
REPORT_PATH=..., then STOP.
```
