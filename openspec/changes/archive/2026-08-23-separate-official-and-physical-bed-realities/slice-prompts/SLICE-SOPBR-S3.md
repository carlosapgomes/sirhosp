# SOPBR-S3 — Duas realidades visuais em /beds e ADR

## Handoff para implementador com contexto zero

Você está no SIRHOSP após SOPBR-S1 e SOPBR-S2. Este é o terceiro e último slice
de implementação do change
`separate-official-and-physical-bed-realities`.

Leia integralmente, nesta ordem:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. proposal, design, tasks e cinco delta specs deste change;
4. prompts e relatórios S1/S2 para contratos já implementados;
5. este arquivo;
6. `apps/census/occupancy.py`, especialmente helpers de apresentação;
7. `apps/census/views.py`, função `bed_status_view`;
8. `apps/census/templates/census/bed_status.html`;
9. `tests/unit/test_bed_status_view.py`;
10. `docs/adr/ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel.md`;
11. `docs/adr/ADR-0004-correcao-co-e-particionamento-etario-3a.md`;
12. `docs/adr/README.md` e `docs/adr/template.md`.

Pré-condições:

- tarefas S1 e S2 estão completas;
- runtime persiste v3, reconciliação, disponibilidade e parcialidade;
- parser aceita novo catálogo integral v3;
- working tree versionado está limpo;
- nenhum catálogo real foi ativado.

Se alguma condição falhar, pare e reporte bloqueio.

Objetivo: fazer `/beds` comunicar duas realidades simultâneas, inequívocas e
visualmente separadas. A seção oficial usa somente medição persistida exact-run;
a seção física usa a mesma normalização conservadora para mostrar cada posição
uma vez. O slice também registra a decisão em ADR-0005. Não publicar release ou
ativar catálogo.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer item falhar, o slice está **INCOMPLETO**: não marque tarefas, não
faça commit/push e reporte evidência.

1. Antes de editar, registre matriz `Requisito → arquivo(s) → teste/inspeção`.
2. Registre `BASE_REF=$(git rev-parse HEAD)` e `git status --short` limpo.
3. Execute `./scripts/test-in-container.sh unit` como baseline oficial antes de
   editar; registre exit code, passed, zero failed e zero errors.
4. Escreva testes RED antes de helpers, view, template ou ADR.
5. Faça GREEN mínimo sem alterar model, migration, catálogo ou cálculo v3.
6. Refatore somente apresentação, aplicando clean code, DRY, YAGNI,
   acessibilidade e nomes semânticos.
7. Execute inspeções visuais por `rg`, testes e todos os gates.
8. Compare `passed_final >= passed_baseline` com zero failures/errors.
9. Gere relatório completo com snippets e handoff para terceiro LLM.

## Objetivo vertical

Ao abrir `/beds` autenticado com último censo e medição exact-run, o usuário vê:

1. `Capacidade oficial e ocupação`, com catálogo, capacidade, ocupações
   consideradas, disponibilidade setorial, excedente e taxa;
2. uma ponte agregada v3 que explica o numerador;
3. `Posições registradas no sistema legado`, com estados físicos, duplicatas,
   conflitos, linhas sem identidade e detalhe por setor-fonte.

Nenhum card, tabela ou rótulo deve permitir confundir disponibilidade oficial
com status vago do legado. Duplicata aparece uma vez; conflito aparece uma vez
sem paciente escolhido.

## Requisitos funcionais do slice

### R1 — Seções simultâneas e visualmente distintas

Renderizar duas `<section>` ou blocos semânticos sempre visíveis, sem tabs:

- título exato `Capacidade oficial e ocupação`;
- título exato `Posições registradas no sistema legado`;
- cores, subtítulos, bordas ou ícones distintos;
- fonte e timestamp próprios;
- ordem oficial primeiro, físico depois;
- texto curto explicando que são bases diferentes.

Bootstrap e CSS existente bastam. Não adicionar framework, JavaScript ou
stylesheet global salvo bloqueio prévio.

