# MOQA-S2 — Catálogo v4 com aliases limpos por código-fonte

## Handoff para implementador com contexto zero

Você está no segundo de três slices do change
`make-occupancy-quality-actionable`. Comece sem assumir conversa anterior.

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. proposal, design, tasks e quatro delta specs deste change;
3. `slice-prompts/SLICE-MOQA-S1.md` e relatório
   `/tmp/sirhosp-slice-MOQA-S1-report.md`;
4. este arquivo;
5. `apps/census/models.py` e migrations até a criada em S1;
6. `apps/census/capacity_catalog.py`;
7. comando `activate_sector_capacity_catalog.py`;
8. os três JSONs existentes em `apps/census/data/`;
9. `tests/unit/test_sector_capacity_catalog.py`;
10. testes de catálogo em `tests/unit/test_occupancy_measurement.py`.

Pré-condições:

- S1 está commitado/pushed e tasks 1.1–1.6 marcadas;
- `occupancy-v4` já existe e funciona com catálogo sintético persistido;
- nenhuma UI v4 foi implementada;
- catálogos inicial, corrigido e v3 são imutáveis;
- membership atual preserva nome bruto em `configured_source_name`;
- publicação continua atômica, idempotente, estritamente futura e separada do
  deploy.

Objetivo: permitir que um catálogo de nova versão persista alias humano limpo
por membership, validar consistência por código e adicionar JSON integral v4
com dry-run 43/48/47/666/666 e cobertura completa de aliases. Não publicar nem
ativar catálogo em banco real.

## Protocolo obrigatório para DeepSeek4-Flash

Se qualquer item falhar, declare **INCOMPLETO**, não marque tasks e não faça
commit/push.

1. Matriz `Requisito → arquivo(s) → teste(s)/inspeção` antes de editar.
2. Registrar `BASE_REF`, árvore limpa e confirmar commit/relatório S1.
3. Rodar baseline `./scripts/test-in-container.sh unit` antes de editar, com
   exit 0, passed, zero failed/errors.
4. Criar testes RED primeiro; pelo menos um falha por alias/schema ausente.
5. GREEN mínimo sem tocar UI, algoritmo ou resumo diário.
6. REFACTOR com clean code, DRY, YAGNI; não duplicar validação de strings.
7. Executar todas as inspeções e interpretar resultados.
8. Rodar todos os gates oficiais em container e integração.
9. Final unitário: exit 0, zero failures/errors,
   `passed_final >= passed_baseline`.
10. Relatório completo com evidência, snippets e handoff.

## Objetivo vertical

Dado um documento integral schema novo declarando v4 e aliases:

- parser valida todo o documento;
- dry-run reporta algoritmo, totais e alias coverage sem escrita;
- publicação sintética persiste aliases atomically;
- aliases são temporais e imutáveis;
- catálogos antigos continuam válidos sem alias;
- artefatos antigos permanecem byte a byte inalterados.

## Requisitos funcionais

### R1 — Campo aditivo e histórico

Adicionar `source_display_name` a `CapacitySectorMembership`:

- nullable/blank somente para catálogos históricos;
- limite explícito coerente com demais nomes;
- migration aditiva, sem `RunPython`/backfill;
- `configured_source_name` permanece bruto e inalterado.

### R2 — Schema novo exige alias

Evoluir parser/validador para versão nova do schema, preferencialmente `3.0`:

- cada membership exige string não vazia `source_display_name`;
- trim/limite usam helper central;
- erro inclui caminho seguro do campo;
- schema 1.0/2.0 histórico continua aceito sem alias;
- schema novo continua exigindo algoritmo explícito suportado.

### R3 — Consistência por código

Quando o mesmo código aparece em memberships particionadas:

- alias deve ser exatamente o mesmo após normalização definida;
- aliases divergentes são rejeitados;
- 3A code `654` mantém um alias físico limpo, não dois aliases Adulto/Infantil;
- não misturar alias de fonte com `display_name` de grupo.

### R4 — Persistência e resultado

- publicação sintética copia alias para cada membership na transação existente;
- dry-run e resultado expõem somente contagem de aliases preenchidos, nunca
  detalhes clínicos;
- idempotência por hash/data permanece;
- falha em um alias não deixa versão parcial.

### R5 — Catálogo integral v4

Criar novo arquivo, sem editar anteriores, declarando:

- schema novo;
- `occupancy-v4`;
- 43 grupos;
- 48 memberships;
- 47 códigos distintos;
- 39 standard e 4 unrated;
- capacidades conhecida/calculável 666/666;
- CO unrated e 3A 32/16 inalterados;
- alias limpo em toda membership.

