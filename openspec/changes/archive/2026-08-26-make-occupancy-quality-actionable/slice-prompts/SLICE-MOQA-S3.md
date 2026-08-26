# MOQA-S3 — Resumos separados e listagem única acionável em `/beds`

## Handoff para implementador com contexto zero

Você está no terceiro e último slice de implementação do change
`make-occupancy-quality-actionable`. Assuma contexto zero.

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. todos os artefatos deste change;
3. prompts S1/S2 e relatórios temporários correspondentes;
4. ADR-0003, ADR-0004 e ADR-0005 e `docs/adr/template.md`;
5. `apps/census/occupancy.py`, especialmente helpers de apresentação;
6. `apps/census/views.py` e URLs de census;
7. `apps/census/templates/census/bed_status.html` integralmente;
8. `tests/unit/test_bed_status_view.py`;
9. catálogo v4 e campos de alias entregues em S2.

Pré-condições:

- S1 e S2 completos, commitados/pushed, árvore limpa;
- v4 persiste reconciliação schema 2 e warning elegível;
- catálogo v4 persiste `source_display_name` limpo;
- página atual tem dois resumos e duas listas detalhadas;
- detalhes físicos atuais normalizam posições, mas conflitos mostram uma posição
  sem alternativas nominais;
- `build_official_group_rows` contém vínculos com linhas brutas que não podem ser
  simplesmente renderizados em v4, pois isso repetiria duplicatas/conflitos;
- exact-run e `login_required` são invariantes.

Objetivo: manter dois resumos agregados, trocar “sistema legado” por “sistema de
origem” e renderizar uma única lista `Setores e posições` construída por
componentes do grafo grupo↔código. Cada posição aparece uma vez; aliases limpos
são primários; todos os autenticados podem expandir alternativas conflitantes e
linhas sem posição, sem autoridade escolhida e sem persistência adicional.

## Protocolo obrigatório para DeepSeek4-Flash

Qualquer falha torna o slice **INCOMPLETO**; não marcar tasks nem commit/push.

1. Matriz R→arquivo→teste/inspeção antes de editar.
2. `BASE_REF`, árvore limpa, confirmação dos relatórios/commits S1/S2.
3. Baseline `./scripts/test-in-container.sh unit` antes de editar com exit 0,
   passed e zero failed/errors.
4. Testes RED primeiro para UI, grafo, autorização e regressões.
5. GREEN mínimo somente nos seis arquivos permitidos.
6. REFACTOR clean/DRY/YAGNI; uma fonte de verdade para unidades e posições.
7. Inspeções obrigatórias com interpretação, inclusive HTML/labels/permissão.
8. Gates oficiais em container, integração e Markdown lint.
9. Final unitário sem failures/errors e `passed_final >= passed_baseline`.
10. Relatório sem dados reais, com evidência e handoff para terceiro LLM.

## Objetivo vertical

Para o censo exact-run v4 mais recente, um usuário autenticado deve ver:

1. resumo `Capacidade oficial e ocupação`;
2. resumo `Posições registradas no sistema de origem`;
3. ponte `Como as ocupações foram tratadas`;
4. uma única lista `Setores e posições`;
5. cada unidade com indicadores oficiais, fontes limpas, posições únicas e
   casos de qualidade acionáveis.

Anônimo continua 302. V1–v3 continuam históricos sem reinterpretar valores.

## Requisitos funcionais

### R1 — Unidade derivada do grafo, sem hardcode

Criar helper de apresentação puro para componentes conexos no grafo bipartido:

- nós de grupo: measurements/grupos oficiais exact-run;
- nós de fonte: códigos presentes em components/memberships exact-run;
- arestas: memberships persistidas no contexto da medição/catalog;
- cada componente gera uma unidade;
- fonte unmapped gera unidade própria.

Proibir branches por código `654`, stable key CO ou nomes Cardio. Testar:

- 1 grupo ↔ 1 fonte;
- 1 grupo ↔ 2 fontes;
- 2 grupos ↔ 1 fonte;
- 1 grupo unrated ↔ várias fontes;
- unmapped.

### R2 — Título e aliases determinísticos

Título:

- um grupo: `display_name` do grupo;
- vários grupos e uma fonte: `source_display_name`;
- demais: nomes oficiais ordenados deterministicamente.

