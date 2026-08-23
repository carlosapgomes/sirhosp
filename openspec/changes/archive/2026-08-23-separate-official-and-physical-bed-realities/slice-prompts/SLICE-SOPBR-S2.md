# SOPBR-S2 — Catálogo integral futuro e ativação explícita v3

## Handoff para implementador com contexto zero

Você está no SIRHOSP após a conclusão obrigatória do slice SOPBR-S1. Este é o
segundo de três slices do change
`separate-official-and-physical-bed-realities`.

Leia integralmente, nesta ordem:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. proposal, design, tasks e cinco delta specs deste change;
4. `slice-prompts/SLICE-SOPBR-S1.md` somente para contratos já entregues;
5. `/tmp/sirhosp-slice-SOPBR-S1-report.md`, se disponível;
6. este arquivo;
7. `apps/census/models.py` e a migration criada em S1;
8. `apps/census/capacity_catalog.py`;
9. `apps/census/management/commands/activate_sector_capacity_catalog.py`;
10. `apps/census/data/initial_sector_capacity_catalog.json`;
11. `apps/census/data/corrected_sector_capacity_catalog.json`;
12. `tests/unit/test_sector_capacity_catalog.py`.

Pré-condições obrigatórias:

- tarefas 1.1 a 1.6 estão marcadas;
- S1 está commitado e disponível no branch;
- modelo possui contexto opcional de algoritmo e runtime suporta v3;
- working tree versionado está limpo;
- artefatos JSON inicial e corrigido não têm diff.

Se qualquer pré-condição falhar, não codifique: reporte
`INCOMPLETE/BLOQUEADO`.

Objetivo deste slice: tornar v3 publicável de forma temporal, explícita e
reprodutível por um novo catálogo integral. O slice termina em dry-run e testes;
não publica catálogo real nem altera produção.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por modelo rápido. Se qualquer item falhar, o
slice está **INCOMPLETO**: não marque tarefas, não faça commit/push e reporte a
evidência.

1. Registre matriz `Requisito → arquivo(s) → teste(s)/inspeção` antes de editar.
2. Registre `BASE_REF=$(git rev-parse HEAD)` e `git status --short` limpo.
3. Execute baseline oficial antes de editar:
   `./scripts/test-in-container.sh unit`. Registre exit code, passed, zero failed
   e zero errors; falha bloqueia.
4. Escreva testes RED antes de alterar parser, comando ou JSON.
5. Faça GREEN mínimo, sem tocar cálculo, view, template, ADR ou migration.
6. Refatore somente duplicação local, com clean code, DRY e YAGNI.
7. Execute todas as inspeções e gates deste arquivo.
8. Compare pytest final com baseline; `passed_final >= passed_baseline`.
9. Produza relatório com evidência e handoff para verificador.

## Objetivo vertical

Dado um novo documento integral de catálogo com schema atualizado e algoritmo
`occupancy-v3`, o operador consegue executar dry-run e obter algoritmo e totais
43/48/47/666/666 sem escrita. Quando usado em teste com data futura, o mesmo
fluxo persiste atomicamente v3; documentos inválidos são rejeitados e os dois
JSONs históricos permanecem byte a byte inalterados.

## Requisitos funcionais do slice

### R1 — Schema atualizado exige algoritmo explícito

Defina uma evolução pequena e explícita do schema de catálogo.

- documentos históricos no schema atual, sem algoritmo, continuam válidos;
- documento no schema novo exige `occupancy_algorithm_version` não vazio;
- valores suportados são exatamente os algoritmos implementados;
- valor desconhecido falha antes de qualquer escrita;
- não inferir v3 por nome de arquivo, hash, data ou presença de duplicata.

### R2 — Persistência imutável do algoritmo

Propagar algoritmo por:

- `ValidatedCatalog`;
- `ActivationResult`;
- persistência de `CapacityCatalogVersion`;
- saída segura do management command.

Dry-run e criação real sintética devem reportar o mesmo algoritmo. Reativação
da mesma data/hash permanece idempotente; hash divergente permanece conflito.

### R3 — Novo catálogo integral v3

Criar novo arquivo, com nome claro e versionado, em `apps/census/data/`.

Ele deve:

- declarar schema novo e `occupancy-v3`;
- conter fotografia integral, não delta;
- preservar os 43 grupos do catálogo corrigido;
- preservar 48 associações e 47 códigos distintos;
- preservar 39 grupos standard, quatro unrated e capacidades 666/666;
- manter CO unrated;
- manter 3A Adulto 32 e Infantil 16 com seletores aprovados;
- manter os outros 40 grupos estruturalmente idênticos;
- usar nova `source_reference` sem conteúdo sensível.

É proibido editar:

- `initial_sector_capacity_catalog.json`;
- `corrected_sector_capacity_catalog.json`.

### R4 — Dry-run observável e sem escrita

