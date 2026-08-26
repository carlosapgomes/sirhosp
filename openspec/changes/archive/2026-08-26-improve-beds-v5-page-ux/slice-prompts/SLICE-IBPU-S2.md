# IBPU-S2 — Métricas oficiais nos cabeçalhos dos cards

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md`;
2. todos os artefatos do change `improve-beds-v5-page-ux`, o relatório
   `/tmp/sirhosp-slice-IBPU-S1-report.md` e o diff do S1;
3. `apps/census/occupancy.py` — seção CIPOO-S3 de apresentação v5:
   `_V5UnitRow`, `_V5PatientItem`, `_V5_COUNTED_LABELS`,
   `_v5_counted_policy`, `_v5_patient_item`, `_v5_units`,
   `_v5_unmapped_units`, `_unit_official_row`, `_component_title`;
4. `apps/census/templates/census/bed_status.html` — branch v5 inteira
   (cabeçalho do card, `official_rows`, lista de pacientes);
5. `tests/unit/test_bed_status_view.py` — classe
   `TestBedStatusV5PatientPresentation` e helpers;
6. `docs/adr/ADR-0007-*.md` (proibição de total combinado 3A).

Entrada esperada: com o S1 completo, a branch v5 tem a seção
`Situação real do hospital` e a ponte recolhida ao fim. O cabeçalho de cada
card v5 ainda mostra apenas `N códigos de origem` e `N pacientes`
(este último omitido quando zero); capacidade/taxa/saldo/excedente estão
somente no corpo; cada paciente carrega badge redundante
`contado na taxa oficial`/`fora da taxa oficial`.

Este slice altera somente apresentação v5 (cabeçalho dos cards e lista de
pacientes). Não altera cálculo persistido, catálogo, modelos, migrations,
branches v1–v4 nem autenticação.

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
   YAGNI e nenhuma formatação/cálculo no template além dos filtros já usados
   (`floatformat`, `pluralize`).
6. Rode as inspeções `rg` obrigatórias, depois todos os gates oficiais e
   Markdown lint.
7. Final exit 0, zero failures/errors e passed >= baseline.
8. Relatório completo; somente então tasks 2.x, commit/push e STOP.

## Objetivo vertical

Um usuário autenticado abre `/beds` v5 e lê cada card colapsado sem expandir:
`[N pacientes] [Cap. X] [Y%] [Saldo Z]` ou `[Acima da capacidade · excedente
W]` por grupo oficial; unidades unrated mostram `[N pacientes] [fora da taxa
oficial]`; a 3A mostra uma linha por partição (`Adulto`/`Infantil`) sem total
combinado; `0 pacientes` é sempre explícito; o cabeçalho não fala de códigos
de origem; a lista de pacientes não repete política de contagem por paciente,
mantendo exceções factuais. O corpo do card permanece como detalhamento.

## Requisitos funcionais

### R1 — `header_metrics` derivado de valores persistidos

Criar `_V5HeaderMetric` (dataclass efêmera) e preencher
`_V5UnitRow.header_metrics` a partir dos `official_rows` já persistidos
(`occupied_count`, `official_capacity`, `occupancy_percentage`,
`official_availability`, `exceeded_by`, `calculation_status`,
`display_name`). Nenhuma nova contagem, consulta ou recálculo; pacientes,
capacidade e percentuais vêm exclusivamente dos valores persistidos.

### R2 — Badges por grupo no cabeçalho

Para cada `header_metric`, renderizar no cabeçalho (sempre visível, sem
expandir):

- grupo standard com capacidade e percentual: `[N pacientes] [Cap. X]
  [Y%]` + `[Saldo Z]` quando dentro da capacidade, ou `[Acima da capacidade ·
  excedente W]` quando acima (o fundo vermelho existente do cabeçalho é
  mantido);
- grupo unrated: `[N pacientes] [fora da taxa oficial]`, sem `Cap.`, sem
  percentual e sem saldo;
- grupo `linked_slots_pending`: `[N pacientes] [cálculo pendente]`;
- grupo standard sem capacidade cadastrada: `[N pacientes] [Capacidade não
  cadastrada]`.

`N pacientes` usa pluralização (`pluralize`) e a formatação de percentual é a
mesma do corpo (`floatformat:2`).

### R3 — Zero pacientes explícito e unidade sem grupo oficial

- O badge de pacientes do cabeçalho nunca é omitido; unidade sem pacientes
  mostra `0 pacientes`.
- Unidade sem `official_rows` (unmapped) mostra `[N pacientes]` no cabeçalho
  e mantém o badge existente `sem mapeamento no catálogo` junto ao título.

### R4 — 3A por partição, sem total combinado

Quando a unidade tiver mais de um `official_row`, cada `header_metric` recebe
rótulo curto derivado deterministicamente do `display_name` persistido: o
sufixo após o travessão (`Enfermaria 3A – Adulto` → `Adulto`); sem travessão,
o `display_name` completo. Renderizar um conjunto de badges por partição no
formato `[Adulto: 21/32 · 65,63% · saldo 11]` (equivalente em conteúdo aos
badges de R2, com rótulo). Nenhum total combinado dos grupos da unidade é
criado; a proibição `3A total 48` permanece.

### R5 — Remoção do badge de códigos do cabeçalho v5

O badge `N códigos de origem` sai do cabeçalho v5. Aliases e códigos
permanecem visíveis no corpo do card (bloco `unit.sources`) exatamente como
estão. O cabeçalho das branches v1–v4 não muda.

### R6 — Fim dos badges por paciente de política de contagem

Remover dos itens de paciente v5 os badges `contado na taxa oficial` e
`fora da taxa oficial` (e de políticas pendente/unmapped, se renderizados).
A política de contagem fica comunicada pelo cabeçalho (R2) e pelos cards
oficiais do corpo. Permanecem por paciente: `Prontuário informado em mais de
um setor oficial neste censo`, nota `Nome informado de formas diferentes em
N linhas`, `sem leito informado` e os casos de leito compartilhado. Remover
o código morto resultante (`counted_policy`/`counted_label` de
`_V5PatientItem`, `_v5_counted_policy`, `_V5_COUNTED_LABELS`) somente após
`rg` provar ausência de outros usos.

### R7 — Corpo preservado e regressão

O corpo colapsado continua exibindo as mini-tabelas oficiais, aliases,
pacientes com nomes/leitos, estados operacionais e identificação incompleta
exatamente como hoje (exceto os badges removidos por R6). Branches v1–v4
continuam renderizando como antes; testes de regressão existentes seguem
verdes sem afrouxar expectativas.

## Arquivos esperados e limite

Máximo **3 arquivos rastreados**:

1. `apps/census/occupancy.py` — `_V5HeaderMetric` + `header_metrics` +
   remoção do código morto de política por paciente;
2. `apps/census/templates/census/bed_status.html` — cabeçalho v5 + lista de
   pacientes;
3. `tests/unit/test_bed_status_view.py` — testes novos.

Se precisar de quarto arquivo ou alterar model/migration/view/catalog, pare e
reporte bloqueio.

## TDD obrigatório

### RED

Testes sintéticos mínimos (reaproveitar fixtures v5 existentes):

1. setor comum dentro da capacidade: cabeçalho contém `N pacientes`, `Cap.`,
   percentual e `Saldo` (valores do fixture, ex.: 13/15/86,67/saldo 2);
2. setor acima da capacidade: cabeçalho contém `Acima da capacidade`,
   `excedente` e o valor W (ex.: 7 pacientes, Cap. 1, 700%);
3. unrated (CO): cabeçalho contém `fora da taxa oficial` e nenhum `Cap.` nem
   percentual naquele cabeçalho;
4. grupo pendente e grupo sem capacidade cadastrada (quando cobertos por
   fixtures existentes ou criados sinteticamente);
5. `0 pacientes` explícito em unidade vazia;
6. 3A: cabeçalho com `Adulto` e `Infantil`, cada qual com pacientes/capacidade
   /percentual/saldo-excedente próprios, e ausência de total combinado
   (nenhum badge com a soma);
7. cabeçalho v5 sem `código`/`códigos de origem` (o corpo mantém os aliases);
8. paciente v5 sem badge `contado na taxa oficial` nem `fora da taxa oficial`;
   exceções cross-group/nome variante/sem leito permanecem;
9. corpo preserva mini-tabela oficial e aliases;
10. regressão: cabeçalho v4 mantém seu badge atual; medição v4 renderiza
    como antes.

Os testes devem isolar o trecho do cabeçalho do card (por exemplo, substring
entre o título da unidade e o fechamento do `card-header`) para não
confundir badges do corpo com badges do cabeçalho.

RED deve falhar por ausência dos badges no cabeçalho e presença dos badges
removidos.

### GREEN

Implementar `_V5HeaderMetric` + `header_metrics` em `_v5_units` (e
`_v5_unmapped_units` quando aplicável), renderizar os badges no cabeçalho,
remover o badge de códigos e os badges por paciente, remover código morto.

### REFACTOR

Derivação do rótulo curto em função coesa e determinística; sem duplicação de
markup (loops/helpers locais simples); sem filtros custom novos.

## Checks de inspeção obrigatórios

```bash
rg -n "header_metrics|_V5HeaderMetric" apps/census/occupancy.py \
  apps/census/templates/census/bed_status.html