Cada fonte usa alias v4 como primário. Nome bruto aparece somente subordinado
como `Nome no sistema de origem`. Histórico sem alias usa fallback documentado,
sem consulta ao catálogo atual e sem regex.

### R3 — Dois resumos, uma lista

Template v4 deve ter exatamente:

- os dois headings agregados separados e simultâneos;
- nenhuma aba;
- uma ponte agregada;
- uma seção detalhada `Setores e posições`;
- nenhuma segunda lista longa oficial/física.

Cada unidade expansível mostra mini-tabela oficial e mini-resumo de origem. Não
calcular taxa/capacidade na view; usar medição persistida.

### R4 — Uma posição física uma vez

Reutilizar a mesma normalização v4 de S1:

- posição inequívoca aparece uma vez;
- occupant conflict aparece uma posição ocupada com warning, não múltiplas
  posições;
- status/age conflict aparece um caso físico, sem status vencedor;
- duplicata exata não repete detalhe;
- 3A física aparece uma vez mesmo com duas linhas oficiais;
- fontes compartilhadas não duplicam capacidade.

Não renderizar diretamente `row.beds` bruto dos cards oficiais.

### R5 — Terminologia de tratamento

Usar `Como as ocupações foram tratadas` e rótulos explícitos:

- `Linhas duplicadas consolidadas` + “posição contada uma vez”;
- occupant conflict: posição computada uma vez com ocupante não autoritativo;
- status conflict: posição/linhas não computadas por status ambíguo;
- age conflict: não atribuída a grupo etário;
- ocupado sem leito: `não computadas por ausência de posição`;
- unrated: `posição válida fora do escopo da taxa oficial`;
- unmapped e linked-pending separados.

Alertas agregados não contêm PHI.

### R6 — “Sistema de origem”

Substituir na UI v4 e textos gerais da página:

- heading físico;
- cards, explicações, tooltips e status de conflito;
- `Conflito no sistema de origem` em vez de legado;
- nome bruto rotulado `Nome no sistema de origem`.

Não precisa reescrever nomes técnicos históricos em specs/ADRs anteriores.

### R7 — Detalhes para todo autenticado

Dentro do collapse da unidade:

- listar cada alternativa única de occupant/status/age conflict;
- mostrar ocorrência equivalente sem repetir duplicatas;
- permitir detalhe nominal já autorizado e links existentes;
- rotular todas como `registro divergente — não autoritativo`;
- não escolher primeiro/último/preferido;
- listar ocupado sem leito em bloco separado e não chamá-lo de posição.

Esses objetos podem existir apenas em memória da renderização exact-run. Não
persistir, logar ou incluir em relatório.

### R8 — Qualidade e elegibilidade v4

Se v4 warning:

- badge `com ressalvas de qualidade`;
- cards usam `Ocupações consideradas`;
- texto explica que a medição continua elegível para estatística diária;
- não usar `(parcial)` com explicação v3 de inelegibilidade.

V3 parcial mantém texto histórico de inelegibilidade.

### R9 — Exact-run, fallback e autenticação

- medição deve pertencer ao run exato do snapshot mais recente;
- sem medição exata, resumo oficial fica pendente e origem/lista continuam;
- nunca reutilizar measurement/alias de run antigo;
- `@login_required` preservado;
- anônimo 302;
- todos os autenticados, não apenas staff, veem os casos já autorizados.

### R10 — ADR substitutiva parcial

Criar ADR-0006 e índice. Registrar:

- por que tolerância zero foi substituída apenas em v4;
- conflitos tipados e occupant conflict contado;
- elegibilidade com warning;
- aliases temporais;
- “sistema de origem”;
- dois resumos e lista única por componente;
- detalhe para autenticados e fronteira de PHI;
- v1–v3/ADR-0005 preservados historicamente;
- ativação futura e correção forward.

## Arquivos esperados e limite rígido

Máximo: **6 arquivos**:

1. `apps/census/occupancy.py`;
2. `apps/census/views.py`;
3. `apps/census/templates/census/bed_status.html`;
4. `tests/unit/test_bed_status_view.py`;
5. `docs/adr/ADR-0006-*.md`;
6. `docs/adr/README.md`.

