# Prompt corretivo SCOH-S1-R1

## Missão

Corrigir a implementação rejeitada do slice `SCOH-S1` do change:

`add-versioned-sector-capacity-occupancy-history`

Não implemente SCOH-S2, medições, resumos diários ou UI. Este trabalho é uma
revisão corretiva do catálogo versionado já publicado no commit:

`9e133260b8234be25c58e60bd65bd53569c2de99`

O verificador independente classificou o slice como **INCOMPLETE**. Leia o
parecer completo antes de editar:

`/tmp/sirhosp-slice-SCOH-S1-verification.md`

## Handoff obrigatório para contexto zero

Leia completamente, nesta ordem:

1. `AGENTS.md`;
2. `PROJECT_CONTEXT.md`;
3. todos os artefatos em
   `openspec/changes/add-versioned-sector-capacity-occupancy-history/`;
4. `slice-prompts/SLICE-SCOH-S1.md`;
5. `/tmp/sirhosp-slice-SCOH-S1-report.md`;
6. `/tmp/sirhosp-slice-SCOH-S1-verification.md`;
7. `apps/census/models.py`;
8. `apps/census/migrations/0014_capacity_catalog.py`;
9. `apps/census/capacity_catalog.py`;
10. `apps/census/management/commands/activate_sector_capacity_catalog.py`;
11. `apps/census/data/initial_sector_capacity_catalog.json`;
12. `tests/unit/test_sector_capacity_catalog.py`;
13. `/tmp/sirhosp-correspondencia-setores-capacidade.md`;
14. `/tmp/sirhosp-capacity-db-recent.txt`.

Os arquivos em `/tmp` contêm somente informações agregadas e nomes de setores.
Não consulte produção e não use dados de pacientes.

## Estado inicial esperado

- `HEAD` e `origin/master` apontam para `9e13326` ou para um descendente que
  ainda não corrigiu SCOH-S1.
- O quality gate oficial passa com 2412 testes.
- Os artefatos e relatório do slice passam em Markdown lint direcionado.
- O gate global `./scripts/markdown-lint.sh` possui dívida preexistente fora do
  slice. Isso continua sendo bloqueador formal do status global.
- Tasks 1.1-1.7 estão marcadas, mas o verificador rejeitou essa conclusão.
- A migration `0014` já foi publicada em `master`; não a reescreva.

Se o estado real divergir, pare e reporte antes de editar.

## Protocolo obrigatório para DeepSeek4-Flash

Siga literalmente:

1. Registre `BASE_REF=$(git rev-parse HEAD)` e `git status --short`.
2. Não sobrescreva mudanças alheias. Se houver alterações inexplicadas nos
   arquivos esperados, pare.
3. Registre no relatório uma matriz
   `Correção -> arquivo(s) -> teste(s) -> inspeção`.
4. Rode o baseline oficial antes de editar:
   `./scripts/test-in-container.sh unit`.
5. Baseline com qualquer falha/erro bloqueia a correção.
6. Adicione todos os testes de regressão primeiro e prove RED real por
   assertion. Erro de import, fixture ou ambiente não vale como RED.
7. Implemente GREEN mínimo somente para os itens C1-C7 abaixo.
8. Faça REFACTOR apenas após GREEN, aplicando clean code, DRY e YAGNI.
9. Rode os checks de inspeção e todos os gates definidos neste prompt.
10. Não marque tasks, não declare o slice completo e não inicie SCOH-S2 se
    qualquer condição automática de INCOMPLETO permanecer.
11. Gere o relatório corretivo exigido, mesmo se o resultado final for
    incompleto.
12. Não altere ou reescreva o commit já publicado. Toda correção deve aparecer
    como novo diff e futuro commit corretivo.

## Correções obrigatórias

### C1. Corrigir os nomes esperados do sistema fonte

`configured_source_name` deve conter o valor esperado em
`CensusSnapshot.setor`, e não um apelido inventado ou o nome resumido da UI.

Use exatamente esta tabela para a configuração inicial:

