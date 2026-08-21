# SLICE-CCO3A-S4 — Apresentação `/beds` e decisão arquitetural

## Handoff para implementador LLM com contexto zero

Implemente somente CCO3A-S4, último slice de código do change. Leia:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. proposal, design, tasks e as cinco delta specs deste change;
3. este prompt;
4. implementação final e relatórios S1–S3;
5. `apps/census/occupancy.py` na seção de presentation helpers;
6. `apps/census/views.py` somente para entender o contrato;
7. `apps/census/templates/census/bed_status.html` completo;
8. `tests/unit/test_bed_status_view.py`;
9. `docs/adr/template.md`, `docs/adr/README.md` e ADR-0003.

Pré-condições:

- blocos 1–3 completos e commits integrados;
- domínio S3 persiste v1/v2, cobertura oficial, unknown count e elegibilidade;
- nenhuma ativação real do catálogo corrigido ocorreu;
- view exige medição do run exato e autenticação;
- working tree limpo e baseline verde.

Se algum dado exigido não estiver persistido por S3, não recalcule na view:
pare e reporte bloqueio para correção do slice anterior.

## Protocolo obrigatório para implementador DeepSeek4-Flash

**Qualquer falha torna o slice INCOMPLETO.** Não marque tasks, commit ou push
nesse caso.

1. Registre `BASE_REF`, branch e working tree limpo.
2. Escreva matriz `R → arquivos → testes/inspeções` antes de editar.
3. Rode baseline oficial `./scripts/test-in-container.sh unit`; pare se falhar.
4. Escreva testes RED primeiro e rode `unit`; exija falha funcional esperada.
5. Implemente GREEN mínimo sem cálculo ad hoc no template/view.
6. Faça REFACTOR restrito com clean code, DRY e YAGNI.
7. Execute inspeções, todos os gates, strict OpenSpec e Markdown lint.
8. Gere relatório verificável e lintado.
9. Marque somente 4.1–4.6, faça um commit, push e pare. Não execute tarefas
   operacionais 5.x.

## Objetivo vertical

Entregar valor visível ao usuário autorizado em `/beds`: CO explicitamente fora
da taxa, duas linhas calculadas da 3A, posições sem faixa sem duplicação,
cobertura 39/43, alerta de taxa parcial e regressão v1/fallback. Registrar a
mudança em ADR nova sem reescrever a decisão histórica.

## Requisitos funcionais

### R1 — Exatidão e autorização preservadas

A página usa somente a medição do `IngestionRun` exato já resolvida. Não busca
medição anterior, não calcula percentual/cobertura na view/template e não muda
login/permissões. Sem medição exata, mantém fallback bruto e estatística
pendente.

### R2 — CO corrigido

Para v2, mostrar uma única linha CO com os cinco códigos/componentes e contagens
brutas, contendo textos equivalentes a:

```text
Capacidade não cadastrada
Não incluído na taxa de ocupação da unidade
```

Nunca mostrar 0%, capacidade 8, 675%, numerator ou excedente em CO v2. v1 exato
continua apresentando seus valores históricos persistidos, sem recálculo.

### R3 — Dois setores oficiais da 3A

Mostrar:

```text
Enfermaria 3A – Adulto    capacidade 32
Enfermaria 3A – Infantil  capacidade 16
```

Cada linha usa occupied_count, percentual e exceeded-by persistidos. Cada leito
ocupado com faixa válida aparece exatamente uma vez na expansão correspondente,
mesmo se prontuários coincidirem. Não mostrar mensagem antiga de pares
cama-berço em v2.

### R4 — Agrupamento auxiliar sem faixa

No run exato, leitos `654` não ocupados e ocupados `unknown` aparecem uma única
vez em `3A – posições sem classificação etária` ou texto equivalente. O grupo:

- não é setor oficial;
- não possui capacidade, percentual ou excedente;
- não altera 39/43 ou 666;
- não duplica linha presente em Adulto/Infantil;
- preserva status e detalhe de paciente já autorizado, sem ampliar acesso.

A classificação usa a faixa persistida de S1/S3, não idade bruta nem inferência.

### R5 — Totais e alerta parcial

Para v2, mostrar:

```text
39 de 43 setores oficiais com capacidade cadastrada
39 de 43 setores oficiais com lotação calculável
capacidade conhecida 666
capacidade calculável 666
```

Se unknown occupied count for positivo, rotular a taxa pontual como parcial,
mostrar somente a quantidade agregada omitida e informar que o censo não entra
nas médias oficiais diárias. Não mostrar idade exata no alerta. Com zero
unknown, nenhum alerta parcial aparece.