Não criar CSS/JS se Bootstrap existente atende. Se precisar de sétimo arquivo,
pare bloqueado e justifique; não expandir silenciosamente.

## Fora de escopo

Não alterar:

- models, migrations, catálogo/parser/JSON;
- semântica de materialização/resumo de S1;
- services clínicos, ingestion, pacientes ou automação;
- URLs/permissões;
- ADR-0003/0004/0005;
- release/deploy/ativação;
- snapshots ou dados reais.

Não adicionar dependência frontend/backend.

## TDD obrigatório

### RED

Criar testes sintéticos para:

1. dois headings agregados + uma seção detalhada;
2. ausência de tabs e de segunda lista longa;
3. termo `sistema de origem` e ausência de `sistema legado` no HTML;
4. alias limpo primário e nome bruto subordinado;
5. componente 1↔1;
6. Cardio 1↔2 sem capacidade duplicada;
7. 3A 2↔1 com posição física uma vez;
8. CO 1↔N unrated e fontes limpas;
9. unmapped em unidade própria;
10. duplicata consolidada sem repetição;
11. occupant conflict contado, alternativas visíveis e não autoritativas;
12. status/age conflict sem vencedor;
13. ocupado sem leito em bloco acionável, não posição;
14. rótulos de tratamento e fora da taxa;
15. v4 warning elegível;
16. v3 partial mantém texto histórico;
17. usuário autenticado não-staff vê detalhes;
18. anônimo 302;
19. exact-run pending e older measurement não reutilizado;
20. alertas agregados sem marcadores nominais sintéticos.

Rodar unit oficial e registrar RED funcional.

### GREEN

Implementar helper/view/template/ADR mínimos. Não usar cálculo oficial ad hoc.

### REFACTOR

- dataclasses de apresentação coesas;
- construção de componente determinística e linear;
- um normalizador compartilhado, sem repetir regras S1;
- template sem lógica de domínio complexa;
- partials só se indispensáveis — exigiriam arquivo extra e bloqueio;
- sem JavaScript customizado;
- nomes claros, sem comentários de conversa ou branches especiais.

## Checks de inspeção obrigatórios

```bash
rg -n "@login_required|bed_status_view|resolve_exact_measurement" \
  apps/census/views.py
rg -n "Capacidade oficial e ocupação|Posições registradas no sistema de origem|Como as ocupações foram tratadas|Setores e posições" \
  apps/census/templates/census/bed_status.html
rg -n "sistema legado|Conflito no legado|Lotação registrada" \
  apps/census/templates/census/bed_status.html
rg -n "data-bs-toggle=\"tab\"|data-bs-toggle=\"collapse\"" \
  apps/census/templates/census/bed_status.html
rg -n "654|OBST-3A|Centro Obstétrico|ENF-2B-CARD" \
  apps/census/occupancy.py apps/census/views.py
rg -n "source_display_name|configured_source_name|presentation.*unit|component" \
  apps/census/occupancy.py apps/census/views.py
rg -n "não autoritativo|duplicadas consolidadas|não computad|fora do escopo" \
  apps/census/templates/census/bed_status.html
rg -n "nome|prontuario|leito|patient" apps/census/occupancy.py apps/census/views.py
rg -n "MOQA|v4|sistema de origem|ADR-0005" docs/adr/ADR-0006-*.md docs/adr/README.md
```

Interpretar:

- busca de `sistema legado` no template deve ser vazia;
- códigos/stable keys não podem controlar componentes; ocorrências em testes ou
  constantes históricas precisam ser justificadas;
- PHI pode existir somente em DTO efêmero/detalhe autenticado;
- `login_required` e exact-run devem permanecer;
- somente collapse Bootstrap, nenhuma tab;
- ADR deve substituir parcialmente, não editar ADR anterior.