O resultado e a saída do comando devem incluir algoritmo v3 e totais aprovados.
Teste deve contar versões, grupos e memberships antes/depois e provar zero
escrita no dry-run.

### R5 — Ativação futura preservada

Teste sintético deve provar:

- hoje/passado rejeitados;
- data futura persiste versão, algoritmo, grupos e associações atomicamente;
- mesmo documento/data é idempotente;
- documento diferente na mesma data falha;
- nenhuma migration, import, startup ou teste publica o arquivo v3
  automaticamente.

Não execute ativação contra produção ou banco persistente não isolado.

### R6 — Compatibilidade histórica

- JSONs históricos continuam válidos sem campo explícito;
- catálogo histórico já persistido com algoritmo nulo continua despachável por
  S1;
- nenhum catálogo existente é atualizado neste slice;
- nenhum backfill ou migration nova é criado.

### R7 — Privacidade e operação simples

Documento, saída, erro e teste contêm somente metadados de catálogo. Não
adicionar dependência, serviço, scheduler, credencial ou dado real.

## Arquivos esperados e limite

Limite rígido: **até 4 arquivos alterados/criados**.

Arquivos esperados:

1. `apps/census/capacity_catalog.py`;
2. `apps/census/management/commands/activate_sector_capacity_catalog.py`;
3. `apps/census/data/<novo-catalogo-v3>.json`;
4. `tests/unit/test_sector_capacity_catalog.py`.

Se precisar alterar model, migration, occupancy, view, outro teste ou quinto
arquivo, pare e reporte **INCOMPLETO/BLOQUEADO**. Não corrija S1 silenciosamente.

## Fora de escopo e arquivos proibidos

Não alterar:

- `apps/census/models.py` ou migrations;
- `apps/census/occupancy.py`;
- `apps/census/views.py`;
- template de `/beds`;
- ADRs;
- JSON inicial ou corrigido;
- release/deploy;
- autenticação e outros apps.

Não ativar catálogo real. Não escolher data efetiva de produção.

## TDD obrigatório

### RED

Antes do código produtivo, criar testes sintéticos para:

1. schema novo sem algoritmo é rejeitado;
2. algoritmo desconhecido é rejeitado;
3. algoritmo v3 chega ao `ValidatedCatalog`;
4. dry-run retorna/imprime v3 e não escreve;
5. ativação futura persiste v3;
6. idempotência e conflito continuam;
7. JSON v3 fecha 43/48/47/39/4/666/666;
8. CO e 3A permanecem corretos;
9. 40 grupos não afetados são equivalentes ao catálogo corrigido;
10. arquivos históricos continuam aceitos sem campo novo.

Execute:

```bash
./scripts/test-in-container.sh unit
```

Registre pelo menos uma falha nova causada pela ausência do contrato de
algoritmo, com nome, assertion, exit code e resumo. Falha de JSON por caminho
errado ou sintaxe não é RED funcional válido.

### GREEN

Implemente apenas parser, propagação, saída e novo documento. Execute:

```bash
./scripts/test-in-container.sh unit
```

Todos os testes devem passar.

### REFACTOR

Depois do GREEN:

- mantenha uma única allowlist de algoritmo;
- evite duplicar validação entre parser e command;
- derive totais das estruturas já validadas;
- mantenha mensagens sem caminho absoluto ou payload;
- não criar abstração para algoritmos futuros inexistentes;
- não reformatar os JSONs históricos.

## Checks de inspeção obrigatórios

Execute e interprete no relatório:

```bash
rg -n "occupancy_algorithm_version|occupancy-v3|ALLOWED" \
  apps/census/capacity_catalog.py \
  apps/census/management/commands/activate_sector_capacity_catalog.py \
  tests/unit/test_sector_capacity_catalog.py
rg -n '"occupancy_algorithm_version"|"stable_key"|"source_code"' \
  apps/census/data/<novo-catalogo-v3>.json
rg -n "activate_sector_capacity_catalog|apps/census/data" \
  apps/census/migrations config compose*.yml deploy scripts
rg -n "Celery|Redis|apply_async|\.delay\(" \
  apps/census/capacity_catalog.py \
  apps/census/management/commands/activate_sector_capacity_catalog.py
git diff --exit-code -- \
  apps/census/data/initial_sector_capacity_catalog.json \
  apps/census/data/corrected_sector_capacity_catalog.json
git diff --name-only "$BASE_REF"..HEAD -- apps/census/migrations
```

No relatório:

- substitua `<novo-catalogo-v3>` pelo nome real;
- confirme que buscas de ativação automática não mostram import/migration/
  startup do documento;
- confirme que `git diff --exit-code` dos históricos retornou 0;
- antes do commit, use também `git diff --name-only "$BASE_REF"` para provar o
  limite de quatro arquivos;
- ausência de migration nova é obrigatória.

Execute dry-run somente no ambiente de teste/diagnóstico local, com data
dinamicamente futura, nunca hardcoded para produção. Registre comando sem
credenciais e saída agregada.

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