rg -n "código[s]? de origem" apps/census/templates/census/bed_status.html
rg -n "contado na taxa oficial|fora da taxa oficial" \
  apps/census/templates/census/bed_status.html tests/unit/test_bed_status_view.py
rg -n "counted_policy|counted_label|_v5_counted_policy|_V5_COUNTED_LABELS" \
  apps/census/occupancy.py
rg -n "Acima da capacidade|0 pacientes|pluralize|floatformat" \
  apps/census/templates/census/bed_status.html
```

Interpretação obrigatória: `código de origem` pode existir somente no corpo
dos cards ou em branches v1–v4, nunca no cabeçalho v5; `contado na taxa
oficial`/`fora da taxa oficial` podem existir como texto de teste (asserção de
ausência) e no cabeçalho v5 como rótulo de política da unidade
(`fora da taxa oficial` em unrated), nunca como badge por paciente;
`counted_policy`/`counted_label` não podem existir mais em `occupancy.py`.

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

- [ ] R1–R7 testados.
- [ ] Badges por grupo no cabeçalho com valores persistidos.
- [ ] `Acima da capacidade · excedente W` textual no cabeçalho.
- [ ] `0 pacientes` explícito; unmapped com contagem.
- [ ] 3A por partição sem total combinado.
- [ ] Cabeçalho v5 sem contagem de códigos.
- [ ] Pacientes sem badge de política; exceções mantidas.
- [ ] Código morto removido com prova `rg`.
- [ ] Corpo e v1–v4 preservados; anônimo 302; zero PHI.
- [ ] Até 3 arquivos e todos os gates verdes.

### Condições automáticas de INCOMPLETO

- baseline/RED/gates ausentes ou falhos;
- cabeçalho recalcula qualquer valor em vez de ler persistido;
- badge de pacientes omitido com zero pacientes;
- total combinado 3A aparece;
- unrated exibe `Cap.`, percentual ou saldo;
- badge de códigos permanece no cabeçalho v5 (ou é removido em v1–v4);
- badge por paciente de política permanece (exceto como texto de teste de
  ausência);
- exceção factual (cross-group, nome variante, sem leito) é perdida;
- corpo perde mini-tabela oficial ou aliases;
- código morto de política permanece sem justificativa com `rg`;
- regressão v1–v4, autenticação ou privacidade violadas;
- quarto arquivo sem bloqueio prévio;
- relatório ausente ou passed final menor que baseline.

## Gates de autoavaliação

1. Qual teste isola o cabeçalho do corpo do card e como?
2. Qual teste prova saldo versus excedente nos dois regimes?
3. Como o rótulo `Adulto`/`Infantil` é derivado sem novo campo persistido?
4. Qual teste prova ausência de total combinado na 3A?
5. Qual prova `rg` acompanha a remoção do código morto?
6. Qual teste garante que o badge de códigos permanece no cabeçalho v4?
7. Que evidência prova que valores do cabeçalho vêm do persistido e não de
   recálculo?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-IBPU-S2-report.md` com status, BASE_REF, matriz
