# PFIF-S2 — Paridade do worker clássico

> **Status de governança: INCOMPLETE após verificação independente.** O commit
> `829afd5` não clicou `Atendimentos` antes de ler sua tabela e solicitou o
> sidecar também para standalone. O relatório original `Status: COMPLETE` foi
> reprovado e não autoriza S3. Não reexecute este prompt nem marque 2.x com base
> nele; implemente `SLICE-PFIF-S2R.md` e aguarde nova verificação.

## Handoff para implementador LLM com contexto zero

Leia integralmente antes de editar:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change
   `recognize-patient-flow-findings`;
2. `slice-prompts/SLICE-PFIF-S1.md`, relatório COMPLETE em
   `/tmp/sirhosp-slice-PFIF-S1-report.md` e diff/commit verificado de S1;
3. o contrato enriquecido e enums entregues por S1;
4. `automation/source_system/medical_evolution/path2.py`, especialmente CLI,
   admissions-only, `read_internacoes_rows`, outputs e cleanup;
5. `apps/ingestion/extractors/playwright_extractor.py`, método
   `get_admission_snapshot`, subprocess, tmpdir e parser;
6. `_process_admissions_only` no worker clássico, erros, attempts, stages,
   follow-ups e batch closure;
7. testes `test_evolution_extractor.py`, paridade current/persistent e fixtures
   subprocess sintéticas.

Pré-condição: S1 está implementado e verificado. O worker persistente já produz
o outcome recente. O worker clássico ainda usa `path2.py --admissions-only` e
lista JSON. Este slice fecha a paridade sem alterar o output de admissions
existente e sem implantar nada em produção. Não implemente classificador/UI.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer item falhar, `Status: INCOMPLETE`, sem task/commit/push.

1. Registre BASE_REF, árvore limpa, verificação S1 e matriz requisito→arquivo→teste.
2. Rode baseline oficial `./scripts/test-in-container.sh unit`; falha bloqueia.
3. RED primeiro: matriz current/persistent deve falhar pela ausência do fallback
   clássico; saída opcional do subprocess deve ter teste falhando funcional.
4. GREEN mínimo nos arquivos permitidos; não refatore `path2.py` amplamente.
5. REFACTOR local com clean code, DRY, YAGNI; reutilize contrato/enums S1.
6. Inspeções e todos os gates oficiais obrigatórios.
7. Unit final exit 0, zero failures/errors e passed >= baseline.
8. Relatório reproduzível e handoff para terceiro verificador.

## Objetivo vertical

Dadas as mesmas fixtures sintéticas de admissions vazias e atendimentos, os
workers clássico e persistente terminam com os mesmos status, counters, stages,
follow-ups e batch outcome para recência recente ou não recente. O JSON/lista de
admissions consumido por integrações existentes permanece compatível.

## Requisitos funcionais

### R1 — Saída lateral opcional em `path2.py`

No modo admissions-only, após lista vazia e somente quando explicitamente
solicitado pelo caller, navegar a `Atendimentos` na mesma página/sessão usando a
mesma estrutura confirmada em S1. Escrever um artefato temporário mínimo no
contrato S1 ou equivalente compatível. O arquivo de admissions existente
continua uma lista JSON inalterada.

Não consultar atendimentos para snapshot não vazio nem sem opção explícita. Não
abrir novo browser/login/subprocess dentro do script.

### R2 — PlaywrightExtractor retorna o contrato compartilhado

Adicionar API enriquecida no extractor clássico, invocando o subprocess uma
única vez e lendo admissions + sidecar opcional do tmpdir. A API antiga
`get_admission_snapshot` continua retornando lista e preserva timeouts/erros.
Ausência/malformação do sidecar quando necessário falha sanitizada; nenhum
preview bruto entra em mensagem.

### R3 — Worker clássico reconhece somente recente confirmado

Aplicar no `_process_admissions_only` clássico a mesma decisão e os mesmos
códigos/stages de S1. Hoje/ontem batch-bound vazio sucede com counters zero,
sem persistência/full-sync/demografia extra; boundary/stale/none preservam
`EmptyAdmissionsSnapshotError`. Full-sync e standalone permanecem.

### R4 — Paridade observável

Testar current versus persistent para:

- recent_confirmed;
- boundary, stale e none;
- admissions não vazias;
- standalone vazio;
- erro de navegação/sidecar;
- counters, attempts, stages/details, cleanup, follow-ups e batch closure.

Diferenças internas de browser/subprocess são permitidas; resultado externo não.

### R5 — Privacidade e compatibilidade CLI

Nenhum stdout/stderr/error/artefato de teste inclui dado real. O sidecar vive em
tmpdir e é apagado pelo lifecycle existente. CLI sem a nova opção preserva
comportamento. Não salvar screenshot/HTML nem profissional.

## Arquivos esperados e limite

Máximo de **5 arquivos**, além de `tasks.md`:

1. `automation/source_system/medical_evolution/path2.py`;
2. `apps/ingestion/extractors/playwright_extractor.py`;
3. `apps/ingestion/management/commands/process_ingestion_runs.py`;
4. `tests/unit/test_current_vs_persistent_encounter_parity.py` (novo);
5. `tests/unit/test_evolution_extractor.py`, somente se fixtures/subprocess
   públicos exigirem regressão adicional.