### R2 — Cards oficiais com rótulos próprios

Para v3, mostrar somente valores persistidos:

- `Capacidade oficial`;
- `Ocupações consideradas na taxa`;
- `Disponibilidade na capacidade oficial`;
- `Excedente à capacidade`;
- `Taxa oficial de ocupação`;
- cobertura e vigência.

Disponibilidade deve ter texto/tooltip dizendo que é saldo calculado por setor,
não lista nominal de leitos vagos. Se a medição for parcial, cards e taxa devem
indicar `parcial` e inelegibilidade diária.

É proibido recalcular capacidade, taxa, disponibilidade, excedente ou ponte em
`views.py` ou template.

### R3 — Tabela oficial sem mistura física

Tabela/lista oficial agrupa por stable key persistida e mostra:

- nome oficial;
- capacidade;
- ocupação considerada;
- disponibilidade;
- taxa;
- excedente;
- motivo de não cálculo.

Não mostrar `N total` de linhas brutas como capacidade. Não misturar badges
`vagos`, `reservados` ou `manutenção` nessa linha oficial. Grupos unrated ou
unmapped aparecem como exclusão, sem taxa ou disponibilidade.

3A Adulto/Infantil permanecem oficiais. Qualquer agrupamento auxiliar v2 deve
ser visualmente separado e não contado como setor oficial.

### R4 — Ponte de reconciliação v3

Consumir somente JSON agregado persistido e mostrar categorias positivas:

- linhas ocupadas brutas;
- duplicatas ocupadas excluídas;
- conflito/identidade ausente ocupados excluídos;
- idade desconhecida excluída;
- posições ocupadas em grupos fora da taxa;
- ocupações consideradas.

A equação exibida deve fechar. Não reconstruir ponte a partir do detalhe nem
expor nome, prontuário, leito ou idade. Para v1/v2, não fabricar ponte v3;
rotular semântica histórica.

### R5 — Visão física normalizada

Criar helper coeso em `occupancy.py` que reutilize o normalizador de S1 em vez
de duplicar regras na view.

A seção física mostra:

- posições físicas identificadas;
- posições ocupadas;
- posições com status vago no legado;
- reservadas;
- manutenção;
- isolamento;
- conflitos;
- linhas duplicadas extras;
- linhas sem identificação de posição.

Regras:

- contagens de status inequívoco + conflitos fecham total de posições
  identificadas;
- duplicatas extras não aumentam posições;
- linhas sem leito não são chamadas de posição;
- cada posição inequívoca aparece uma vez no detalhe;
- conflito aparece uma vez como `Conflito no legado`, sem escolher paciente;
- mesmo prontuário em leitos diferentes permanece em duas posições;
- detalhe nominal de posição inequívoca mantém links autorizados existentes.

### R6 — Setores físicos refletem a origem

Na tabela física:

- agrupar por setor/código de origem do censo;
- a 3A fonte aparece fisicamente uma vez, não duplicada como Adulto e Infantil;
- CO e demais setores sem capacidade mostram todos os estados físicos;
- unmapped permanece visível;
- nomes divergentes continuam auditáveis sem remapeamento automático.

### R7 — Exact-run, pendência e compatibilidade histórica

- medição oficial deve continuar pertencendo ao run exato do último censo;
- medição antiga nunca pode ser usada como atual;
- sem medição exata, seção oficial fica `Pendente` e física continua visível;
- v1 e v2 preservam valores persistidos e recebem indicação histórica;
- v1/v2 não recebem disponibilidade ou deduplicação oficial v3 inventada;
- fallback cru deve usar rótulos físicos corrigidos, nunca `Total de leitos`.

### R8 — Autenticação, privacidade e acessibilidade

- preservar `login_required` e redirect anônimo;
- preservar links existentes somente em detalhe autenticado inequívoco;
- alertas agregados sem identificadores;
- conflito não exibe paciente escolhido;
- headings em ordem, `role="alert"` quando aplicável e texto além de cor;
- collapse deve manter `aria-expanded` e alvo único.