Markdown lint é obrigatório porque um JSON não o aciona, mas `tasks.md` será
alterado localmente e todos os artefatos do change devem continuar válidos.
Registre exit code e resumo de cada comando.

## Critérios de sucesso binários

- [ ] S1 completo e working tree inicial limpo.
- [ ] Baseline oficial verde registrado antes de editar.
- [ ] RED funcional real registrado.
- [ ] Schema novo exige algoritmo explícito suportado.
- [ ] Históricos sem campo continuam válidos e não são editados.
- [ ] Algoritmo v3 percorre validação, resultado, saída e persistência.
- [ ] Novo documento é integral e fecha 43/48/47/39/4/666/666.
- [ ] CO, 3A e 40 grupos restantes estão preservados.
- [ ] Dry-run escreve zero linhas.
- [ ] Ativação futura sintética permanece atômica e idempotente.
- [ ] Não há ativação automática nem data de produção hardcoded.
- [ ] Nenhum dado sensível ou dependência foi adicionado.
- [ ] Todos os gates e inspeções passaram.
- [ ] Limite de quatro arquivos foi respeitado.
- [ ] Relatório obrigatório foi criado.

## Gates de autoavaliação

Responda no relatório:

1. Como schema histórico e schema novo são distinguidos?
2. Onde está a allowlist única de algoritmos?
3. Como se prova que v3 não é inferido por data ou nome do arquivo?
4. Quais contagens provam fotografia integral?
5. Como os 40 grupos não afetados foram comparados?
6. Qual teste prova zero escrita no dry-run?
7. Qual teste prova algoritmo persistido e idempotência?
8. Algum arquivo histórico mudou um byte?
9. Existe qualquer caminho de ativação automática?
10. Foram tocados exatamente quais arquivos e por quê?

### Condições automáticas de INCOMPLETO

Marque incompleto se:

- S1 não estiver completo/verde;
- baseline não tiver sido executado antes da edição;
- RED real não existir;
- qualquer gate, integração, lint, typecheck ou Markdown lint falhar;
- pytest final tiver failure/error ou menos passed que baseline;
- schema novo aceitar ausência/algoritmo desconhecido;
- v3 for inferido por data, hash, filename ou estado global;
- qualquer JSON histórico for alterado;
- novo catálogo não for integral ou totais divergirem;
- dry-run escrever qualquer linha;
- publicação real for executada;
- migration/model/occupancy/view/template/ADR for alterado;
- mais de quatro arquivos forem tocados;
- `tasks.md` for marcado antes das evidências;
- relatório não contiver snippets antes/depois por arquivo.

## Relatório obrigatório

Crie exatamente:

```text
/tmp/sirhosp-slice-SOPBR-S2-report.md
```

Inclua:

1. status COMPLETE/INCOMPLETE;
2. `BASE_REF`, estado inicial e confirmação de S1;
3. matriz R1..R7;
4. baseline, RED e GREEN com comandos/exit codes/resumos;
5. lista e justificativa dos arquivos;
6. snippets antes/depois por arquivo;
7. resumo estrutural comparativo dos três JSONs, sem copiar o arquivo inteiro;
8. dry-run e prova de zero escrita;
9. inspeções `rg` e diffs dos históricos;
10. gates oficiais e comparação baseline/final;
11. respostas de autoavaliação;
12. riscos e limitações;
13. comandos exatos para rerun;
14. `Handoff para verificador` com checklist R1..R7.

Somente após tudo passar, marque tarefas 2.1 a 2.5, commit/push, responda
`REPORT_PATH=/tmp/sirhosp-slice-SOPBR-S2-report.md` e pare.

## Prompt pronto para o implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and all artifacts of
separate-official-and-physical-bed-realities, then read
slice-prompts/SLICE-SOPBR-S2.md completely. Assume zero prior context. Verify
SOPBR-S1 is complete and the tracked tree is clean before editing.

Implement ONLY SOPBR-S2 with TDD RED -> GREEN -> REFACTOR, clean code, DRY and
YAGNI. Run the official containerized unit baseline before editing. Touch only
capacity_catalog.py, the activation command, one new full v3 JSON and
unit test_sector_capacity_catalog.py: maximum four files. Never edit historical
JSONs, models, migrations, occupancy, views, template or ADR. Do not activate a
real catalog and do not hardcode a production date.

Execute every inspection and official gate, integration, OpenSpec strict and
Markdown lint. If any gate/test/check fails, pytest has failure/error,
passed_final < baseline, historical JSON changes, dry-run writes, or file limit
is exceeded, report INCOMPLETE, do not mark tasks and do not commit/push.

Create /tmp/sirhosp-slice-SOPBR-S2-report.md with baseline/RED/GREEN, before and
after snippets for every changed file, structural JSON comparison, zero-write
dry-run evidence, gates, rerun commands and Handoff para verificador. Mark
2.1-2.5 only when complete, commit, push, reply REPORT_PATH and STOP.
```