| Código | `configured_source_name` esperado |
| --- | --- |
| 751 | `0 - SALA DE PROCEDIMENTO ADULTO HGRS` |
| 728 | `0 0 - CHD - HGRS` |
| 721 | `0 L - INTERMEDIARIO ALA C - HGRS` |
| 719 | `0 N - CARDIOCLINICA` |
| 720 | `0 S - INTERMEDIÁRIO ALA B - HGRS` |
| 20 | `0 T - CENTRO OBSTETRICO (CO) - HGRS` |
| 733 | `0 T - CRPA - HGRS` |
| 1522 | `0 T - CRPA - HH` |
| 2702 | `0 T - ENFERMARIA GASTROENTEROLOGIA - HGRS` |
| 1116 | `0 T - INTERNAÇÃO CENTRO OBSTETRICO` |
| 731 | `0 T - SALA AMARELA ADULTO HGRS` |
| 738 | `0 T - SALA AMARELA PED HGRS` |
| 1114 | `0 T - SALA DE ESTABILIZAÇÃO CO (RN)` |
| 1112 | `0 T - SALA DE MEDICACAO - OBSERVACAO CO` |
| 1002 | `0 T - SALA DE MEDICACAO PED HGRS` |
| 954 | `0 T - SALA DE OBSERVACAO ADULTO HGRS` |
| 1110 | `0 T - SALA DE OBSERVACAO GINECOLOGICA` |
| 747 | `0 T - SALA DE OBSERVACAO PED HGRS` |
| 745 | `0 T - SALA LARANJA ADULTO HGRS` |
| 1004 | `0 T - SALA LARANJA PED HGRS` |
| 729 | `0 T - SALA VERMELHA ADULTO HGRS` |
| 732 | `0 T - SALA VERMELHA PED HGRS` |
| 637 | `0 T - UNIDADE DE AVC - HGRS` |
| 628 | `0 T - UTI CARDIOVASCULAR - HGRS` |
| 630 | `0 T - UTI CIRÚRGICA - HGRS` |
| 633 | `0 T - UTI GERAL ADULTO 1 - HGRS` |
| 634 | `0 T - UTI GERAL ADULTO 2 - HGRS` |
| 629 | `0 T - UTI NEUROLÓGICA - HGRS` |
| 631 | `0 T - UTI PEDIATRICA - HGRS` |
| 640 | `1 6 - 1A - CIRURGIA GERAL - HGRS` |
| 642 | `1 7 - 1B - HGRS` |
| 644 | `1 8 - 1C - CIRURGIAS ELETIVAS - HGRS` |
| 2155 | `2 6 - 2A - CLINICA ISOLAMENTO` |
| 643 | `2 6 - 2A - ONCOHEMATO - HGRS` |
| 2156 | `2 7 - 2B - CARDIO - HGRS` |
| 651 | `2 7 - 2B - NEUROCLINICA - HGRS` |
| 652 | `2 8 - 2C - CLINICA MÉDICA - HGRS` |
| 2158 | `2 8 - 2C - ENDOCRINO - HGRS` |
| 654 | `3 6 - 3A - OBSTETRÍCIA CLÍNICA - HGRS` |
| 653 | `3 7 - 3B - OBSTETRÍCIA CIRÚRGICA - HGRS` |
| 655 | `3 8 - 3C - UNID. CUIDADOS INTERM. NEONATAL CANGURU (UCINCA) - HGRS` |
| 635 | `3 8 - 3C - UNID. CUIDADOS INTERM. NEONATAL CONV. (UCINCO) - HGRS` |
| 636 | `3 8 - 3C - UTI NEONATAL (UTIN) - HGRS` |
| 656 | `4 6 - 4A - ONCOHEMATOLOGIA - HGRS` |
| 1926 | `4 6 - UTI ONCOHEMATO - HGRS` |
| 658 | `4 7 - 4B - NEUROCIRURGIA - HGRS` |
| 659 | `4 8 - 4C - CLINICA MÉDICA PEDIÁTRICA - HGRS` |

Adicione um teste que compare o dicionário completo código-nome. Não teste
somente quantidade ou subconjunto.

`display_name` é o rótulo oficial resumido da UI e permanece separado. Use os
nomes resumidos aprovados em
`/tmp/sirhosp-correspondencia-setores-capacidade.md`; corrija rótulos
enganosos, como:

- CHD não é `Cardiologia - HGRS`;
- `INT-B` e `INT-C` são Intermediários, não Internações;
- `UTI-ONCO` é Oncohematologia;
- código 1002 é Sala de Medicação Pediátrica;
- grupo CO é Centro Obstétrico.

Não invente novas identidades ou capacidades.

### C2. Corrigir a proveniência do catálogo inicial

A referência atual contém o ano incorreto `2025-08-16`.

