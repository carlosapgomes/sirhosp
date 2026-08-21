# SLICE-CCO3A-S2 — Catálogo futuro particionado e dry-run corrigido

## Handoff para implementador LLM com contexto zero

Implemente somente CCO3A-S2 do change
`correct-co-3a-occupancy-policy`. Comece sem assumir contexto de conversa.

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. proposal, design e tasks deste change;
3. delta spec `specs/versioned-sector-capacity-catalog/spec.md`;
4. este prompt;
5. `apps/census/models.py`, `apps/census/capacity_catalog.py` e
   `apps/census/management/commands/activate_sector_capacity_catalog.py`;
6. `apps/census/data/initial_sector_capacity_catalog.json`;
7. migrations `0014`, `0015` e a migration criada por S1;
8. `tests/unit/test_sector_capacity_catalog.py`;
9. relatório `/tmp/sirhosp-slice-CCO3A-S1-report.md`, se disponível.

Pré-condições:

- tarefas 1.1–1.5 marcadas e S1 em commit já integrado;
- `CensusSnapshot` possui faixa normalizada; não a renomeie;
- catálogo inicial e versão de produção `2026-08-19` permanecem imutáveis;
- última migration esperada é a de S1, normalmente `0018`; confirme;
- working tree limpo.

Se uma pré-condição falhar, reporte bloqueio. Não implemente S1 novamente e não
comece materialização v2.

## Protocolo obrigatório para implementador DeepSeek4-Flash

**Qualquer item ausente ou falho torna o slice INCOMPLETO.** Nesse caso, não
marque tasks, não faça commit/push e pare com evidência.

1. Registre `BASE_REF`, branch e `git status --short` limpo.
2. Registre no relatório matriz `R → arquivos → testes` antes de editar.
3. Rode baseline oficial:

   ```bash
   ./scripts/test-in-container.sh unit
   ```

   Pare se houver failure/error.
4. Escreva testes RED primeiro. Rode `unit`; pelo menos um teste novo deve falhar
   pelo comportamento ausente esperado.
5. Implemente GREEN mínimo e somente o catálogo/dry-run.
6. Faça REFACTOR restrito, com clean code, DRY e YAGNI. Não crie DSL de filtros.
7. Execute inspeções, todos os gates oficiais e comparação de testes.
8. Gere e valide o relatório temporário completo.
9. Marque somente 2.1–2.6, faça um commit, push e pare. Não inicie S3.

## Objetivo vertical

Entregar um documento corretivo que percorra
`JSON → parse → validação → dry-run/resultado de ativação`, com seletor etário
persistível, totais verificáveis e nenhuma escrita em dry-run. Ao fim do slice o
catálogo é tecnicamente publicável, mas **não deve ser ativado** até S3, S4,
release e deploy estarem concluídos.

## Requisitos funcionais

### R1 — Seletores mínimos

Cada `CapacitySectorMembership` deve ter um seletor persistido com escolhas:

```text
all
under_12
age_12_or_over
```

Associações antigas recebem `all`. Não reutilize choices de snapshot se isso
acoplar conceitos indevidamente; compartilhe constantes somente quando houver
uma abstração realmente coesa.

### R2 — Exclusividade validada em domínio e banco

Dentro de uma versão:

- um código pode ter uma única associação `all`; ou
- exatamente duas associações, uma `under_12` e uma `age_12_or_over`;
- `all` nunca pode coexistir com partição;
- seletor duplicado, par incompleto e seletor desconhecido são rejeitados antes
  da escrita;
- banco garante unicidade por catálogo, código e seletor;
- `source_code` continua contado uma vez nos diagnósticos distintos.

Não implemente regex, condição arbitrária, faixa configurável ou DSL.

### R3 — Compatibilidade e imutabilidade

Catálogo JSON v1 sem seletor continua válido e equivale a `all`. Ativação de
mesma data/hash permanece idempotente; hash diferente permanece conflito. Não
edite migrations anteriores, JSON inicial ou versão persistida.

### R4 — Fotografia corretiva completa

Adicionar novo arquivo JSON versionado, com nome claro, sem sobrescrever o
inicial. Ele deve copiar os 40 grupos não afetados exatamente e alterar apenas:

- `CO`: mesmos cinco códigos, `unrated`, capacidade `null`, seletor `all`;
- `OBST-3A-ADULTO`: standard, 32, código `654/age_12_or_over`;
- `OBST-3A-INFANTIL`: standard, 16, código `654/under_12`;
- remover a definição antiga `OBST-3A` somente do novo documento.

Nenhum dado de paciente pode entrar no JSON ou proveniência.

### R5 — Totais exatos

Validação e dry-run devem distinguir associação de código distinto e reportar:

```text
grupos oficiais: 43
associações: 48
códigos-fonte distintos: 47
grupos com capacidade: 39
grupos standard: 39
grupos unrated: 4
capacidade conhecida: 666
capacidade calculável: 666
```

Não hardcode totais no comando; derive do documento validado.

### R6 — Persistência atômica

Quando futuramente ativado, o seletor deve ser persistido e ligado ao mesmo
catálogo/grupo em uma transação. Dry-run não grava versão, grupo ou associação.
S2 não executa ativação real nem escolhe data efetiva.

### R7 — Limites e segurança

Derive limites persistíveis do model, mantenha leitura única/hash único do
arquivo, recuperação de corrida e mensagens sanitizadas. Nenhuma dependência
nova, backfill, scheduler ou alteração clínica.

## Arquivos esperados e limite

Máximo de **6 arquivos de implementação/teste**, além de `tasks.md`:

1. `apps/census/models.py`;
2. nova migration `apps/census/migrations/0019_*.py` ou próximo número livre;
3. `apps/census/capacity_catalog.py`;
4. `apps/census/management/commands/activate_sector_capacity_catalog.py`;
5. novo JSON em `apps/census/data/`;
6. `tests/unit/test_sector_capacity_catalog.py`.

Se o próximo número de migration não for 0019, use o grafo real e documente.
Se um sétimo arquivo for necessário, pare antes de editar e reporte bloqueio.

Proibido:

- editar JSON inicial ou migrations existentes;
- `apps/census/occupancy.py`;
- templates/views/ADR;
- ativar catálogo em qualquer banco não efêmero de teste;
- alterar o campo de idade de S1;
- criar política nova além das três existentes;
- incluir dado real.

## TDD obrigatório

### RED

Criar testes antes da implementação para:

1. v1 sem seletor → `all`;
2. um `all` duplicado rejeitado;
3. mistura `all` + etário rejeitada;
4. partição incompleta/duplicada/desconhecida rejeitada;
5. par etário completo aceito e persistido;
6. constraint do banco impede duplicação final;
7. novo JSON possui somente as mudanças aprovadas;
8. totais 43/48/47/39/39/4/666/666;
9. CO sem capacidade e dois grupos 3A corretos;
10. dry-run mostra totais e persiste zero;
11. idempotência/conflito existentes continuam passando.

Execute RED com:

```bash
./scripts/test-in-container.sh unit
```

Falha de fixture ou migration não conta como RED funcional.

### GREEN

Implemente o mínimo necessário. Estenda dataclasses/resultados existentes; não
crie segundo pipeline de ativação. Use uma única validação de combinações por
código e persista os objetos já validados.

### REFACTOR

Após GREEN:

- remova cálculos duplicados de códigos/associações;
- mantenha validação inteira antes da transação;
- mantenha mensagens determinísticas e sem conteúdo clínico;
- evite generalização além dos três seletores.

## Checks de inspeção obrigatórios

```bash
rg -n "all|under_12|age_12_or_over" \
  apps/census/models.py apps/census/capacity_catalog.py \
  apps/census/data tests/unit/test_sector_capacity_catalog.py
rg -n '"stable_key": "CO"|"stable_key": "OBST-3A' \
  apps/census/data/*.json
rg -n '658|626|666|group_count|member_count|code_count' \
  apps/census/capacity_catalog.py \
  apps/census/management/commands/activate_sector_capacity_catalog.py \
  tests/unit/test_sector_capacity_catalog.py
git diff --check
git diff --name-only "$BASE_REF"
git diff "$BASE_REF" -- apps/census/data/initial_sector_capacity_catalog.json \
  apps/census/migrations/0014_capacity_catalog.py \
  apps/census/migrations/0015_fix_capacity_catalog_constraints.py
```