### R6 — Aliases curados

Não usar regex runtime. Exemplos mínimos obrigatórios no artefato/testes:

- `2702`: `Enfermaria Gastroenterologia`;
- `654`: `Enfermaria 3A Obstetrícia Clínica` em ambas memberships;
- `719`: `Cardioclínica`;
- `2156`: `Enfermaria 2B Cardio`;
- CO: aliases específicos e limpos para Centro Obstétrico, observação
  ginecológica, medicação, estabilização RN e internação;
- demais códigos: nome humano sem prefixo técnico de localização e sem sufixo
  hospitalar redundante.

Acentuação pode ser corrigida no alias sem alterar nome bruto.

### R7 — Compatibilidade histórica

- JSON inicial, corrigido e v3 não podem ser editados;
- models históricos mantêm alias nulo;
- parsing de documentos antigos mantém o mesmo hash/resultado;
- não criar fallback que modifique banco;
- alias histórico de apresentação será responsabilidade de S3.

### R8 — Ativação continua separada

- comando aceita dry-run v4 futuro;
- este slice não executa publicação operacional;
- não adicionar data hardcoded, auto-activation, signal, migration de dados ou
  startup hook;
- activation real fica nas tasks 4.5–4.6.

## Arquivos esperados e limite rígido

Máximo: **5 arquivos**:

1. `apps/census/models.py`;
2. `apps/census/migrations/0023_*.py`;
3. `apps/census/capacity_catalog.py`;
4. `apps/census/data/sector_capacity_catalog_v4.json`;
5. `tests/unit/test_sector_capacity_catalog.py`.

Se migration tiver outro número legítimo, explicar. Não alterar comando se o
serviço compartilhado já atende; se mudança no comando for indispensável,
pare como bloqueado porque excederia limite e proponha substituição explícita,
não um sexto arquivo silencioso.

## Fora de escopo

Não alterar:

- `apps/census/occupancy.py` ou semântica S1;
- `apps/census/views.py`, template, URLs, CSS;
- testes de `/beds`;
- serviços clínicos, ingestão ou Playwright;
- catálogos JSON existentes;
- ADRs e release docs;
- migrations anteriores ou dados publicados.

Não instalar dependências.

## TDD obrigatório

### RED

Adicionar primeiro testes para:

1. schema novo sem alias falha;
2. alias whitespace falha;
3. alias acima do limite falha com path;
4. aliases divergentes no mesmo código particionado falham;
5. schema v2 antigo sem alias continua válido;
6. publicação sintética persiste alias;
7. dry-run reporta cobertura completa sem escrita;
8. v4 JSON tem 43/48/47/39/4/666/666;
9. exemplos curados de Gastro, 3A, Cardio e CO;
10. aliases não têm padrões técnicos aprovados como proibidos;
11. JSONs antigos mantêm SHA-256/bytes esperados;
12. algoritmo desconhecido continua rejeitado;
13. idempotência/atomicidade continuam verdes.

Executar `./scripts/test-in-container.sh unit` e registrar RED funcional.

### GREEN

Implementar o mínimo para parser, persistência, migration e artefato passarem.
Não antecipar unidades de apresentação.

### REFACTOR

- reutilizar validação de path/string/limite;
- manter dataclasses imutáveis de documento;
- não criar camada genérica de schema registry;
- ordenar JSON conforme padrão existente;
- manter aliases curados explícitos e revisáveis;
- não inferir alias do nome bruto.

## Checks de inspeção obrigatórios

```bash
rg -n "source_display_name|configured_source_name|schema_version|occupancy-v4" \
  apps/census/models.py apps/census/capacity_catalog.py \
  apps/census/data/sector_capacity_catalog_v4.json
rg -n '"source_code": "654"|"source_code": "719"|"source_code": "2156"' \
  apps/census/data/sector_capacity_catalog_v4.json
rg -n '0 T|[1-4] [6-8] -| - HGRS|sistema legado' \
  apps/census/data/sector_capacity_catalog_v4.json
rg -n "RunPython|RemoveField|DeleteModel" apps/census/migrations/0023_*.py
rg -n "effective_from.*2026|timezone\.localdate\(\).*occupancy-v4|post_migrate|ready\(" \
  apps/census
sha256sum apps/census/data/initial_sector_capacity_catalog.json \
  apps/census/data/corrected_sector_capacity_catalog.json \
  apps/census/data/sector_capacity_catalog_v3.json
rg -n "source_display_name|occupancy-v4|dry-run|idempoten" \
  tests/unit/test_sector_capacity_catalog.py
```

Interpretação:

- padrões técnicos podem permanecer em `configured_source_name`, mas não em
  aliases; inspeção JSON deve distinguir os campos, não apenas contar matches;
- ausência de auto-activation é obrigatória;
- hashes antigos devem coincidir com baseline pré-edição;
- migration é aditiva, sem backfill.

Executar dry-run somente em ambiente de teste/container conforme fixtures; não
usar produção:

```bash
./scripts/test-in-container.sh unit
```

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

- [ ] S1 confirmado completo e baseline S2 verde.
- [ ] RED real de alias/schema ausente.
- [ ] Campo/migration aditivos sem backfill.
- [ ] Schema novo exige alias e algoritmo.
- [ ] Alias particionado é consistente por código.
- [ ] Histórico aceita ausência sem ser editado.
- [ ] JSON v4 integral mantém 43/48/47/39/4/666/666.
- [ ] Aliases curados cobrem 100% das memberships.
- [ ] CO, 3A, Cardio e exemplos aprovados testados.
- [ ] Dry-run não escreve e reporta alias coverage.
- [ ] Três JSONs anteriores byte-preservados.
- [ ] Nenhuma ativação operacional executada.
- [ ] Todos gates/inspeções verdes.
- [ ] Máximo cinco arquivos.
- [ ] Relatório completo criado.

## Gates de autoavaliação

1. Por que `display_name` de grupo não substitui alias de código-fonte?
2. Como 3A garante um alias físico entre duas memberships?
3. Quais padrões técnicos foram removidos apenas dos aliases?
4. Qual fallback mantém catálogos antigos sem editar rows?
5. Como dry-run prova ausência de escrita?
6. Quais hashes comprovam preservação dos JSONs anteriores?
7. Como falha de alias mantém atomicidade?
8. Onde se prova que nenhuma data ativa v4 automaticamente?
9. Quais totais do documento foram conferidos?
10. Houve arquivo extra ou antecipação da UI?

### Condições automáticas de INCOMPLETO

- S1 incompleto ou baseline falho/ausente;
- RED ausente ou causado por erro incidental;
- qualquer gate/integração/lint/typecheck falhar;
- final com failure/error, exit não zero ou regressão de passed;
- alias inferido por regex do nome bruto;
- schema novo aceitar alias vazio/divergente;
- documento antigo exigir alias retroativamente;
- JSON anterior alterado;
- totais v4 divergirem de 43/48/47/39/4/666/666;
- publicação/ativação real executada;
- migration com backfill/destruição;
- UI, occupancy ou serviço clínico alterado;
- mais de cinco arquivos;
- task marcada sem relatório/evidência.

## Relatório obrigatório

Criar:

```text
/tmp/sirhosp-slice-MOQA-S2-report.md
```

Incluir status, BASE_REF, matriz R1–R8, baseline, RED/GREEN, arquivos, snippets
antes/depois, migration, tabela código→alias dos casos críticos sem dados de
paciente, hashes antigos antes/depois, totais/dry-run, inspeções interpretadas,
todos gates, comparação pytest, autoavaliação, riscos, rerun e `Handoff para
verificador` com checklist R1–R8.

Só após tudo passar, marcar 2.1–2.5, commit/push, responder
`REPORT_PATH=/tmp/sirhosp-slice-MOQA-S2-report.md` e parar.

## Prompt pronto para implementador LLM

```text
Read AGENTS.md, PROJECT_CONTEXT.md and all artifacts in
openspec/changes/make-occupancy-quality-actionable, especially
slice-prompts/SLICE-MOQA-S2.md and the S1 report. Assume zero context.

Implement ONLY MOQA-S2 with the DeepSeek4-Flash protocol: clean baseline, real
TDD RED, minimal GREEN, controlled REFACTOR, mandatory inspections, full
official container gates and baseline-vs-final evidence. Apply clean code, DRY
and YAGNI. Touch at most the five allowed files. Add only the additive source
alias model/schema/parser/persistence and integral v4 JSON. Do not touch
occupancy semantics, UI, ADR, old JSONs, clinical services, release or perform
activation/publication.

If any test/check/gate fails or is omitted, old artifact changes, alias is
heuristically inferred, totals drift, migration backfills, file limit is
exceeded or privacy/atomicity is uncertain, report INCOMPLETE; do not mark tasks
or commit/push.

Create /tmp/sirhosp-slice-MOQA-S2-report.md with RED/GREEN, snippets for every
file, hashes, migration/dry-run evidence, gates, rerun commands, self-review and
Handoff para verificador. Mark only 2.1-2.5 after all criteria pass. Commit,
push, reply with REPORT_PATH and STOP.
```
