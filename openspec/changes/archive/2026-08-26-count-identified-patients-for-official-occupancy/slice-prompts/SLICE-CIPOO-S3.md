# CIPOO-S3 — `/beds` por pacientes e estados de leitos

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos deste change e relatórios S1/S2;
3. commits/diffs S1/S2;
4. `apps/census/{occupancy.py,views.py,templates/census/bed_status.html}`;
5. `tests/unit/test_bed_status_view.py`;
6. ADR-0005, ADR-0006 e `docs/adr/README.md`;
7. specs históricas e delta `bed-status-capacity-view`.

Entrada esperada: v5 materializa por paciente e o JSON v5 existe, mas `/beds`
ainda usa componentes físicos v4. Este slice muda somente apresentação v5 e
documenta a decisão. Não altera cálculo persistido, catálogo ou migration.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer falha implica `INCOMPLETE`, sem tasks/commit/push.

1. Registre BASE_REF/árvore limpa e matriz requisito→arquivo→teste.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`, com exit e
   passed/failed/errors. Falha bloqueia.
3. Testes RED primeiro e suíte unitária comprovando failures funcionais.
4. GREEN mínimo em até cinco arquivos; não refatore v3/v4.
5. REFACTOR somente componentes v5, com clean code, funções coesas, DRY, YAGNI
   e nenhuma lógica complexa em template/view.
6. Rode inspeções de HTML, autorização, terminologia e privacidade, depois todos
   os gates e Markdown lint.
7. Final exit 0, zero failures/errors e passed >= baseline.
8. Relatório completo; somente então tasks S3, commit/push e STOP.

## Objetivo vertical

Um usuário autenticado abre `/beds` em um censo exato v5 e vê resumo oficial sem
capacidade repetida, pacientes deduplicados com todos os nomes/leitos e estados
operacionais factuais, sem linguagem genérica de conflito. Anônimo continua
302; nada identificável é persistido.

## Requisitos funcionais

### R1 — Resumo oficial sem redundância

Para v5 renderizar somente:

- `Capacidade oficial` uma vez;
- `Pacientes identificados`;
- `Saldo da capacidade oficial`;
- `Excedente`;
- `Taxa de ocupação`;
- cobertura 39/43 e quatro fora da taxa como texto/metadado secundário.

Não renderizar cards `Capacidade conhecida`, `Capacidade calculável` ou
`Disponibilidade na capacidade oficial` em v5. Explicar que saldo não é lista de
leitos vagos. Preservar cards e valores históricos v1–v4 sem recalcular.

### R2 — Unidade/lista v5

Título `Setores, pacientes e estados de leitos`. Derivar unidades genericamente
do grafo catálogo↔origem. Para cada grupo:

- um paciente por record normalizado;
- todos os aliases/códigos de origem envolvidos;
- todos os leitos distintos; vazio vira `sem leito informado`;
- todas as variantes de nome;
- counted/unrated/pending/unmapped de forma explícita;
- nenhuma posição física usada para decidir contagem.

### R3 — Mensagens factuais

- mesmo record/nomes variantes: `Nome informado de formas diferentes em N linhas`;
- record em grupos diferentes: `Prontuário informado em mais de um setor oficial neste censo`;
- records distintos no mesmo leito: `pacientes informados com o mesmo leito`;
- mesma nomenclatura com estados operacionais diferentes:
  `estados informados para o mesmo leito`;
- identificação incompleta: `Identificação incompleta — não contada`.

Não escolher nome, setor, leito ou estado vencedor.

### R4 — Estados operacionais

Vago, reservado, manutenção e isolamento aparecem como linhas/estados do
sistema de origem, inclusive uma única linha isolada. Não entram no numerador,
não reduzem capacidade e, em UI v5, não recebem `conflito`,
`registro divergente` ou `não autoritativo`. Não tentar corrigir/recalcular a
reconciliação persistida v4.

### R5 — Casos estruturais

Cobrir 1:1, Cardio 1 grupo↔2 códigos, 3A 2 grupos↔1 código, CO 1 grupo↔5 códigos,
unrated e unmapped. Não hardcodar códigos `654`, `719`, `2156` ou CO na
montagem; usar membership/selectors e dados persistidos.

### R6 — Ponte agregada

`Como os pacientes foram contados` usa exclusivamente reconciliação persistida
v5, fecha a ponte e mostra duplicados, políticas, identificação incompleta,
cross-group, variantes e fallback etário somente em agregados. Sem PHI.

### R7 — Autorização/exact-run/privacidade

- `login_required` e anônimo 302;
- qualquer autenticado autorizado vê detalhes atuais;
- latest census sem measurement exata fica pendente; nunca usar older fallback;
- nomes/records/leitos somente em memória e HTML autenticado;
- measurement, summary, logs, reports e testes não recebem PHI real;
- links internos existentes continuam seguros.

### R8 — ADR

Criar ADR-0007. Ela substitui ADR-0005/0006 somente para v5 quanto à unidade de
contagem e apresentação; v1–v4 permanecem históricos. Registrar decisões de
identidade, grupo, 3A/RN, estados operacionais, privacidade, saldo e ativação
future-only.

## Arquivos esperados e limite

Máximo **5 arquivos rastreados**:

1. `apps/census/occupancy.py` — componentes de apresentação v5;
2. `apps/census/templates/census/bed_status.html`;
3. `tests/unit/test_bed_status_view.py`;
4. `docs/adr/ADR-0007-*.md`;
5. `docs/adr/README.md`.

`apps/census/views.py` não deve mudar se o contrato atual de
`build_units_presentation` bastar. Se precisar de sexto arquivo ou alterar
model/migration/catalog, pare e reporte bloqueio. Nenhum CSS/JS novo sem
necessidade demonstrada.

## TDD obrigatório

### RED

Testes sintéticos mínimos:

1. v5 renderiza um único 666 e labels novos, sem cards redundantes;
2. paciente sem leito conta/lista;
3. dois pacientes no mesmo leito aparecem e contam;
4. duplicado no grupo lista uma pessoa com todos os leitos;
5. Cardio deduplica entre códigos;
6. nomes variantes todos visíveis + mensagem;
7. cross-group conta/lista nos dois + mensagem;
8. identificação incompleta separada;
9. linha única vago/reservado/manutenção/isolamento não é conflito;
10. estados diferentes mesmo leito aparecem + mensagem;
11. 3A Adulto/Infantil e fallback agregados sem total 48;
12. CO/unrated e unmapped sem taxa;
13. ponte privada;
14. exact-run pending, anônimo 302 e autenticado comum 200;
15. regressão v1–v4.

RED deve falhar por labels/estrutura/componente v5 ausentes.

### GREEN

Criar dataclasses/helpers efêmeros em `occupancy.py`, reutilizando normalização
v5 de S1. Template apenas apresenta estruturas prontas. Branch explícito por
algorithm version é permitido para preservar história; não recalcular official
values na view.

### REFACTOR

Remover duplicação somente na apresentação v5. Evitar consultas N+1, lógica de
negócio no template, filtros custom desnecessários, hardcode de setor e markup
repetido sem componente local simples.

## Checks de inspeção obrigatórios

```bash
rg -n "Capacidade oficial|Pacientes identificados|Saldo da capacidade oficial|Setores, pacientes e estados de leitos|Como os pacientes foram contados" \
  apps/census/templates/census/bed_status.html tests/unit/test_bed_status_view.py