Não editar arquivos S1, models, migrations, views, templates, health, métricas
ou docs. Se a API S1 não comportar paridade sem edição, pare e reporte bloqueio
ao planner; não altere S1 silenciosamente.

## TDD obrigatório

### RED

1. parser/sidecar sintético com datas fora de ordem e inválidas;
2. `path2.py` vazio+opção chama Atendimentos; não vazio/sem opção não chama;
3. admissions-output continua lista JSON byte/shape compatível;
4. extractor inicia um subprocess, lê dois resultados e limpa tmpdir;
5. sidecar ausente/malformado falha sanitizada;
6. matriz current/persistent recente e não recente completa;
7. zero persistência/follow-up/counters no recente;
8. sentinelas de PHI/segredo ausentes em outputs.

Pelo menos um RED deve mostrar divergência current/persistent atual.

### GREEN

Implemente R1–R5 usando o contrato S1, subprocess único e menor opção CLI.

### REFACTOR

Evite duplicar recency/parser S1. Não reestruture extração de evoluções, chunks,
PDF ou login. Não introduza nova intent/queue.

## Checks de inspeção obrigatórios

```bash
rg -n "admissions-only|admissions-output|Atendimentos|encounter" \
  automation/source_system/medical_evolution/path2.py
rg -n "get_admission_snapshot|patient_flow|subprocess|TemporaryDirectory" \
  apps/ingestion/extractors/playwright_extractor.py
rg -n "encounter_fallback|recent_confirmed|EmptyAdmissionsSnapshotError|persist_admissions_snapshot" \
  apps/ingestion/management/commands/process_ingestion_runs.py
rg -n "current|persistent|boundary|stale|standalone|non.empty|sidecar" \
  tests/unit/test_current_vs_persistent_encounter_parity.py \
  tests/unit/test_evolution_extractor.py
rg -n "professional|profissional|cookie|password|html|screenshot" \
  automation/source_system/medical_evolution/path2.py \
  apps/ingestion/extractors/playwright_extractor.py
git diff --check
git diff --stat
```

Interprete no relatório: confirme subprocess único, output admissions antigo
preservado, fallback condicional, mesma decisão de S1 e ausência de raw preview.
Ocorrências históricas não relacionadas em `path2.py` devem ser explicadas; não
faça limpeza fora do slice.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate recognize-patient-flow-findings --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] S1 verificado e não alterado.
- [ ] R1–R5 cobertos RED/GREEN.
- [ ] Admissions-output antigo permanece lista compatível.
- [ ] Um subprocess/login/browser por job, sem fallback para não vazio.
- [ ] Current/persistent equivalentes em todos os cenários exigidos.
- [ ] Recente tem zero efeito clínico/follow-up; não recente falha fechado.
- [ ] Sem acesso real/dado sensível.
- [ ] Máximo cinco arquivos + tasks.
- [ ] Gates exit zero e unit final >= baseline sem failures/errors.

### Condições automáticas de INCOMPLETO

S1 ausente/não verificado/alterado; baseline/RED/gate ausente; output antigo
muda de lista para objeto; segundo subprocess/browser/login é criado; fallback
roda para não vazio/standalone/full-sync; paridade compara apenas status e ignora
efeitos; recency é reimplementada divergentemente; sidecar persiste fora de
tmpdir; raw stderr/HTML/PHI aparece; teste antigo é removido/enfraquecido; arquivo
extra é tocado; relatório ausente; tasks marcadas prematuramente.

## Gates de autoavaliação

1. Qual teste prova compatibilidade do admissions-output?
2. Qual teste conta subprocess/browser uma vez?
3. Onde está a matriz completa current/persistent?
4. Como o clássico reutiliza os enums/recency de S1?
5. Qual teste nega persistência e follow-up no recente?
6. Como sidecar e erros são sanitizados?
7. Por que cada arquivo alterado é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-PFIF-S2-report.md` com Status, BASE_REF, prova S1,
matriz, baseline unit, RED/GREEN, snippets antes/depois por arquivo, compatibilidade
CLI/JSON, matriz de paridade, inspeções e interpretação, unit baseline/final,
todos os gates, arquivos/justificativa, riscos, respostas e `Handoff para
verificador` R1–R5 com comandos exatos para rerun. Sem dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full recognize-patient-flow-findings change, verified PFIF-S1 report/diff and SLICE-PFIF-S2.md. Implement ONLY PFIF-S2. Follow the DeepSeek4-Flash protocol: clean baseline, requirement matrix, real RED showing current/persistent divergence, minimal GREEN, clean-code/DRY/YAGNI refactor, inspections and every official container gate. Extend the classic path with one optional synthetic encounter sidecar while preserving the existing admissions list output and one subprocess/browser/login. Reuse S1 contract and make external outcomes equivalent; do not edit S1 files or implement UI/health/metrics. Touch at most five listed files plus tasks. Create /tmp/sirhosp-slice-PFIF-S2-report.md with parity evidence and verifier handoff. Missing/failing evidence means INCOMPLETE without task mark/commit. If complete, mark only 2.1–2.5, commit, push, reply REPORT_PATH=..., then STOP.
```