requisito→arquivo→teste, evidência RED/GREEN com comandos e resumos, snippets
antes/depois por arquivo, inspeções `rg` e interpretação, baseline versus
final (exit, passed, failed, errors), gates, Markdown lint, arquivos alterados
e justificativas, privacidade, riscos e `Handoff para verificador` R1–R7 com
comandos exatos de rerun. Nunca incluir dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete improve-beds-v5-page-ux
change, the S1 report/diff and SLICE-IBPU-S2.md. Implement ONLY S2 under the
mandatory DeepSeek4-Flash protocol: BASE_REF and official container baseline
before edits, real RED, minimal GREEN in at most occupancy.py,
bed_status.html and its unit test, scoped clean code/DRY/YAGNI refactor, rg
inspections, all official gates, Markdown lint and baseline-vs-final
evidence. Derive per-group header metrics (_V5HeaderMetric) strictly from
persisted official_rows and render always-visible header badges: patients,
Cap., percentage, Saldo or "Acima da capacidade · excedente W", "fora da taxa
oficial" for unrated, "cálculo pendente", "Capacidade não cadastrada",
explicit "0 pacientes", and one labeled metric set per 3A partition with no
combined total. Remove the v5 header source-code badge and the per-patient
counting-policy badges keeping factual exceptions, delete the dead code with
rg proof, and preserve bodies, v1-v4 branches, login and privacy. On any
failure report INCOMPLETE without tasks/commit. Otherwise create
/tmp/sirhosp-slice-IBPU-S2-report.md with RED/GREEN evidence, snippets,
gates, rerun commands and verifier handoff; mark only 2.x in tasks.md,
commit, push, reply REPORT_PATH=..., then STOP.
```