rg -n "Capacidade conhecida|Capacidade calculável|Disponibilidade na capacidade oficial|registro divergente|não autoritativo|[Cc]onflito" \
  apps/census/templates/census/bed_status.html
rg -n "login_required|resolve_exact_measurement|build_units_presentation" \
  apps/census/views.py apps/census/occupancy.py
rg -n "654|719|2156|1110|1112|1114|1116" \
  apps/census/occupancy.py apps/census/templates/census/bed_status.html
rg -n "ADR-0007|ADR-0005|ADR-0006|occupancy-v5" docs/adr
```

Interpretação obrigatória: termos antigos podem existir somente em branches
históricos v1–v4; testes v5 devem provar sua ausência no HTML v5. Códigos não
podem aparecer em novo branch de montagem. Decorator/exact-run devem permanecer.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate count-identified-patients-for-official-occupancy --strict
./scripts/markdown-format.sh
./scripts/markdown-lint.sh
```

Autofix Markdown não autoriza alterar conteúdo sem revisão do diff.

## Critérios binários de sucesso

- [ ] R1–R8 testados.
- [ ] Um card de capacidade e labels novos em v5.
- [ ] Paciente é unidade da listagem/numerador; leito é atributo.
- [ ] Mensagens factuais e todas as evidências visíveis.
- [ ] Estados operacionais não são conflitos.
- [ ] Sem hardcode setorial na montagem.
- [ ] Exact-run/autenticação/privacidade preservados.
- [ ] V1–v4 passam regressão.
- [ ] ADR/index lintados.
- [ ] Até cinco arquivos e todos os gates verdes.

