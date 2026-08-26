# IBPU-S1 — Resumo da situação real e ponte compacta

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos do change `improve-beds-v5-page-ux` (proposal, design,
   tasks, delta spec) e este arquivo;
3. `apps/census/occupancy.py` (funções `build_units_presentation`,
   `_PhysicalPresentation`, `_V5Coverage`, branch `occupancy-v5`) e
   `apps/census/views.py`;
4. `apps/census/templates/census/bed_status.html` (branch v5 inteira: resumo
   oficial, seção `Como os pacientes foram contados`, lista de setores);
5. `tests/unit/test_bed_status_view.py` (classe `TestBedStatusV5PatientPresentation`
   e helpers existentes de renderização);
6. `docs/adr/ADR-0007-*.md`.

Entrada esperada: produção roda v5 desde 2026-08-26; a página v5 está
semanticamente correta (ponte agregada, pacientes por prontuário, estados
operacionais factuais). Problemas deste slice: não existe resumo agregado com
todos os pacientes identificados (dentro e fora da taxa) e a ponte
`Como os pacientes foram contados` ocupa o topo da página, entre o resumo
oficial e a lista de setores.

Este slice altera somente a apresentação da branch v5. Não altera cálculo
persistido, reconciliação, catálogo, modelos, migrations, branches v1–v4 nem
autenticação.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer falha implica `INCOMPLETE`, sem tasks/commit/push.

1. Registre `BASE_REF=$(git rev-parse HEAD)`, árvore limpa e matriz
   requisito→arquivo→teste.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`, com exit code
   e passed/failed/errors. Falha bloqueia.
3. Testes RED primeiro; ao menos um teste novo deve falhar pelo motivo
   esperado antes da implementação.
4. GREEN mínimo em até 3 arquivos rastreados; não refatore v1–v4.
5. REFACTOR somente na apresentação v5, com clean code, funções coesas, DRY,
   YAGNI e nenhuma aritmética de agregados no template.
6. Rode as inspeções `rg` obrigatórias, depois todos os gates oficiais e
   Markdown lint.
7. Final exit 0, zero failures/errors e passed >= baseline.
8. Relatório completo; somente então tasks 1.x, commit/push e STOP.

## Objetivo vertical

Um usuário autenticado abre `/beds` em um censo exato v5 e vê, na ordem: o
resumo oficial, a nova seção `Situação real do hospital` com o total de
pacientes identificados (na taxa + fora da taxa) e os estados operacionais,
a lista de setores e, ao fim, a ponte `Como os pacientes foram contados`
recolhida por padrão. Anônimo continua 302; nada identificável é persistido
ou agregado.

## Requisitos funcionais

### R1 — Resumo da situação real (posição e conteúdo)

Somente na branch v5, renderizar nova seção com
`id="real-situation-heading"` posicionada no HTML entre os ids
`official-heading` e `units-heading`, derivada exclusivamente de
`measurement.physical_reconciliation_json`:

- total de pacientes identificados = `standard_identified_patients +
  unrated_identified_patients + linked_pending_identified_patients +
  unmapped_identified_patients`, com subtítulo `N na taxa oficial ·
  N fora da taxa` (fora = total − standard);
- contagens dos estados operacionais a partir de
  `operational_rows_by_status` para as chaves canônicas `empty`
  (`Vagos`), `reserved` (`Reservados`), `maintenance` (`Em manutenção`) e
  `isolation` (`Isolamento`), cada uma com sua contagem, inclusive zero;
- linha `identificação incompleta (não contada): N` somente quando
  `incomplete_identity_rows > 0`;
- se `physical_reconciliation_json` for ausente/nulo, a seção não é
  renderizada.

Toda soma/agregação acontece em Python (`occupancy.py`), nunca no template.

### R2 — Dataclass `_V5RealTotals`

Criar dataclass efêmera com campos para total identificado, na taxa, fora da
taxa, contagens por estado operacional e linhas de identificação incompleta.
Preenchê-la na branch v5 de `build_units_presentation` a partir do JSON
persistido e expô-la como atributo `v5_real` da estrutura `physical`
(`_PhysicalPresentation`), com `None` como padrão. Nenhum campo nominal
(nome, prontuário, leito) pode existir nessa estrutura.

### R3 — Ponte ao fim e recolhida

Mover a seção `Como os pacientes foram contados` (branch v5) para depois da
seção da lista de setores (`id="units-heading"`), envolvida em collapsible no
mesmo padrão dos cards de setor: container com classe `collapse` sem classe
`show`, gatilho clicável com `data-bs-toggle="collapse"` e
`aria-expanded="false"`, ícone de chevron. O conteúdo interno (todos os `<li>`
e o parágrafo de fechamento da ponte) permanece idêntico, apenas a posição e o
envoltório mudam. As pontes v3/v4 e todas as branches históricas permanecem
exatamente onde estão.

### R4 — Privacidade e autorização preservadas

A nova seção contém somente contagens agregadas. Anônimo permanece 302;
autenticado comum continua autorizado; nenhum nome, prontuário, leito ou
assinatura de linha entra na seção, nos testes, logs ou relatório.

### R5 — Regressão histórica

Branches v1–v4 continuam renderizando exatamente como antes: sem seção
`Situação real do hospital`, com suas pontes nas posições atuais. Testes de
regressão existentes permanecem verdes sem edição de expectativas.

## Arquivos esperados e limite

Máximo **3 arquivos rastreados**:

1. `apps/census/occupancy.py` — `_V5RealTotals` + preenchimento na branch v5;
2. `apps/census/templates/census/bed_status.html` — nova seção + movimentação
   da ponte v5;
3. `tests/unit/test_bed_status_view.py` — testes novos.

Se precisar de quarto arquivo ou alterar model/migration/view/catalog, pare e
reporte bloqueio. `apps/census/views.py` não deve mudar.

## TDD obrigatório

### RED

Testes sintéticos mínimos (usar fixtures/helpers existentes de medição v5):

1. HTML v5 contém `real-situation-heading` e sua posição está entre
   `official-heading` e `units-heading` (comparar índices no HTML renderizado);
2. total identificado = soma das quatro políticas (ex.: 607 + 35 + 0 + 0 =
   642 sintético) e subtítulo com `na taxa oficial` e `fora da taxa`;
3. estados `Vagos`, `Reservados`, `Em manutenção` e `Isolamento` com as
   contagens do JSON sintético, inclusive um estado com contagem zero;
4. `identificação incompleta` aparece quando > 0 e não aparece quando 0;
5. reconciliação ausente oculta a seção;
6. ponte v5: `patient-bridge-heading` aparece depois de `units-heading`;
   container da ponte tem classe `collapse` sem `show`; gatilho com
   `aria-expanded="false"`;
7. conteúdo da ponte inalterado (mesmos `<li>` de duplicatas/standard/unrated);
8. anônimo 302; nenhum nome/prontuário na nova seção;
9. regressão: medição v4 renderiza sem `real-situation-heading` e com sua
   ponte na posição atual (antes da lista).

RED deve falhar por ausência da seção/posição/estado recolhido.

### GREEN

Implementar `_V5RealTotals` + `physical.v5_real`, renderizar a seção no
template v5 e mover a ponte com o envoltório `collapse`. Template apenas lê
estruturas prontas.

### REFACTOR

Função coesa para derivar `_V5RealTotals` do JSON (tolerante a chaves
ausentes), sem duplicação e sem lógica no template.

## Checks de inspeção obrigatórios

```bash
rg -n "real-situation-heading|Situação real do hospital|na taxa oficial|fora da taxa" \
  apps/census/templates/census/bed_status.html tests/unit/test_bed_status_view.py