### R6 — Regressões obrigatórias

Preservar:

- rótulo `Lotação registrada no sistema legado`;
- alertas acessíveis acima de 100%;
- valores v1 44/47, 43/47, 658/626 e CO histórico;
- grupos compartilhados, unmapped e unrated;
- detalhe nominal somente para usuário já autorizado;
- redirect anônimo;
- fallback sem medição e proibição de fallback para run anterior.

### R7 — ADR substitutiva parcial

Criar ADR-0004, ou próximo número livre confirmado, com status `Accepted`, que:

- registra deliberação CO opção A;
- registra 3A por faixa do ocupante, sem pareamento;
- documenta unknown excluído só do ponto e censo excluído do diário;
- registra occupancy-v2, cobertura oficial e vigência pós-deploy;
- declara substituir somente decisões CO/3A da ADR-0003;
- preserva imutabilidade, fotografia completa, não-backfill, privacidade e
  rollback da ADR-0003;
- compara alternativas e riscos;
- não contém dado real.

Atualizar índice. Não editar ADR-0003.

## Arquivos esperados e limite

Máximo de **5 arquivos de implementação/teste/documentação**, além de
`tasks.md`:

1. `apps/census/occupancy.py` somente helpers de apresentação;
2. `apps/census/templates/census/bed_status.html`;
3. `tests/unit/test_bed_status_view.py`;
4. nova `docs/adr/ADR-0004-*.md` ou próximo número livre;
5. `docs/adr/README.md`.

Não altere `views.py` salvo bloqueio comprovado; isso excederia o limite. Não
mude models/migrations/domain materializer para contornar S3. Pare antes de um
sexto arquivo.

Proibido:

- calcular taxa/cobertura no template ou view;
- editar ADR-0003;
- mudar autenticação/rota/permissões;
- alterar JSON/migrations/models/capacity_catalog;
- ativar catálogo, deployar ou publicar release;
- JS/dependência/CSS global novo sem requisito;
- dado real em teste, ADR ou relatório.

## TDD obrigatório

### RED

Adicionar testes sintéticos antes da implementação para:

1. CO v2 uma vez, raw counts, textos e ausência de taxa/capacidade;
2. CO v1 histórico preservado;
3. Adulto 32 e Infantil 16 com percentuais persistidos;
4. ocupados válidos aparecem uma vez no grupo correto;
5. não ocupados e unknown aparecem uma vez no auxiliar;
6. auxiliar não altera oficial coverage;
7. cobertura/totais v2 39/43/666/666;
8. alerta parcial com aggregate count e mensagem diária;
9. ausência de alerta quando completa;
10. v1 44/47/43/47/658/626;
11. sobrelotação acessível;
12. fallback exato, medição antiga não reutilizada e redirect anônimo;
13. HTML não expõe idade exata criada para o teste.

Rode `./scripts/test-in-container.sh unit` e documente RED real.

### GREEN

Estenda `build_official_group_rows` e estruturas de apresentação usando somente
medição persistida mais snapshots do run exato. Para código com duas partições,
mapeie por `(código, age_band)`; trate não aplicável/unknown em auxiliar. O
template apenas renderiza valores prontos.

### REFACTOR

- evite lookup de código que sobrescreva uma das partições;
- garanta one-row-in-one-bucket;
- mantenha helpers coesos e nomes de contexto explícitos;
- não generalize auxiliar para engine arbitrária;
- preserve HTML acessível e Bootstrap existente.

## Checks de inspeção obrigatórios

```bash
rg -n "Capacidade não cadastrada|Não incluído|classificação etária|parcial|média" \
  apps/census/templates/census/bed_status.html
rg -n "OBST-3A-ADULTO|OBST-3A-INFANTIL|age_band|unknown" \
  apps/census/occupancy.py tests/unit/test_bed_status_view.py
rg -n "39|43|666|44|47|658|626" \
  apps/census/templates/census/bed_status.html \
  tests/unit/test_bed_status_view.py
rg -n "login_required|resolve_exact_measurement" apps/census/views.py \
  apps/census/occupancy.py
rg -n "ADR-0003|occupancy-v2|Centro Obstétrico|3A" \
  docs/adr/ADR-0004-*.md docs/adr/README.md
rg -n "idade|age" apps/census/templates/census/bed_status.html
git diff --check
git diff --name-only "$BASE_REF"
git diff "$BASE_REF" -- docs/adr/ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel.md \
  apps/census/models.py apps/census/migrations apps/census/capacity_catalog.py
```