### Condições automáticas de INCOMPLETO

- baseline/RED/gates ausentes ou falhos;
- template calcula identidade, dedupe ou taxa;
- view recalcula measurement ou usa older fallback;
- um paciente duplicado aparece como duas pessoas no grupo;
- variante/leito é descartado ou escolhido como verdade;
- operacional isolado aparece como conflito v5;
- termos proibidos aparecem no HTML v5;
- PHI entra em persistência/log/report/fixture real;
- autenticação relaxada;
- hardcode por setor/código;
- regressão histórica;
- sexto arquivo sem bloqueio prévio;
- relatório ausente ou final passed menor.

## Gates de autoavaliação

1. Qual teste conta ocorrências de 666 e prova ausência dos cards redundantes?
2. Qual teste prova paciente sem leito e dois pacientes no mesmo leito?
3. Como a estrutura representa nomes/leitos múltiplos sem vencedor?
4. Como Cardio/3A/CO são derivados sem hardcode?
5. Qual teste prova linha operacional única sem conflito?
6. Onde PHI existe e como foi provado que não persiste?
7. Qual teste prova exact-run e autorização?
8. Como ADR-0007 limita sua substituição a v5?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CIPOO-S3-report.md` com status, BASE_REF, matriz,
RED/GREEN, screenshots somente sintéticos se usados, snippets antes/depois,
inspeções e interpretação, baseline/final, gates, Markdown lint, arquivos e
justificativas, privacidade, riscos e `Handoff para verificador` R1–R8 com
comandos exatos de rerun. Nunca incluir dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete
count-identified-patients-for-official-occupancy change, S1/S2 reports and
diffs, current /beds implementation, ADR-0005/0006 and SLICE-CIPOO-S3.md.
Implement ONLY S3 using the mandatory DeepSeek4-Flash protocol: official
container baseline before edits, real RED, minimal GREEN, scoped clean
code/DRY/YAGNI refactor, rg inspections, all official gates, Markdown lint and
baseline-vs-final evidence. Touch at most occupancy.py presentation,
bed_status.html, its unit test, ADR-0007 and ADR index. Do not change models,
migrations, catalog, persisted calculations, release or production. Build v5
UI around deduplicated patients with all name/bed evidence and separate factual
operational states; preserve v1-v4, exact-run, login and privacy. On any failure
report INCOMPLETE without tasks/commit. Otherwise create
/tmp/sirhosp-slice-CIPOO-S3-report.md with RED/GREEN, snippets, gates, rerun and
verifier handoff; mark only S3, commit, push, reply REPORT_PATH=..., then STOP.
```