### R9 — ADR-0005 substitutiva parcial

Criar ADR conforme template e atualizar índice. Registrar:

- duas realidades e seus nomes;
- identidade origem+leito;
- duplicata exata versus prontuário em leitos distintos;
- conflito/identidade ausente como parcialidade;
- disponibilidade por saldo positivo setorial;
- preservação bruta, privacidade e ativação futura v3;
- consequências e correção forward.

ADR-0005 substitui somente decisões afetadas da ADR-0004 sobre não
deduplicação por prontuário, esclarecendo que prontuário isolado continua não
sendo deduplicado. Não editar ADR-0003 ou ADR-0004.

### R10 — Sem alteração operacional

Este slice não publica release, não faz deploy, não ativa catálogo, não consulta
produção e não registra dados reais em screenshots ou relatório.

## Arquivos esperados e limite

Limite rígido: **até 6 arquivos alterados/criados**.

Arquivos esperados:

1. `apps/census/occupancy.py`;
2. `apps/census/views.py`;
3. `apps/census/templates/census/bed_status.html`;
4. `tests/unit/test_bed_status_view.py`;
5. `docs/adr/ADR-0005-*.md`;
6. `docs/adr/README.md`.

Se precisar de model, migration, catálogo, URL, CSS global, outro teste ou
sétimo arquivo, pare e reporte **INCOMPLETO/BLOQUEADO**. Não corrija slices
anteriores silenciosamente.

## Fora de escopo e arquivos proibidos

Não alterar:

- `apps/census/models.py` ou migrations;
- `apps/census/capacity_catalog.py` ou management command;
- JSONs de catálogo;
- URLs, permissões, pacientes ou ingestão;
- ADR-0003, ADR-0004 ou release docs;
- JavaScript/CSS global;
- deploy e produção.

Não adicionar dependência nem snapshot com dado real.

## TDD obrigatório

### RED

Antes da implementação, criar testes sintéticos para, no mínimo:

1. ambos os headings exatos aparecem simultaneamente;
2. cards oficiais usam os cinco rótulos corretos;
3. texto `Total de leitos` não aparece na nova página com censo;
4. status vago do legado não é chamado disponibilidade oficial;
5. disponibilidade e ponte vêm dos valores persistidos v3;
6. ponte fecha e não contém marcadores sintéticos de PHI;
7. duplicata exata renderiza uma posição e diagnóstico agregado;
8. conflito renderiza uma posição, sem nome/prontuário escolhido;
9. status físicos fecham total identificado;
10. 3A física aparece uma vez e Adulto/Infantil aparecem na visão oficial;
11. CO sem taxa aparece fisicamente com estados;
12. v1/v2 permanecem históricos sem disponibilidade v3 fabricada;
13. medição antiga não é reutilizada;
14. sem medição exata mantém oficial pendente e físico visível;
15. acesso anônimo continua redirecionado.

Execute:

```bash
./scripts/test-in-container.sh unit
```

Registre pelo menos uma falha funcional nova de conteúdo/estrutura esperada.
Falha por template syntax, import ou fixture inválida não é RED válido.

### GREEN

Implemente helpers, contexto e template mínimos. Execute:

```bash
./scripts/test-in-container.sh unit
```

Todos os testes devem passar.

### REFACTOR

Depois do GREEN:

- mantenha normalização em um helper compartilhado, não na view/template;
- use dataclasses/objetos de apresentação coesos já adotados no módulo;
- mantenha view fina e template sem aritmética oficial;
- remova badges/rótulos ambíguos substituídos;
- evite macro, inclusion tag, JS ou CSS novo sem necessidade;
- preserve Bootstrap, acessibilidade e links atuais;
- não faça redesign de outras páginas.

## Checks de inspeção obrigatórios

Execute e interprete:

```bash
rg -n "Capacidade oficial e ocupação|Posições registradas no sistema legado|Disponibilidade na capacidade oficial|Ocupações consideradas na taxa|Taxa oficial de ocupação" \
  apps/census/templates/census/bed_status.html
rg -n "Total de leitos|Lotação registrada no sistema legado|>Ocupados<|>Vagas<" \
  apps/census/templates/census/bed_status.html
rg -n "measurement\.(occupied_for_rate|occupancy_percentage|available_capacity|exceeded_by)|reconciliation" \
  apps/census/templates/census/bed_status.html apps/census/views.py
rg -n "login_required|resolve_exact_measurement|build_.*physical|build_.*official" \
  apps/census/views.py apps/census/occupancy.py
rg -n "prontuario|nome|leito|exact_age|patient_name|record_number" \
  apps/census/templates/census/bed_status.html apps/census/occupancy.py
rg -n "ADR-0005|ADR-0003|ADR-0004|Supersed" \
  docs/adr/ADR-0005-*.md docs/adr/README.md
git diff --exit-code -- docs/adr/ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel.md \
  docs/adr/ADR-0004-correcao-co-e-particionamento-etario-3a.md
rg -n "Celery|Redis|apply_async|\.delay\(" \
  apps/census/views.py apps/census/occupancy.py
```

Interpretação obrigatória:

- os cinco rótulos positivos devem existir;
- os rótulos ambíguos não devem aparecer no novo fluxo; ocorrência em fallback
  histórico precisa ser eliminada ou justificada por teste, nunca ignorada;
- campos oficiais podem ser lidos, mas não deve haver divisão, soma ou
  `max(...)` em view/template para recalculá-los;
- PHI pode existir apenas no detalhe autenticado preexistente e em memória;
  nunca em alertas/reconciliação;
- ADR-0003/0004 devem retornar diff zero;
- confirme limite de seis arquivos com `git diff --name-only "$BASE_REF"`.

## Gates oficiais de conclusão