A proveniência deve identificar, sem versionar o documento original:

- arquivo administrativo: `setores-leitos.xls`;
- SHA-256:
  `fa5c4e95941794b4a90f2011d0584ae9eb5d4a5178e7e4022debeef4db8ca4dd`;
- última gravação observada: `29/07/2026`;
- baseline aprovada: `16/08/2026`;
- indicação de que o JSON é uma síntese versionada e sem dados de pacientes.

Respeite `max_length=255`. Adicione teste de regressão para ano, nome do
arquivo e hash da fonte administrativa.

### C3. Corrigir a constraint política-capacidade no banco

A constraint atual permite `NULL` para `standard` e
`linked_slots_pending`, pois `CHECK(NULL)` é aceito pelo PostgreSQL.

No estado dos models, a ramificação calculável deve exigir explicitamente:

```text
official_capacity IS NOT NULL AND official_capacity > 0
```

Não reescreva `0014_capacity_catalog.py`, porque ela já está publicada em
`master`. Crie migration aditiva `0015` que:

1. remova `ck_capacity_group_policy_capacity`;
2. recrie a constraint com semântica correta e nome rastreável;
3. não altere ou apague dados.

Adicione testes de banco provando `IntegrityError` para:

- `standard` com capacidade nula;
- `linked_slots_pending` com capacidade nula;
- `unrated` com capacidade não nula;
- capacidade zero.

Não aceite a justificativa anterior de que PostgreSQL não consegue rejeitar o
caso nulo.

### C4. Tornar a corrida de mesmo hash idempotente

`select_for_update()` não bloqueia uma data ainda inexistente. Em duas
publicações concorrentes, a perdedora pode receber `IntegrityError`.

Após sair da transação abortada:

1. releia a versão pela data efetiva;
2. se o hash vencedor for igual, retorne no-op idempotente;
3. se o hash for diferente, levante `CatalogConflictError`;
4. se nenhuma versão existir, levante erro seguro preservando a causa;
5. não deixe linhas parciais.

Adicione testes determinísticos que executem o ramo de recuperação de
`IntegrityError` para:

- vencedor com mesmo hash -> sucesso com `created=False`;
- vencedor com hash diferente -> conflito;
- ausência inesperada da versão -> conflito seguro.

O teste antigo que apenas pré-cria hash diferente não comprova concorrência e
não é suficiente sozinho.

### C5. Ler, validar e hashear o mesmo buffer

O serviço atual chama `Path.read_bytes()` duas vezes. Elimine o risco TOCTOU:

```text
read once -> bytes imutáveis -> decode/parse -> validate -> SHA-256
```

Adicione teste com spy/mock provando que a ativação lê o arquivo exatamente uma
vez e que o hash persistido é derivado dos mesmos bytes validados.

Não crie abstração genérica de storage ou importador.

### C6. Fazer dry-run validar todos os limites persistíveis

A validação integral deve rejeitar antes da escrita, inclusive em `--dry-run`,
strings acima dos limites dos models:

- `schema_version`: 20;
- `source_reference`: 255;
- `stable_key`: 100;
- `display_name`: 255;
- `source_code`: 50;
- `configured_source_name`: 255.

Adicione testes parametrizados para cada limite excedido, comprovando:

- `CatalogValidationError`;
- zero linhas persistidas;
- mensagem segura que não despeja o documento inteiro.

Mantenha DRY: derive limites dos campos Django ou centralize constantes com
nomes claros; não duplique números sem necessidade.

### C7. Exigir data estritamente `YYYY-MM-DD`

`date.fromisoformat()` aceita formatos adicionais. Rejeite explicitamente:

- `20260817`;
- `2026-W34-1`;
- datas/formatos inválidos.

Aceite somente o formato de dez caracteres `YYYY-MM-DD`, com data real válida,
e continue exigindo dia estritamente futuro em `America/Bahia`.

Adicione testes RED/GREEN para os formatos acima.

## Arquivos esperados e limite rígido

Máximo de **5 arquivos de implementação**, excluindo `tasks.md` e relatório:

```text
apps/census/models.py
apps/census/migrations/0015_fix_capacity_catalog_constraints.py
apps/census/capacity_catalog.py
apps/census/data/initial_sector_capacity_catalog.json
tests/unit/test_sector_capacity_catalog.py
```

O comando não deve precisar de alteração. Se precisar tocar um sexto arquivo de
implementação, pare e reporte bloqueio antes de editar.

