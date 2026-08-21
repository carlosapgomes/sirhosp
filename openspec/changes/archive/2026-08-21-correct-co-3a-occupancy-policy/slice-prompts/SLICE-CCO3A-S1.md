# SLICE-CCO3A-S1 — Faixa etária mínima no snapshot

## Handoff para implementador LLM com contexto zero

Você está no repositório SIRHOSP. Implemente somente o primeiro slice do change
`correct-co-3a-occupancy-policy`. Não use a conversa anterior como fonte.

Leia integralmente, nesta ordem:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. `openspec/changes/correct-co-3a-occupancy-policy/proposal.md`;
4. `openspec/changes/correct-co-3a-occupancy-policy/design.md`;
5. `openspec/changes/correct-co-3a-occupancy-policy/tasks.md`;
6. `openspec/changes/correct-co-3a-occupancy-policy/specs/census-snapshot-processing/spec.md`;
7. este arquivo;
8. `automation/source_system/current_inpatients/extract_census.py` nas funções de
   parse e escrita do CSV;
9. `apps/census/models.py`, `apps/census/services.py` e
   `apps/census/management/commands/extract_census.py`;
10. testes existentes de parsing, modelos e comando de extração.

Estado esperado antes do slice:

- o XLSX já possui `Idade` e o extrator já grava `idade` no CSV temporário;
- `parse_census_csv` descarta `idade`;
- `CensusSnapshot` não possui faixa etária;
- o algoritmo de ocupação é v1 e não deve ser alterado neste slice;
- a última migration de `census` deve ser `0017`; confirme, não presuma;
- o working tree deve estar limpo e o bloco 1 de `tasks.md` deve estar
  incompleto.

Se o estado real divergir, se houver edição concorrente ou se S2–S4 já estiver
parcialmente implementado, pare e reporte bloqueio. Não tente reconciliar
silenciosamente.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por modelo rápido, com risco de concluir cedo.
Siga literalmente. **Se qualquer item falhar, o slice está INCOMPLETO**: não
marque `tasks.md`, não faça commit/push e responda com bloqueio e evidência.

1. Registre `BASE_REF=$(git rev-parse HEAD)` e `git status --short` antes de
   editar. O estado deve estar limpo.
2. Escreva primeiro no relatório uma matriz `Requisito → arquivo(s) → teste(s)`.
3. Rode o baseline oficial antes de editar:

   ```bash
   ./scripts/test-in-container.sh unit
   ```

   Registre exit code e resumo completo. Qualquer failure/error bloqueia o
   slice.
4. Faça RED real: escreva testes primeiro e rode novamente o comando oficial
   `unit`. Pelo menos um teste novo deve falhar pelo motivo esperado, não por
   sintaxe, fixture ou infraestrutura.
5. Faça GREEN mínimo, sem antecipar seletor de catálogo, occupancy-v2, UI ou
   ADR. Rode `unit` e comprove zero failures/errors.
6. Faça REFACTOR somente dentro do escopo, aplicando clean code, DRY, YAGNI,
   nomes claros, funções coesas e sem código morto.
7. Execute checks de inspeção deste arquivo e todos os gates oficiais. Compare
   a contagem final de testes com o baseline.
8. Crie o relatório exigido com evidência verificável. Valide também o próprio
   relatório com Markdown lint.
9. Marque somente tarefas 1.1–1.5 depois de todos os critérios passarem.
10. Faça um único commit claro, push e pare. Não inicie S2.

## Objetivo vertical

Entregar o fluxo completo `CSV do censo → normalização segura → snapshot
persistido`, mantendo o dado clínico original e sem mudar qualquer cálculo de
ocupação. O resultado observável é que todo novo `CensusSnapshot` possui uma
faixa mínima pronta para uso futuro, enquanto extração, completude e
processamento clínico continuam funcionando.

## Requisitos funcionais

### R1 — Estados mínimos

Criar choices persistíveis exatamente equivalentes a:

```text
under_12
age_12_or_over
unknown
not_applicable
```

Use nome de campo e classe coerentes com o domínio. Não persista a string etária
bruta nem introduza dependência em `Patient`.

### R2 — Inteiros

Para linha ocupada:

- `0` a `11` → `under_12`;
- `12` ou maior → `age_12_or_over`;
- o limite 12 é adulto;
- espaços ao redor podem ser normalizados;
- negativo ou formato numérico não inteiro → `unknown`.

O legado pode usar inteiro para anos ou para o dia de nascimento; abaixo de 12
a ambiguidade não muda a faixa.

### R3 — Meses e dias

Aceitar, sem diferença de caixa e com normalização segura, os formatos
conhecidos:

```text
Nm
NmDd
```