rg -n "patient-bridge-heading|Como os pacientes foram contados" \
  apps/census/templates/census/bed_status.html
rg -n "v5_real|_V5RealTotals" apps/census/occupancy.py
rg -n "aria-expanded=\"false\"|collapse" \
  apps/census/templates/census/bed_status.html | head -30
```

Interpretação obrigatória: a seção nova e o envoltório da ponte devem existir
somente na branch v5; a ponte v4/v3 não pode ter ganho `collapse`; as somas
devem estar em `occupancy.py`, não no template.

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

- [ ] R1–R5 testados.
- [ ] Seção nova entre resumo oficial e lista, somente v5, só agregados.
- [ ] Soma fecha e estados canônicos com zero visível quando aplicável.
- [ ] Incompleta omitida quando zero.
- [ ] Ponte após a lista, recolhida por padrão, conteúdo idêntico.
- [ ] Pontes v3/v4 e branches v1–v4 intocadas.
- [ ] Anônimo 302; zero PHI.
- [ ] Até 3 arquivos e todos os gates verdes.

### Condições automáticas de INCOMPLETO

- baseline/RED/gates ausentes ou falhos;
- template realiza soma ou derivação de agregados;
- nova seção aparece em v1–v4;
- ponte v5 permanece antes da lista ou aberta por padrão;
- ponte v3/v4 movida ou modificada;
- contagem de estado ou soma divergente do JSON sintético;
- PHI em persistência, log, fixture real ou relatório;
- autenticação relaxada;
- quarto arquivo sem bloqueio prévio;
- relatório ausente ou passed final menor que baseline.

## Gates de autoavaliação

1. Qual teste prova a ordem `official < real < units < bridge` no HTML?
2. Qual teste prova que o total fecha contra as quatro políticas?
3. Como estados com contagem zero são renderizados e testados?
4. Onde a soma acontece e por que não no template?
5. Qual teste prova a ponte recolhida (`collapse` sem `show`,
   `aria-expanded="false"`)?
6. Qual teste de regressão prova v1–v4 sem a seção nova?
7. Que evidência prova ausência de PHI na nova seção?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-IBPU-S1-report.md` com status, BASE_REF, matriz
requisito→arquivo→teste, evidência RED/GREEN com comandos e resumos, snippets
antes/depois por arquivo, inspeções `rg` e interpretação, baseline versus
final (exit, passed, failed, errors), gates, Markdown lint, arquivos alterados
e justificativas, privacidade, riscos e `Handoff para verificador` R1–R5 com
comandos exatos de rerun. Nunca incluir dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete improve-beds-v5-page-ux
change and SLICE-IBPU-S1.md. Implement ONLY S1 under the mandatory
DeepSeek4-Flash protocol: BASE_REF and official container baseline before
edits, real RED, minimal GREEN in at most occupancy.py, bed_status.html and
its unit test, scoped clean code/DRY/YAGNI refactor, rg inspections, all
official gates, Markdown lint and baseline-vs-final evidence. Add the v5-only
"Situação real do hospital" summary between the official summary and the unit
list, derived only from persisted physical_reconciliation_json via a new
_V5RealTotals exposed as physical.v5_real (no template arithmetic), and move
the v5 patient bridge section after the unit list inside a collapsed-by-default
container with aria-expanded="false", keeping its aggregate content and the
v1-v4 branches untouched. Preserve login, exact-run and privacy; no PHI. On
any failure report INCOMPLETE without tasks/commit. Otherwise create
/tmp/sirhosp-slice-IBPU-S1-report.md with RED/GREEN evidence, snippets, gates,
rerun commands and verifier handoff; mark only 1.x in tasks.md, commit, push,
reply REPORT_PATH=..., then STOP.
```