Não alterar:

- views ou templates;
- processamento de snapshot;
- orquestrador ou scraping;
- modelos de medição/resumo;
- dependências;
- Admin;
- dados ou banco de produção;
- arquivos fora do app census e do OpenSpec task state.

## TDD obrigatório

### RED

Antes de corrigir produção, adicione testes que falhem por assertion para:

1. dicionário exato dos 47 nomes fonte;
2. proveniência correta;
3. constraints nulas para duas políticas calculáveis;
4. recuperação concorrente de mesmo/diferente hash;
5. leitura única do payload;
6. limites máximos em dry-run;
7. formatos de data compacta e ISO week rejeitados.

Execute o teste focado em container e registre nomes, exit code e resumo.
Pelo menos um teste por C1-C7 deve falhar pelo motivo esperado.

### GREEN

Implemente a menor correção que faça todos os testes passarem. Não refatore a
arquitetura do catálogo além do necessário.

### REFACTOR

Depois do GREEN:

- remova duplicações na validação de strings e recuperação de conflito;
- mantenha parse, validação e persistência coesos;
- use nomes claros e type hints;
- mantenha transação e tratamento de corrida explícitos;
- aplique clean code, DRY e YAGNI;
- não introduza repository, plugin, signal ou política futura.

Rode os testes após cada refactor.

## Checks de inspeção obrigatórios

Execute e interprete no relatório:

```bash
python3 -m json.tool \
  apps/census/data/initial_sector_capacity_catalog.json >/dev/null
rg -n \
  "official_capacity__isnull=False|ck_capacity_group_policy_capacity" \
  apps/census/models.py \
  apps/census/migrations/0015_fix_capacity_catalog_constraints.py
rg -n \
  "IntegrityError|source_sha256|read_bytes|fromisoformat|fullmatch" \
  apps/census/capacity_catalog.py
rg -n \
  "2025-08-16|Cardiologia 719|Centro Obstetrico 1110|Medicina Pediátrica" \
  apps/census/data/initial_sector_capacity_catalog.json
rg -n \
  "OccupancyMeasurement|DailyOccupancy|bed_status_view" \
  apps/census tests/unit/test_sector_capacity_catalog.py
uv run python manage.py makemigrations --check --dry-run
git diff --check
git status --short
```

Interpretação obrigatória:

- JSON válido;
- constraint corrigida no model e em migration aditiva;
- leitura de payload ocorre uma única vez por ativação;
- busca por valores antigos incorretos não possui match;
- não há implementação de slices futuros;
- não há migration drift;
- somente arquivos permitidos estão alterados.

Adicione também um pequeno script Python no relatório, sem criar arquivo no
repositório, que compare o dicionário exato dos 47 nomes esperados com o JSON e
imprima:

```text
expected=47
configured=47
mismatches=0
```

## Gates obrigatórios

Execute:

```bash
./scripts/test-in-container.sh quality-gate
npx --yes markdownlint-cli2 \
  --config .markdownlint-cli2.yaml \
  /tmp/sirhosp-slice-SCOH-S1-R1-report.md \
  'openspec/changes/add-versioned-sector-capacity-occupancy-history/**/*.md'
./scripts/markdown-lint.sh
openspec validate \
  add-versioned-sector-capacity-occupancy-history \
  --type change --strict
```

O gate global de Markdown deve ser executado e seu resultado não pode ser
omitido ou reinterpretado.

## Política especial para a dívida global de Markdown

Este prompt não autoriza corrigir 1631 erros Markdown fora do escopo.

Se `./scripts/markdown-lint.sh` continuar falhando exclusivamente fora dos
arquivos tocados:

- conclua tecnicamente C1-C7;
- mantenha tasks 1.1-1.7 desmarcadas;
- use no relatório o status
  `CORRECTIONS_APPLIED_SLICE_INCOMPLETE_GLOBAL_MARKDOWN`;
- não declare `COMPLETE`;
- não inicie SCOH-S2;
- não faça commit/push;
- entregue o diff e o relatório ao planner para resolver a dívida em change
  separado.

Somente se o gate global também retornar zero poderá:

- marcar tasks 1.1-1.7;
- declarar `Status: COMPLETE`;
- criar commit corretivo e push;
- solicitar nova verificação.

## Critérios binários de sucesso técnico