Exemplos obrigatórios: `1m` e `1m3d`. A implementação deve comparar a idade
normalizada ao limite de 12 anos e rejeitar estruturas/unidades inválidas. Não
crie parser genérico de linguagem natural.

### R4 — Idade desconhecida

Linha ocupada com idade vazia, negativa, unidade não suportada ou estrutura
inválida recebe `unknown`. Não inferir por nome, prontuário, especialidade,
setor, outra linha ou banco de pacientes.

### R5 — Linha não ocupada

Vago, reserva, manutenção e isolamento recebem `not_applicable`, mesmo que o
CSV contenha algum valor de idade. O status de leito tem precedência.

### R6 — Persistência nova sem backfill

Adicionar migration aditiva. Snapshots antigos recebem default seguro e não são
consultados para reconstruir idade. Não editar migration existente e não criar
data migration com leitura de paciente.

### R7 — Propagação pelo comando real

`parse_census_csv` deve ler a coluna opcional `idade`, produzir a faixa, e o
management command deve persistir o valor em cada `CensusSnapshot`. CSV legado
sem coluna `idade` continua aceito e produz `unknown` para ocupado,
`not_applicable` para não ocupado.

### R8 — Regressão e privacidade

Preservar exatamente:

- `setor`, `setor_codigo`, `leito`, prontuário e demais campos existentes;
- classificação de status de leito;
- gate de completude;
- lifecycle do `IngestionRun` e métricas;
- processamento clínico, que não usa o setor virtual;
- ausência de idade exata no histórico de ocupação.

## Arquivos esperados e limite

Máximo de **5 arquivos de implementação/teste**, além de `tasks.md`:

1. `apps/census/models.py`;
2. uma nova migration `apps/census/migrations/0018_*.py`;
3. `apps/census/services.py`;
4. `apps/census/management/commands/extract_census.py`;
5. um teste novo coeso, preferencialmente
   `tests/unit/test_census_age_band.py`.

O extrator Playwright já fornece a coluna; não o altere sem bloqueio comprovado.
Se precisar tocar sexto arquivo, pare e reporte `INCOMPLETE/BLOQUEADO` antes de
editar. `tasks.md` e o relatório em `/tmp` não contam no limite.

Fora de escopo e proibido neste slice:

- `apps/census/occupancy.py`;
- `apps/census/capacity_catalog.py`;
- JSON de catálogo;
- templates, views ou ADRs;
- alteração de migrations `0001`–`0017`;
- backfill;
- dependência nova;
- dado real de paciente em teste, fixture, log ou relatório.

## TDD obrigatório

### RED

Escreva testes sintéticos que falhem antes da implementação e cubram no mínimo:

1. `0`, `11`, `12` e idade adulta;
2. `1m`, `1m3d`, caixa/espaços e limite em meses;
3. vazio, negativo, decimal e unidade desconhecida;
4. não ocupado sempre `not_applicable`;
5. CSV sem `idade`;
6. comando persiste a faixa em snapshot ocupado e não ocupado;
7. nenhuma alteração dos campos clínicos existentes.

Execute:

```bash
./scripts/test-in-container.sh unit
```

Registre nomes dos testes falhando, exit code e por que a falha prova o
requisito. Se todos passarem antes da implementação, corrija os testes.

### GREEN

Implemente a menor solução que satisfaça R1–R8. Centralize a classificação em
uma função pura e reutilize-a no parser; não duplique regex ou regras no comando.
Rode `unit` até obter exit code 0 e zero failures/errors.

### REFACTOR

Somente depois do GREEN:

- remova duplicação;
- mantenha parser pequeno e determinístico;
- derive limites de campos dos models quando aplicável;
- preserve typing e mensagens sem dados clínicos;
- não adicione abstração para seletores ou occupancy-v2.

## Checks de inspeção obrigatórios

Execute e interprete no relatório:

```bash
rg -n "idade|age_band|under_12|age_12_or_over|unknown|not_applicable" \
  apps/census/models.py apps/census/services.py \
  apps/census/management/commands/extract_census.py \
  tests/unit/test_census_age_band.py
rg -n "idade" automation/source_system/current_inpatients/extract_census.py
rg -n "occupancy-v2|age_band_filter" apps/census || true
git diff --check
git diff --name-only "$BASE_REF"
```

Interpretação obrigatória:

- a coluna já existe no extrator e não foi reimplementada;
- nenhum `occupancy-v2` ou seletor de catálogo foi antecipado;
- somente arquivos permitidos mudaram;
- migration nova é aditiva e migrations antigas não mudaram;
- nenhuma idade, nome ou prontuário real aparece no diff.

## Gates oficiais obrigatórios

