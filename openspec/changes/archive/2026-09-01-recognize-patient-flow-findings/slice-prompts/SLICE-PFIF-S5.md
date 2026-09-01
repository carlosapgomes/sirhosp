# PFIF-S5 — Métricas, health e operação

## Handoff para implementador LLM com contexto zero

Leia integralmente:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change;
2. relatórios COMPLETE PFIF-S1–S4 e diffs verificados;
3. enums/stage outcome de S1/S2 e classificador S3;
4. `apps/ingestion/pipeline_health.py` e command
   `check_ingestion_pipeline_health.py`;
5. testes unitários do health check e contratos de saída agregada;
6. `apps/services_portal/views.py`, especialmente
   `_get_latest_batch_failure_stats`, batch history/detail e filtros;
7. `apps/services_portal/templates/services_portal/ingestion_metrics.html`;
8. testes da aba patients, batch history, auth e privacidade;
9. seção de health/rollout em `deploy/README.md` e runbooks RC recentes apenas
   para seguir formato, nunca para copiar dados reais.

Pré-condição: pipeline e três páginas estão completos. Este slice não muda
regras, runs, batch status ou findings; apenas health, apresentação agregada e
runbook. É o último slice. Não arquive nem faça deploy.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Qualquer item ausente/falho implica INCOMPLETE, sem task/commit/push.

1. Registre BASE_REF, árvore limpa, S1–S4 verificados e matriz requisito→arquivo→teste.
2. Rode baselines oficiais unit e integration, com exit e resumos; falha bloqueia.
3. RED primeiro para health allowlist/forgery, portal succeeded-with-findings,
   partial failure, timeout preservado, auth e saída sanitizada.
4. GREEN mínimo em no máximo seis arquivos.
5. REFACTOR local clean/DRY/YAGNI; uma função compartilhada pode reconhecer
   stage outcome, mas não crie engine/framework.
6. Inspeções, todos os gates, OpenSpec strict e markdown lint.
7. Unit/integration finais exit zero, zero failures/errors e passed >= baseline.
8. Relatório final evidencial, revisão do diff integral e handoff para terceiro.

## Objetivo vertical

Um batch sintético com admissions vazias reconhecidas aparece como `Concluído
com achados` e health saudável; um batch com achados + timeout aparece `Falha
parcial`, conta finding e timeout separadamente; sucesso vazio sem stage exato
continua unhealthy. Tudo é agregado e read-only.

## Requisitos funcionais

### R1 — Health aceita somente outcome exato

Em `pipeline_health.py`, excluir de `empty_success` apenas run batch-bound
`succeeded`, `admissions_seen=0` que possua stage `encounter_fallback` succeeded
com outcome e recency allowlisted exatos de S1. Wrong stage, unknown code,
`boundary`, `stale`, details parcial/forjado ou stage failed continuam anomalia.

### R2 — Métrica reconhecida agregada

Adicionar contador `recognized_recent_encounter` (nome final consistente com
spec) ao result DTO e output command. O comando continua one-shot/read-only e
não imprime run/batch/patient/date. Recognized empty não gera
`missing_full_sync`; admissions non-empty continua exigindo follow-up.

### R3 — Batch presentation derivada

No portal:

- raw `succeeded` + finding >0 => `Concluído com achados`;
- raw `failed` + finding >0 + technical failures >0 => `Falha parcial`;
- sem findings => apresentação antiga.

Não alterar `CensusExecutionBatch.status`, choices, migration ou histórico.
Finding counts vêm de outcomes allowlisted do batch. Technical failures vêm dos
runs/final failures existentes.

### R4 — Eixos e filtros preservados

Mostrar cards/linhas separados por findings allowlisted e falhas técnicas.
Timeout/invalid/unexpected continuam contados mesmo que classificador atual
encontre residual/recent. Filtros de run/batch e página patients permanecem.
Não listar patient record no novo resumo; tabela já autorizada existente não
deve ganhar novo dado sensível.

