# SLICE-CCO3A-S3 — Materialização occupancy-v2 e resumo elegível

## Handoff para implementador LLM com contexto zero

Implemente somente CCO3A-S3. Leia integralmente antes de editar:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. proposal, design e tasks do change;
3. delta specs `occupancy-measurement-history`, `daily-occupancy-summary` e
   `census-snapshot-processing` deste change;
4. este prompt;
5. models, migrations e implementação finais de S1/S2;
6. `apps/census/occupancy.py` completo;
7. integração em `apps/census/services.py` apenas para entender o fluxo;
8. `tests/unit/test_occupancy_measurement.py` e
   `tests/unit/test_process_census_snapshot.py`;
9. relatórios S1/S2 em `/tmp`, se disponíveis.

Pré-condições:

- blocos 1 e 2 de `tasks.md` completos e commits integrados;
- faixa etária de S1 e seletor de associação de S2 existem;
- novo JSON corrige CO/3A, mas não foi ativado em produção;
- última migration esperada é a de S2, normalmente `0019`; confirme;
- working tree limpo e baseline verde.

Se faltar pré-condição, pare. Não refaça S1/S2 e não implemente UI/ADR.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer etapa faltar, o slice está **INCOMPLETO**: não marque tasks, não
faça commit/push e pare com evidência.

1. Registre `BASE_REF`, branch e working tree limpo.
2. Escreva matriz `R → arquivos → testes` no relatório antes de editar.
3. Rode baseline oficial `./scripts/test-in-container.sh unit`; qualquer
   failure/error bloqueia.
4. Crie testes RED primeiro e execute `unit`. Exija falha funcional esperada.
5. Faça GREEN mínimo somente no domínio de medição/resumo.
6. Faça REFACTOR limitado com clean code, DRY, YAGNI e despacho explícito.
7. Rode inspeções, gates oficiais, strict OpenSpec e comparação baseline/final.
8. Gere relatório lintado com evidência e handoff para terceiro LLM.
9. Marque somente 3.1–3.7, faça um commit, push e pare antes de S4.

## Objetivo vertical

Entregar o fluxo completo
`censo aceito + catálogo aplicável → medição imutável → filhos → resumo diário`,
selecionando v1 ou v2 sem alterar história. O slice termina no domínio
persistido; `/beds` ainda não muda.

## Requisitos funcionais

### R1 — Despacho explícito e estável

- catálogo sem partição etária usa `occupancy-v1` e comportamento atual;
- catálogo com o par etário usa `occupancy-v2`;
- a escolha é determinística pelo contexto persistido do catálogo, não pela data
  corrente ou por hardcode de data;
- medição grava a versão escolhida;
- reexecução do mesmo run retorna a medição existente sem recalcular.

Não substitua globalmente a constante v1 por v2.

### R2 — Aplicação de membership por linha

A linha observada do materializador deve incluir sua faixa persistida. Em v2:

- membro `all` recebe todas as linhas de seu código;
- `under_12` recebe somente ocupado dessa faixa;
- `age_12_or_over` recebe somente ocupado dessa faixa;
- cada linha classificada entra em no máximo um grupo oficial;
- não deduplicar por prontuário e não relacionar linhas;
- componentes históricos copiam código, nome e seletor aplicado.

### R3 — CO corrigido

Sob o catálogo v2, os cinco códigos do CO geram um único filho `CO` `unrated`:

- status_counts brutos preservados;
- capacidade, occupied_count oficial, percentual e exceeded-by nulos;
- nenhum ocupado CO entra no pai hospitalar;
- v1 CO existente e novo censo ainda sob catálogo v1 mantêm cálculo anterior.

### R4 — Dois setores 3A

- Adulto soma ocupados `654/age_12_or_over` sobre 32;
- Infantil soma ocupados `654/under_12` sobre 16;
- não ocupados entram em nenhum numerador etário;
- ambos podem exceder 100%;
- não criar `3A total 48` como terceiro grupo oficial.

### R5 — Idade desconhecida e taxa pontual parcial

Cada ocupado `654/unknown`:

- fica fora dos numeradores Adulto, Infantil e hospitalar;
- não reduz capacidades 32, 16 ou 666;
- incrementa somente contagem agregada auditável;
- torna a medição `age-partial`/não elegível para média diária;
- não bloqueia materialização ou fluxo clínico;
- não copia idade, nome, prontuário ou texto clínico para tabelas/JSON/logs.

A medição pontual continua numérica com os ocupados classificados e deve ser
marcada explicitamente como parcial para S4.

### R6 — Cobertura oficial e diagnósticos

Persistir, sem reinterpretar v1:

```text
setores oficiais v2: 43
com capacidade: 39
calculáveis: 39
capacidade conhecida: 666
capacidade calculável: 666
```

Manter os diagnósticos existentes de códigos observados/cobertos para qualidade
da extração. Código desconhecido continua `unmapped`, não altera 39/43 e não
bloqueia.

### R7 — Resumo diário elegível

Toda medição do dia conta na auditoria, mas medição v2 com unknown age na 3A é
excluída integralmente de todos os campos oficiais de média, mínimo, máximo e
excedente do pai e dos grupos. Persistir:

- measurement_count total;
- eligible/calculation measurement count;
- age-excluded measurement count.

Elegíveis mantêm peso igual e arredondamento final. Se todas forem excluídas,
criar resumo auditável com campos estatísticos oficiais nulos, nunca zeros ou
valor anterior. v1 é sempre elegível e resumos históricos não são reconstruídos.

### R8 — Fluxo clínico não bloqueado

Censo completo com idade desconhecida cria medição parcial e continua criação
de batch/runs clínicos. Erro estrutural real mantém comportamento seguro atual.
Nenhuma mudança em completude, fila, paciente ou movimento.

### R9 — Privacidade e imutabilidade

Pais, filhos, components e resumos contêm somente agregados. Reexecução,
catálogo futuro e mudança de algoritmo não alteram medição/resumo existente.
Sem backfill ou comando de varredura.

## Arquivos esperados e limite

Máximo de **5 arquivos de implementação/teste**, além de `tasks.md`:

1. `apps/census/models.py`;
2. nova migration `apps/census/migrations/0020_*.py` ou próximo número livre;
3. `apps/census/occupancy.py`;
4. `tests/unit/test_occupancy_measurement.py`;
5. `tests/unit/test_process_census_snapshot.py` somente para R8.

Não altere `services.py` se a integração atual já permite o resultado parcial.
Se uma mudança nele for inevitável, pare antes: seria sexto arquivo e exige
replanejamento. Descubra o próximo número real da migration.

Proibido:

- alterar migrations/JSON/capacity_catalog de S1/S2;
- template, view ou ADR;
- ativação real ou data hardcoded;
- campo com idade exata;
- Celery/Redis/dependência nova;
- reprocessar história;
- dado real em teste/relatório.

## TDD obrigatório

### RED

Testes sintéticos obrigatórios:

1. catálogo v1 continua `occupancy-v1` com 658/626 e CO calculado;
2. catálogo particionado escolhe `occupancy-v2`;
3. Adulto e Infantil calculam separadamente 32/16;
4. duas linhas com mesmo prontuário contam duas vezes por sua própria faixa;
5. não ocupados não entram nos grupos etários;
6. unknown ocupado exclui apenas a linha, mantém 666 e marca parcial;
7. CO v2 guarda raw counts e todos os campos de taxa nulos;
8. total v2 39/43 e 666/666;
9. sobrelotação v2 não é limitada;
10. código desconhecido não muda cobertura oficial;
11. medição parcial persiste e não bloqueia processamento clínico;
12. resumo misto registra total/elegível/excluído e usa somente elegíveis;
13. dia só parcial possui estatísticas nulas;
14. idempotência e privacidade.

Rode `./scripts/test-in-container.sh unit` e registre RED funcional.

### GREEN

Estenda o domínio atual; não crie materializador paralelo completo. Separe
funções pequenas para selecionar algoritmo, combinar membership/linha e avaliar
elegibilidade diária. Use transação/idempotência existentes.

### REFACTOR

Após verde:

- uma única fonte para `occupied_for_rate` e cobertura;
- nenhuma condição por data/código especial fora do dado de catálogo;
- nomes explícitos para total versus elegível;
- JSON agregado limitado e determinístico;
- preserve caminho v1 coberto por regressão.

## Checks de inspeção obrigatórios

```bash
rg -n "occupancy-v1|occupancy-v2|algorithm_version" \
  apps/census/occupancy.py tests/unit/test_occupancy_measurement.py
rg -n "under_12|age_12_or_over|unknown|partial|eligible|excluded" \
  apps/census/models.py apps/census/occupancy.py \
  tests/unit/test_occupancy_measurement.py
rg -n "known_capacity|calculable_capacity|official_sector|666|658|626" \
  apps/census/occupancy.py tests/unit/test_occupancy_measurement.py
rg -n "nome|prontuario|idade|exact_age" apps/census/occupancy.py
rg -n "activate_sector_capacity_catalog" apps/census/occupancy.py || true
git diff --check
git diff --name-only "$BASE_REF"
git diff "$BASE_REF" -- apps/census/data apps/census/capacity_catalog.py \
  apps/census/migrations/0014_capacity_catalog.py
```