Execute exatamente e registre exit code/resumo:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  /tmp/sirhosp-slice-CCO3A-S1-report.md
```

Execução host-only de pytest não substitui nenhum gate oficial.

## Critérios binários de sucesso

- [ ] R1–R8 possuem testes e implementação.
- [ ] Há RED real pelo motivo esperado.
- [ ] Baseline e final oficiais têm exit code registrado.
- [ ] Pytest final tem zero failures/errors.
- [ ] `passed_final >= passed_baseline`.
- [ ] Migration 0018 é aditiva e migrations anteriores estão intactas.
- [ ] CSV sem idade permanece compatível.
- [ ] Idade exata não é persistida no histórico agregado.
- [ ] Nenhum arquivo de S2–S4 foi alterado.
- [ ] Todos os gates e inspeções passaram.
- [ ] Relatório existe, passa Markdown lint e não contém dado sensível.

## Gates de autoavaliação

Responda objetivamente no relatório:

1. Cada formato aceito/rejeitado possui teste de fronteira?
2. Idade 12 é inequivocamente adulta?
3. Status não ocupado sempre vence qualquer idade recebida?
4. CSV sem coluna idade mantém compatibilidade?
5. Existe uma única função de normalização, sem regra duplicada no comando?
6. Algum módulo clínico passou a depender da faixa? A resposta deve ser não.
7. Alguma migration existente ou extrator Playwright foi modificado? Se sim,
   por quê e onde está o bloqueio prévio exigido?
8. O diff contém dado real ou idade individual de paciente? A resposta deve ser
   não.
9. A lista de arquivos respeita o limite de cinco?
10. Todos os comandos obrigatórios têm evidência de exit code 0?

## Condições automáticas de INCOMPLETO

Marque `INCOMPLETE` se ocorrer qualquer situação:

- baseline não executado ou com failure/error;
- RED ausente ou falhando por motivo não funcional;
- teste planejado ausente;
- formato obrigatório sem teste;
- idade exata persistida por conveniência;
- inferência por outro paciente/linha/campo;
- migration antiga editada ou backfill criado;
- arquivo fora do limite alterado sem parar antes;
- occupancy-v2, catálogo ou UI antecipados;
- qualquer check, unit, integration, lint, typecheck, quality gate ou Markdown
  lint falhar;
- pytest final com exit code não zero, failures/errors ou menos `passed` que o
  baseline;
- `tasks.md` marcado apesar de pendência;
- relatório ausente/incompleto ou com dado sensível;
- commit/push feito antes de todos os gates.

## Relatório obrigatório para terceiro LLM

Crie `/tmp/sirhosp-slice-CCO3A-S1-report.md` com:

1. `Status: COMPLETE` ou `Status: INCOMPLETE`;
2. resumo e escopo;
3. `BASE_REF` e estado inicial;
4. matriz requisito → arquivos → testes;
5. baseline oficial com comando, exit code e resumo;
6. RED com comando, testes falhando e motivo esperado;
7. GREEN/REFACTOR com comandos e resultados;
8. lista de arquivos alterados e justificativa;
9. snippets **antes/depois de cada arquivo alterado**; para arquivo novo, usar
   `antes: inexistente`;
10. checks `rg` e interpretação;
11. tabela pytest baseline versus final com passed/failed/errors e exit code;
12. todos os gates oficiais e Markdown lint;
13. respostas aos dez gates de autoavaliação;
14. riscos e limitações;
15. comandos exatos para rerun;
16. seção `Handoff para verificador` com arquivos, commit, checklist R1–R8,
    pontos para inspeção e confirmação de ausência de dados sensíveis.

Não inclua nomes, prontuários, idades reais, CSV real ou credenciais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every artifact listed in the handoff of
openspec/changes/correct-co-3a-occupancy-policy/slice-prompts/SLICE-CCO3A-S1.md.
Implement ONLY CCO3A-S1. Follow the DeepSeek4-Flash protocol literally: clean
baseline, official containerized unit baseline, requirement matrix, real RED,
minimal GREEN, bounded REFACTOR with clean code/DRY/YAGNI, mandatory rg
inspections, every official container gate, baseline-vs-final comparison and a
verifiable report at /tmp/sirhosp-slice-CCO3A-S1-report.md. Touch at most the
five listed implementation/test files; do not implement catalog selectors,
occupancy-v2, UI or ADR. If any test/check/gate/report item is missing or
failing, if final pytest has any failure/error, if passed_final is below the
baseline, or if the file limit must be exceeded, report INCOMPLETE and do not
mark tasks, commit or push. Mark only tasks 1.1-1.5 after all evidence passes,
commit, push, reply REPORT_PATH=/tmp/sirhosp-slice-CCO3A-S1-report.md, then STOP.
```