### R5 — Empty states e autorização

Sem batch/finding usa defaults completos e não quebra template. Anonymous
continua redirect. Nenhum query N+1 por finding; agregação no DB ou bounded.

### R6 — Runbook canário

Atualizar `deploy/README.md` com procedimento somente agregado:

- baseline 24h antes do rollout;
- um worker canário e um ciclo completo;
- avanço: recognized sobe, `empty_success=0`, admissions invalid_payload cai,
  timeout/fila não pioram e logs sanitizados;
- parada: empty_success, unknown outcome, timeout/fila crescente, output
  sensível ou sessão instável;
- rollback de imagem sem reescrever runs/stages;
- proibição de requeue/backfill/reclassificação manual durante canário.

Comandos devem usar compose/runtime oficial e placeholders, nunca valores/IDs
reais.

### R7 — Revisão final de privacidade

Testes injetam sentinelas de record/name/professional/URL/HTML/cookie/password e
provam ausência em command output, derived cards e exceptions. Relatório não
copia dados da investigação.

## Arquivos esperados e limite

Máximo de **6 arquivos**, além de `tasks.md`:

1. `apps/ingestion/pipeline_health.py`;
2. `apps/ingestion/management/commands/check_ingestion_pipeline_health.py`;
3. `apps/services_portal/views.py`;
4. `apps/services_portal/templates/services_portal/ingestion_metrics.html`;
5. `tests/integration/test_patient_flow_findings_observability.py` (novo
   consolidado para health command/service + portal);
6. `deploy/README.md`.

Não editar models/migrations/status choices, classificador, extraction,
`/censo`, `/beds`, admissions, URLs, systemd units ou dependências. Se testes
existentes exigirem quinto/sexto arquivo diferente, pare e peça emenda; não
exceda.

## TDD obrigatório

### RED

1. exact recent outcome: health healthy, recognized=1, empty_success=0,
   missing_full_sync=0;
2. cada forgery/partial/wrong stage/recency: unhealthy empty_success=1;
3. non-empty sem full-sync continua missing;
4. command stdout agregado contém recognized e nenhuma sentinela;
5. succeeded batch + finding => derived label e counts;
6. failed batch + finding + timeout => partial, counts separados;
7. timeout continua nos reasons/filtros;
8. batch sem finding mantém label antigo;
9. no batch usa defaults;
10. anonymous redirect;
11. query behavior bounded;
12. runbook contém avanço/parada/rollback e nenhuma sequência de identificação.

Pelo menos um RED health e um RED portal.

### GREEN

Implementar R1–R7 sem mutação de estado e sem usar classificador clínico para
reescrever história.

### REFACTOR

Centralizar reconhecimento exato se evitar divergência health/portal dentro do
limite; não criar model, status, repository ou generic telemetry framework.

## Checks de inspeção obrigatórios

```bash
rg -n "recognized_recent|empty_success|missing_full_sync|encounter_fallback|recent_confirmed" \
  apps/ingestion/pipeline_health.py \
  apps/ingestion/management/commands/check_ingestion_pipeline_health.py
rg -n "Concluído com achados|Falha parcial|finding|technical" \
  apps/services_portal/views.py \
  apps/services_portal/templates/services_portal/ingestion_metrics.html
rg -n "CensusExecutionBatch.*status|status *=|STATUS_CHOICES|migration" \
  apps/services_portal/views.py apps/ingestion/pipeline_health.py
rg -n "record|patient|professional|profissional|cookie|password|html|url" \
  tests/integration/test_patient_flow_findings_observability.py
rg -n "canário|baseline|avanço|parada|rollback|requeue|backfill" deploy/README.md
rg -n "markdownlint-disable" \
  openspec/changes/recognize-patient-flow-findings deploy/README.md
git diff --check
git diff --stat
```