- [ ] C1: os 47 nomes fonte são exatos e `mismatches=0`.
- [ ] C2: proveniência contém arquivo, hash e datas de 2026 corretos.
- [ ] C3: PostgreSQL rejeita nulo nas duas políticas calculáveis.
- [ ] C4: corrida de mesmo hash retorna no-op; hash diferente conflita.
- [ ] C5: payload é lido uma vez e hash/parse usam os mesmos bytes.
- [ ] C6: dry-run rejeita cada campo acima de `max_length`.
- [ ] C7: somente `YYYY-MM-DD` é aceito.
- [ ] RED real registrado para C1-C7.
- [ ] Teste focado e quality gate passam.
- [ ] OpenSpec estrito passa.
- [ ] Markdown direcionado passa.
- [ ] Nenhum slice futuro ou arquivo fora do limite foi tocado.
- [ ] Não há dados de pacientes, credenciais ou acesso à produção.
- [ ] Relatório contém evidência verificável e reruns.

## Condições automáticas de INCOMPLETO

O trabalho permanece incompleto se qualquer item ocorrer:

- algum C1-C7 não possui teste RED/GREEN;
- qualquer nome fonte diverge;
- proveniência mantém ano/hash incorreto;
- `standard=NULL` ou `linked_slots_pending=NULL` passa no banco;
- corrida de mesmo hash levanta conflito;
- ativação lê o arquivo mais de uma vez;
- dry-run aceita campo maior que o model;
- data compacta ou ISO week é aceita;
- migration `0014` é reescrita;
- migration drift existe;
- teste, check, lint, mypy ou OpenSpec falha;
- passou final fica abaixo do baseline;
- arquivo fora do escopo é alterado;
- tasks são marcadas apesar do gate global falhar;
- relatório omite exit code ou falhas conhecidas;
- relatório contém dados sensíveis;
- SCOH-S2 é iniciado.

## Relatório corretivo obrigatório

Crie:

`/tmp/sirhosp-slice-SCOH-S1-R1-report.md`

Inclua:

- status exato;
- `BASE_REF` e git status inicial/final;
- matriz correção-arquivo-teste-inspeção;
- baseline com exit code e resumo completo;
- RED por C1-C7;
- GREEN e REFACTOR;
- snippets antes/depois de cada arquivo;
- lista de arquivos e justificativa;
- comparação dos 47 nomes com `mismatches=0`;
- prova SQL/teste das constraints nulas;
- prova do ramo concorrente;
- prova de leitura única;
- testes de limites e formato de data;
- inspeções obrigatórias interpretadas;
- baseline versus final;
- quality gate, Markdown direcionado, Markdown global e OpenSpec com exit codes;
- respostas aos critérios binários;
- riscos e pendências;
- comandos exatos para rerun;
- seção final `Handoff para verificador` com:
  - arquivos alterados;
  - commit/push ou motivo explícito para ausência;
  - checklist C1-C7;
  - comandos para terceiro LLM;
  - status das tasks;
  - confirmação de que SCOH-S2 não foi iniciado.

O relatório deve passar no Markdown lint direcionado e não conter dados de
pacientes.

## Prompt final pronto para execução

```text
Read AGENTS.md, PROJECT_CONTEXT.md, every artifact under
openspec/changes/add-versioned-sector-capacity-occupancy-history,
/tmp/sirhosp-slice-SCOH-S1-report.md,
/tmp/sirhosp-slice-SCOH-S1-verification.md and
/tmp/sirhosp-prompt-correct-SCOH-S1-R1.md completely.

Correct ONLY SCOH-S1 findings C1-C7. Do not implement SCOH-S2. Follow TDD:
official baseline, real RED for every correction, minimal GREEN and controlled
REFACTOR with clean code, DRY and YAGNI. Touch at most five implementation
files and never rewrite migration 0014; add migration 0015.

Run every inspection and gate. Generate
/tmp/sirhosp-slice-SCOH-S1-R1-report.md with objective evidence. If global
Markdown still fails only outside touched files, use status
CORRECTIONS_APPLIED_SLICE_INCOMPLETE_GLOBAL_MARKDOWN, leave tasks unchecked,
do not commit/push and stop for planner review. Only declare COMPLETE, mark
tasks and commit/push if every gate, including global Markdown, exits zero.

Reply with REPORT_PATH=/tmp/sirhosp-slice-SCOH-S1-R1-report.md and STOP.
```