Interprete cada ocorrência potencialmente sensível. `nome` pode existir apenas
na leitura transitória/apresentação histórica já sanitizada, nunca em aggregate
JSON novo. O diff dos artefatos S1/S2 protegidos deve estar vazio.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate correct-co-3a-occupancy-policy --strict
./scripts/markdown-lint.sh
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  /tmp/sirhosp-slice-CCO3A-S3-report.md
```

## Critérios binários de sucesso

- [ ] R1–R9 têm teste/implementação.
- [ ] RED real e GREEN registrados.
- [ ] v1 permanece byte-semanticamente equivalente nos valores testados.
- [ ] v2 produz CO null-rated, 3A 32/16 e 39/43/666/666.
- [ ] Unknown exclui só a linha no ponto e o censo inteiro no diário.
- [ ] Dia sem elegível não fabrica estatística.
- [ ] Fluxo clínico não é bloqueado.
- [ ] Nenhum identificador/idade exata entra no histórico.
- [ ] Máximo de cinco arquivos respeitado.
- [ ] Todos os gates passam e final não reduz `passed`.
- [ ] Relatório lintado e verificável.

## Gates de autoavaliação

1. O que determina v1/v2 e por que não depende da data corrente?
2. Um mesmo snapshot pode entrar em dois grupos oficiais? Deve ser não.
3. Prontuário é lido para deduplicar ocupação? Deve ser não.
4. CO v2 contribui algum numerador/capacidade? Deve ser não.
5. Unknown altera denominador? Deve ser não.
6. Como o revisor distingue taxa pontual parcial de completa?
7. Como total diário, elegível e excluído são comprovados?
8. Se todas as medições forem parciais, quais campos ficam nulos?
9. Algum dado paciente-específico foi persistido/logado? Deve ser não.
10. Qual teste prova v1 e idempotência?
11. O processamento clínico continua após partial?
12. O limite de arquivos foi respeitado?

## Condições automáticas de INCOMPLETO

- baseline, RED, gates ou relatório sem evidência;
- v1 quebrado/reinterpretado;
- despacho global para v2 ou dependente de data hardcoded;
- CO v2 com capacidade, percentual ou contribuição hospitalar;
- linha 3A duplicada/deduplicada por prontuário;
- unknown inferido, oculto, reduzindo capacidade ou bloqueando clínica;
- medição parcial incluída em qualquer média oficial diária;
- dia sem elegível recebe zero/valor anterior;
- PII ou idade exata em histórico/log/relatório;
- arquivo S1/S2/UI/ADR alterado;
- mais de cinco arquivos sem replanejamento;
- qualquer failure/error, exit code não zero ou redução de passed;
- tasks/commit antes de tudo passar.

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CCO3A-S3-report.md` com:

- status, BASE_REF e baseline;
- matriz R1–R9;
- RED/GREEN/REFACTOR com comandos, exit codes e resumos;
- arquivos e snippets antes/depois por arquivo;
- tabela de casos v1, v2 completo e v2 parcial com valores esperados/obtidos;
- prova de resumo misto e somente parcial;
- prova agregada de fluxo clínico continuado;
- inspeções e análise de privacidade;
- pytest baseline versus final;
- todos os gates;
- respostas aos 12 gates;
- riscos, limitações e rerun;
- `Handoff para verificador` com commit, arquivos, checklist R1–R9 e pontos de
  auditoria transacional/privacidade.

Use somente fixtures sintéticas e não inclua nomes/prontuários reais.

## Prompt pronto para o implementador

```text
Read every zero-context handoff file in SLICE-CCO3A-S3.md and implement ONLY the
vertical occupancy-v2/materialization/daily-summary slice. Follow the mandatory
DeepSeek4-Flash protocol: clean official baseline, requirement matrix, real RED,
minimal GREEN, bounded clean-code/DRY/YAGNI refactor, mandatory rg inspections,
all official container gates, strict OpenSpec validation, baseline-vs-final
comparison and a complete report at
/tmp/sirhosp-slice-CCO3A-S3-report.md. Touch at most the five listed files.
Preserve v1, S1/S2 artifacts and clinical flow; do not implement UI, ADR,
activation or exact-age persistence. If any requirement/evidence/gate is
missing, final tests fail or regress in count, privacy is uncertain, or the file
limit must be exceeded, report INCOMPLETE and do not mark tasks, commit or push.
Mark only 3.1-3.7 after success, commit, push, reply with REPORT_PATH, then STOP.
```