Interprete: stage allowlist exata, nenhum status save/update, eixos separados,
output novo agregado, sentinelas apenas em testes com asserção de ausência e
runbook sem PHI. Proibido silenciar markdownlint.

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

Após marcar somente 5.x, rode markdown lint novamente. Não marcar 6.x; a
verificação final pertence ao planner/verificador.

## Critérios binários de sucesso

- [ ] S1–S4 verificados e inalterados fora do consumo necessário.
- [ ] R1–R7 RED/GREEN.
- [ ] Somente exact allowlist exclui empty_success.
- [ ] Recognized vazio não exige full-sync; non-empty continua exigindo.
- [ ] Derived labels sem status/migration/historical rewrite.
- [ ] Findings e timeout técnicos separados.
- [ ] Defaults/auth/query behavior preservados.
- [ ] Runbook tem canário/stop/rollback agregados.
- [ ] Privacidade por sentinelas e diff integral.
- [ ] Máximo seis arquivos + tasks.
- [ ] Gates e baselines finais verdes.

### Condições automáticas de INCOMPLETO

S1–S4 não verificados; baseline/RED/gate ausente; health aceita unknown/boundary;
recognized vazio exige full-sync; non-empty deixa de exigir; batch status/model/
migration é alterado; timeout some; portal mistura findings/falhas; output novo
lista identidade/data/profissional; auth relaxa; N+1; runbook sem stop/rollback
ou com comando mutante; markdown lint silenciado/falho; arquivo extra; teste
removido/enfraquecido; relatório/tasks incorretos; deploy/legacy acessado.

## Gates de autoavaliação

1. Qual matriz prova allowlist exata versus forgery?
2. Como missing_full_sync diferencia vazio reconhecido de non-empty?
3. Onde se prova que status persistido não foi salvo/alterado?
4. Qual teste mantém timeout ao lado de finding?
5. Como no-batch/auth/query defaults foram preservados?
6. Quais critérios objetivos governam canário e rollback?
7. Qual varredura prova ausência de dados sensíveis?
8. Por que cada arquivo alterado é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-PFIF-S5-report.md` com:

- Status, BASE_REF, provas S1–S4 e matriz;
- baselines unit/integration com exit/resumos;
- RED/GREEN e matriz allowlist/forgery;
- snippets antes/depois de cada arquivo, incluindo `tasks.md` e runbook;
- outputs agregados sintéticos e prova de sentinelas ausentes;
- inspeções e interpretação;
- unit/integration finais versus baseline;
- todos os gates, OpenSpec strict e markdown lint;
- revisão do diff integral, arquivos/justificativa, riscos e respostas;
- comandos exatos de rerun;
- `Handoff para verificador` com checklist R1–R7, critérios de canário e
  confirmação explícita de que produção/legado não foram acessados.

Somente `Status: COMPLETE` com toda evidência. Não marcar tarefas 6.x, arquivar,
fazer deploy ou executar canário.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full recognize-patient-flow-findings change, verified PFIF-S1..S4 reports and SLICE-PFIF-S5.md. Implement ONLY PFIF-S5. Follow the DeepSeek4-Flash protocol with clean official unit/integration baselines, real RED for exact health allowlist and portal derived states, minimal GREEN, local clean-code/DRY/YAGNI refactor, privacy sentinels, inspections, all official gates, OpenSpec strict and markdown lint. Separate aggregate findings from technical failures without changing persisted run/batch status; preserve timeout and fail closed on forged/boundary outcomes. Update only the aggregate canary/rollback runbook, never access production/legacy. Touch at most six listed files plus tasks. Create /tmp/sirhosp-slice-PFIF-S5-report.md with per-file before/after and verifier handoff. Missing/failing means INCOMPLETE without tasks/commit. If complete mark only 5.1–5.5, commit, push, reply REPORT_PATH=..., then STOP; do not mark final verification or archive.
```