## Gates oficiais

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate make-occupancy-quality-actionable --strict
./scripts/markdown-lint.sh
```

## Critérios de sucesso binários

- [ ] S1/S2 e baseline S3 comprovados.
- [ ] RED funcional de UI/grafo/autorização.
- [ ] Dois resumos separados e uma lista detalhada.
- [ ] Componentes genéricos cobrem 1↔1, 1↔N, N↔1 e unmapped.
- [ ] Nenhuma posição/capacidade duplicada.
- [ ] Alias limpo primário e bruto secundário.
- [ ] “Sistema de origem” substitui “legado” na UI.
- [ ] Tratamento de cada categoria é explícito.
- [ ] Todos autenticados veem alternativas não autoritativas.
- [ ] Nenhum candidato recebe autoridade implícita.
- [ ] Agregado/histórico/log não recebe PHI.
- [ ] Warning v4 é elegível; v3 permanece histórico.
- [ ] Exact-run, pending, fallback e 302 preservados.
- [ ] ADR-0006 e índice válidos.
- [ ] Todos gates e inspeções verdes.
- [ ] Máximo seis arquivos e relatório completo.

## Gates de autoavaliação

1. Como componentes conexos resolvem 3A e Cardio sem hardcode?
2. Onde se prova que cada posição aparece uma vez?
3. Por que linhas brutas de `measured_groups.beds` não foram renderizadas?
4. Qual regra escolhe título e alias da unidade?
5. Como cada tratamento é explicado ao usuário?
6. Como alternativas são mostradas sem vencedor?
7. Onde PHI deixa de existir após renderização?
8. Qual teste usa usuário autenticado não-staff?
9. Como v3 e pending permanecem históricos/exact-run?
10. Houve sétimo arquivo ou antecipação de release?

### Condições automáticas de INCOMPLETO

- S1/S2 não completos ou baseline falho/ausente;
- RED não funcional ou teste crítico ausente;
- qualquer gate/integração/markdown lint falhar;
- final com exit não zero, failure/error ou passed menor;
- duas listas detalhadas permanecerem;
- posição ou capacidade duplicada em 3A/Cardio/CO;
- branch hardcoded por código/stable key para montar unidade;
- nome limpo inferido por regex;
- termo `sistema legado` permanecer no template v4;
- conflito receber primeiro/último candidato vencedor;
- detalhes limitados a staff;
- PHI persistida/logada/registrada em relatório;
- `login_required` ou exact-run relaxado;
- models/migrations/JSON/serviços alterados;
- ADR anterior editada em vez de substituição parcial;
- mais de seis arquivos;
- tasks marcadas sem relatório completo.

## Relatório obrigatório

Criar:

```text
/tmp/sirhosp-slice-MOQA-S3-report.md
```

Sem dados reais. Incluir status, BASE_REF, matriz R1–R10, baseline, RED/GREEN,
arquivos, snippets antes/depois, diagramas sintéticos dos componentes 1↔N/N↔1,
contagem de posições antes/depois sintética, inspeções interpretadas, testes de
permissão/privacidade/exact-run, ADR, todos gates, comparação pytest,
autoavaliação, riscos, rerun e `Handoff para verificador` R1–R10.

Somente após tudo passar, marcar 3.1–3.6, commit/push, responder
`REPORT_PATH=/tmp/sirhosp-slice-MOQA-S3-report.md` e parar.

## Prompt pronto para implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every artifact under
openspec/changes/make-occupancy-quality-actionable, especially
slice-prompts/SLICE-MOQA-S3.md and S1/S2 reports. Assume zero context.

Implement ONLY MOQA-S3. Follow the DeepSeek4-Flash protocol: clean baseline,
real TDD RED, minimal GREEN, controlled clean-code/DRY/YAGNI refactor,
mandatory permission/UI/privacy inspections, all official container gates,
integration, markdown lint and baseline-vs-final evidence. Touch only the six
allowed files. Keep two aggregate summaries and build one generic connected-
component list. Do not touch models, migrations, catalog, JSON, clinical
services, release or activation. Preserve exact-run and historical v1-v3.

If any gate/check/test is missing or failing, final has failure/error, passed
regresses, a position/capacity duplicates, component construction is hardcoded,
a candidate is made authoritative, access is staff-only, PHI escapes
render-memory, terminology is wrong or file limit is exceeded, report
INCOMPLETE; do not mark tasks or commit/push.

Create /tmp/sirhosp-slice-MOQA-S3-report.md with RED/GREEN, before/after
snippets per file, synthetic graph evidence, UI/auth/privacy checks, ADR,
complete gates, rerun commands, self-evaluation and Handoff para verificador.
Mark only 3.1-3.6 after every criterion passes. Commit, push, reply REPORT_PATH
and STOP.
```