O último diff deve estar vazio. Interprete ocorrências de `idade`: somente texto
agregado de classificação, nunca valor individual. Confirme que nenhum número
de taxa foi hardcoded para cálculo no template.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate correct-co-3a-occupancy-policy --strict
./scripts/markdown-format.sh
./scripts/markdown-lint.sh
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  /tmp/sirhosp-slice-CCO3A-S4-report.md
```

Se `markdown-format.sh` alterar Markdown, reinspecione o diff e rerode strict
OpenSpec e Markdown lint.

## Critérios binários de sucesso

- [ ] R1–R7 cobertos.
- [ ] RED e GREEN comprovados.
- [ ] Nenhuma linha 3A é duplicada ou perdida da apresentação permitida.
- [ ] CO v2 não mostra taxa e CO v1 não é reescrito.
- [ ] V2 mostra 39/43 e 666/666 apenas de valores persistidos.
- [ ] Alerta parcial é agregado e ausência funciona.
- [ ] Auth, fallback exato e sobrelotação permanecem.
- [ ] ADR nova substitui parcialmente, sem editar ADR-0003.
- [ ] Máximo cinco arquivos.
- [ ] Gates e Markdown lint passam; testes finais não regrediram.
- [ ] Relatório completo sem dados sensíveis.

## Gates de autoavaliação

1. Algum cálculo de taxa/cobertura ocorre na apresentação? Deve ser não.
2. Como o lookup evita sobrescrever Adulto por Infantil no código `654`?
3. Cada snapshot 3A aparece em exatamente um local?
4. Auxiliar afeta setor oficial/capacidade? Deve ser não.
5. CO v2 mostra algum 8/675%/excedente? Deve ser não.
6. Qual teste prova CO/v1 histórico?
7. Qual teste prova ausência de fallback de outro run?
8. O alerta revela apenas contagem agregada?
9. Permissão/autenticação mudou? Deve ser não.
10. ADR-0003 teve diff? Deve ser não.
11. A ADR nova explicita quais decisões substitui e quais preserva?
12. O limite de arquivos e todos os gates foram respeitados?

## Condições automáticas de INCOMPLETO

- baseline/RED/gates/relatório ausentes;
- cálculo ad hoc na view/template;
- duplicação ou desaparecimento de snapshot 3A;
- auxiliar contado como oficial;
- CO v2 com taxa/capacidade ou v1 reescrito;
- totais/cobertura divergentes;
- idade exata/PII em alerta, ADR, log ou relatório;
- fallback para medição antiga ou autenticação relaxada;
- ADR-0003 editada;
- models/migration/JSON/domain de S3 alterado;
- mais de cinco arquivos sem bloqueio;
- Markdown lint, strict OpenSpec ou qualquer gate falhar;
- final pytest com failure/error, exit não zero ou menos passed;
- tasks/commit antes dos critérios.

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CCO3A-S4-report.md` com:

- status, BASE_REF, baseline e matriz R1–R7;
- RED/GREEN/REFACTOR e exit codes;
- arquivos e snippets antes/depois por arquivo;
- matriz visual v1/v2 completo/v2 parcial/fallback;
- prova one-row-in-one-bucket com fixture sintética;
- inspeções de template, auth, privacidade e ADR;
- pytest baseline/final e todos os gates;
- respostas aos 12 gates;
- riscos/limitações e comandos de rerun;
- `Handoff para verificador` com commit, arquivos, checklist R1–R7, pontos de
  UI/acessibilidade/ADR e confirmação de nenhuma operação de produção.

## Prompt pronto para o implementador

```text
Read every file in the zero-context handoff of SLICE-CCO3A-S4.md and implement
ONLY the /beds presentation plus superseding ADR slice. Follow the mandatory
DeepSeek4-Flash protocol: clean official baseline, matrix, real RED, minimal
GREEN, bounded clean-code/DRY/YAGNI refactor, rg inspections, all official
container gates, strict OpenSpec, Markdown format/lint, baseline-vs-final and a
verifiable /tmp/sirhosp-slice-CCO3A-S4-report.md. Touch at most the five listed
files. Never calculate official rates in view/template, alter auth, edit ADR-0003
or touch models/migrations/catalog/domain. Do not release, deploy or activate.
If any evidence/gate fails, any row duplicates, privacy is uncertain, final
tests regress, or file limit must be exceeded, report INCOMPLETE and do not mark
tasks, commit or push. Mark only 4.1-4.6 after success, commit, push, reply with
REPORT_PATH, then STOP.
```