O último diff deve estar vazio. No relatório, comprove que os 40 grupos não
afetados no novo documento equivalem ao inicial e que a diferença se limita a
CO/3A/proveniência/schema.

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
  /tmp/sirhosp-slice-CCO3A-S2-report.md
```

## Critérios binários de sucesso

- [ ] R1–R7 testados e implementados.
- [ ] RED real registrado.
- [ ] v1 sem seletor continua válido como `all`.
- [ ] Ambiguidades são rejeitadas antes de escrita e pela constraint aplicável.
- [ ] JSON inicial e migrations antigas não mudaram.
- [ ] Novo JSON contém 43/48/47 e 666/666.
- [ ] Dry-run escreve zero linhas.
- [ ] Nenhum cálculo de ocupação foi implementado.
- [ ] Todos os gates têm exit code 0 e zero failures/errors.
- [ ] `passed_final >= passed_baseline`.
- [ ] Relatório completo, lintado e sem dados sensíveis.

## Gates de autoavaliação

Responder no relatório:

1. Há alguma combinação capaz de associar uma linha a dois grupos? Deve ser não.
2. Um catálogo v1 sem campo novo ainda ativa e gera o mesmo hash do arquivo
   original? Explique sem alterar o arquivo.
3. O banco e o domínio rejeitam duplicação relevante?
4. Os 40 grupos não afetados foram comparados estruturalmente?
5. CO continua um grupo com cinco códigos e capacidade nula?
6. Código `654` é um código distinto com duas associações exclusivas?
7. Totais são derivados ou hardcoded?
8. Dry-run e conflito de data continuam sem escrita parcial?
9. Algum banco não efêmero ou catálogo de produção foi tocado? Deve ser não.
10. O limite de seis arquivos foi respeitado?

## Condições automáticas de INCOMPLETO

- baseline/RED/gates sem evidência;
- qualquer failure/error ou redução de testes passados;
- catálogo inicial ou migration antiga modificada;
- seletor arbitrário/DSL introduzido;
- combinação ambígua aceita;
- totais divergentes de 43/48/47/666/666;
- CO ainda standard ou com capacidade;
- 3A ainda pending no novo documento;
- dry-run persiste qualquer linha;
- occupancy, UI, ADR ou ativação real antecipados;
- mais de seis arquivos sem bloqueio prévio;
- relatório ausente, não lintado ou com dado sensível;
- tasks/commit feitos antes dos gates.

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CCO3A-S2-report.md` contendo:

- status COMPLETE/INCOMPLETE;
- `BASE_REF`, branch, working tree e baseline;
- matriz R1–R7 → arquivo → teste;
- RED e GREEN com comandos, exit codes e resumos;
- arquivos alterados e justificativa;
- snippets antes/depois de cada arquivo; novos arquivos como `inexistente`;
- prova estrutural dos 40 grupos preservados;
- saída sintética do dry-run e contagens no banco de teste antes/depois;
- checks de inspeção interpretados;
- tabela pytest baseline/final;
- todos os gates;
- respostas aos dez gates;
- riscos/limitações;
- comandos exatos para rerun;
- `Handoff para verificador`: commit, arquivos, checklist R1–R7, inspeções
  críticas e confirmação de que nenhuma ativação real ocorreu.

Não copiar segredo, dump, catálogo persistido de produção ou dado clínico.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and every file listed in the zero-context
handoff of SLICE-CCO3A-S2.md. Implement ONLY the vertical catalog/dry-run slice.
Use the mandatory DeepSeek4-Flash protocol: clean official baseline, matrix,
real RED, minimal GREEN, clean-code/DRY/YAGNI refactor, rg inspections, all
container quality gates, strict OpenSpec validation, baseline-vs-final evidence
and /tmp/sirhosp-slice-CCO3A-S2-report.md. Touch no more than the six listed
implementation/test files. Preserve the initial JSON, old migrations and v1
compatibility; do not implement occupancy-v2, UI, ADR or activate a real
catalog. If any required evidence/gate fails, final pytest has failure/error or
fewer passes, ambiguity remains, totals differ, or the file limit must be
exceeded, report INCOMPLETE and do not mark tasks, commit or push. Mark only
2.1-2.6 after success, commit, push, reply with REPORT_PATH, then STOP.
```