Execute todos:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate separate-official-and-physical-bed-realities --strict
./scripts/markdown-lint.sh
```

Markdown lint global é obrigatório e não pode ser inibido. Registre exit code e
resumo. Uma confirmação visual manual pode complementar, nunca substituir,
testes e inspeções; não capture dados reais.

## Critérios de sucesso binários

- [ ] S1/S2 completos e baseline oficial verde antes de editar.
- [ ] RED funcional real e GREEN comprovados.
- [ ] Dois headings exatos estão simultaneamente visíveis.
- [ ] Cards oficiais e físicos usam vocabulários não intercambiáveis.
- [ ] Tabela oficial não mistura status físicos.
- [ ] Disponibilidade tem explicação setorial e não nominal.
- [ ] Ponte v3 usa somente persistência, fecha e é privada.
- [ ] Duplicata aparece uma vez; conflito aparece uma vez sem paciente escolhido.
- [ ] Status físicos fecham total e unidentified não é chamado posição.
- [ ] 3A oficial/física e CO seguem os contratos.
- [ ] Exact-run, pendência, v1/v2 e autenticação têm regressões.
- [ ] View/template não recalculam indicador oficial.
- [ ] ADR-0005 e índice estão válidos; ADR-0003/0004 sem diff.
- [ ] Todos os gates e inspeções passaram.
- [ ] Limite de seis arquivos respeitado.
- [ ] Relatório temporário completo criado.

## Gates de autoavaliação

Responda no relatório:

1. Quais elementos visuais impedem confundir as duas realidades?
2. Onde cada seção declara sua fonte e timestamp?
3. Como se prova que disponibilidade não é status vago?
4. A view ou template executa alguma aritmética oficial?
5. Como a ponte fecha em fixture sintética?
6. Como duplicata e conflito são apresentados sem repetição?
7. Por que a 3A física aparece uma vez, mas a oficial duas?
8. O que o usuário vê sem medição exata?
9. Qual teste preserva login e qual preserva v1/v2?
10. ADR-0005 substitui exatamente quais decisões e quais preserva?

### Condições automáticas de INCOMPLETO

Marque incompleto se:

- S1/S2 ou baseline estiverem ausentes/falhos;
- RED real ou teste de regressão crítico faltar;
- qualquer gate, integração, lint, typecheck, OpenSpec ou Markdown lint falhar;
- pytest final tiver failure/error ou menos passed que baseline;
- uma realidade estiver escondida em tab por padrão;
- `Total de leitos`, `Ocupados` ou `Vagas` continuar ambíguo;
- disponibilidade for confundida ou calculada globalmente na UI;
- view/template recalcular taxa, capacidade, disponibilidade, excedente ou
  ponte;
- duplicata aparecer repetida ou conflito escolher paciente/status;
- alerta/reconciliação expuser PHI;
- medição antiga for usada como atual;
- login/permissão for relaxado;
- model, migration, catálogo, URL, ADR-0003/0004 ou sétimo arquivo for alterado;
- relatório ou snippets por arquivo faltarem;
- `tasks.md` for marcado antes de tudo passar.

## Relatório obrigatório

Crie exatamente:

```text
/tmp/sirhosp-slice-SOPBR-S3-report.md
```

Inclua:

1. status COMPLETE/INCOMPLETE;
2. `BASE_REF`, estado inicial e confirmação S1/S2;
3. matriz R1..R10;
4. baseline, RED e GREEN com comandos/exit codes/resumos;
5. lista de arquivos e justificativa;
6. snippets antes/depois por arquivo alterado;
7. mapa textual das duas seções e seus rótulos;
8. fixture/equação sintética da reconciliação;
9. evidência de duplicata, conflito, 3A, CO, pendência, v1/v2 e autenticação;
10. todos os `rg`, diff das ADRs preservadas e interpretação;
11. gates oficiais, Markdown e comparação baseline/final;
12. respostas de autoavaliação;
13. riscos/limitações;
14. comandos exatos de rerun;
15. `Handoff para verificador` com checklist R1..R10 e inspeção visual segura.

Não inclua screenshot, nome, prontuário, leito ou qualquer dado real. Somente
após tudo passar, marque tarefas 3.1 a 3.6, commit/push, responda
`REPORT_PATH=/tmp/sirhosp-slice-SOPBR-S3-report.md` e pare.

## Prompt pronto para o implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and all artifacts under
openspec/changes/separate-official-and-physical-bed-realities. Read
slice-prompts/SLICE-SOPBR-S3.md completely and assume zero prior context.
Confirm SOPBR-S1/S2 are complete and the tracked tree is clean.

Implement ONLY SOPBR-S3. Follow the DeepSeek4-Flash protocol: official
container unit baseline before editing, real RED, minimal GREEN, controlled
REFACTOR with clean code/DRY/YAGNI, mandatory rg inspections, all official
gates, integration, OpenSpec strict, global Markdown lint and baseline-final
comparison. Touch only occupancy.py, views.py, bed_status.html,
test_bed_status_view.py, one new ADR-0005 and the ADR index: maximum six files.

Keep both realities visible and visually distinct. Never recalculate official
values in view/template. Preserve exact-run, v1/v2, fallback, authentication,
privacy and authorized details. Do not touch models, migrations, catalog, URLs,
ADR-0003/0004, release or production.

If any test/check/gate fails, pytest has failure/error, passed_final < baseline,
labels remain ambiguous, PHI leaks, file limit is exceeded or prior artifacts
need repair, report INCOMPLETE, do not mark tasks and do not commit/push.

Create /tmp/sirhosp-slice-SOPBR-S3-report.md with complete RED/GREEN,
before/after snippets for every file, visual map, reconciliation evidence,
checks, gates, rerun commands and Handoff para verificador. Mark 3.1-3.6 only
after proof, commit, push, reply REPORT_PATH and STOP.
```
