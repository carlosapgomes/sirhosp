# FX-S1 — Retry por classe de falha: fail-fast de payload determinístico

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md` (raiz do repo);
2. `docs/adr/ADR-0008-fullsync-failure-characterization-decision.md`
   (causa comprovada que este change corrige);
3. o change atual: `proposal.md`, `design.md` (seção **D1**),
   `specs/fullsync-failure-exhaustion-fix/spec.md`, `tasks.md`;
4. `apps/ingestion/run_lifecycle.py` (taxonomia `classify_failure_reason`,
   `safe_error_message`, `record_final_run_failure`);
5. `apps/ingestion/models.py`: `IngestionRun` (`attempt_count`,
   `max_attempts` default 3, `next_retry_at`), `IngestionRunAttempt`,
   `FinalRunFailure`;
6. `_mark_run_failed` em
   `apps/ingestion/management/commands/process_ingestion_runs.py` e em
   `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
   (dois workers; produção usa o persistente; ambos precisam da correção);
7. testes existentes dos workers em `tests/unit/` (padrão de fixtures e
   chamada de `_mark_run_failed`).

Estado atual: qualquer falha de execução é reenfileirada enquanto
`attempt_count < max_attempts` (+60s), sem distinguir falha determinística
(`invalid_payload`) de transitória (`timeout`). Em produção isso queima
centenas de tentativas/semana nos 23 pacientes da coorte fail-only
(evidência na ADR-0008). Este slice NÃO muda taxonomia, backoff, mensagens
persistidas nem contratos do health check/characterização.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Este slice será implementado por um modelo rápido com tendência a concluir
cedo demais. Siga literalmente. **Se qualquer item falhar, o slice está
INCOMPLETO**: não marque `tasks.md`, não faça commit/push, responda com
bloqueio + evidência.

1. **Plano antes de editar**: matriz `Requisito → arquivo(s) → teste(s)` no
   relatório. Sem requisito sem teste.
2. **Baseline antes de editar**: `BASE_REF=$(git rev-parse HEAD)`; árvore
   limpa; rode `./scripts/test-in-container.sh unit` e registre exit code +
   resumo (`passed/failed/errors`). Falha/error no baseline → pare e
   reporte BLOQUEADO.
3. **RED real**: escreva os testes primeiro; rode o subconjunto alvo; pelo
   menos um teste novo deve falhar pelo motivo esperado (não por erro de
   import). Teste que passa antes da implementação não prova nada —
   ajuste-o.
4. **GREEN mínimo**: somente o necessário; sem refactor amplo; sem
   antecipar FX-S2/S3/S4.
5. **Inspeções obrigatórias**: rode os `rg` deste slice e interprete cada
   resultado no relatório.
6. **Gate completo**: `./scripts/test-in-container.sh check`, `unit`,
   `lint`, `typecheck` (+ `quality-gate`). Unit final exit 0, zero
   failures/errors, `passed >= baseline`.
7. **Relatório com evidência**: comandos, exit codes, resumos
   baseline/final, RED/GREEN, snippets antes/depois, respostas aos gates,
   `Handoff para verificador`. `Status: COMPLETE` só com tudo comprovado.

## Objetivo do slice (fluxo end-to-end)

Um run cuja tentativa falha com reason `invalid_payload` (validação
determinística de payload) termina **fail-fast na primeira tentativa**:
não é reenfileirado, registra `FinalRunFailure`, fecha o batch e loga
linha sanitizada distinta. Um run que falha com `timeout` continua no
comportamento atual (requeue +60s enquanto houver tentativas). A decisão
vem de uma única função pura compartilhada pelos dois workers.

## Contexto técnico atual

- `_mark_run_failed(run, exc)` em cada worker: classifica
  (`classify_failure_reason`), atualiza a `IngestionRunAttempt` aberta,
  decide retry pela guarda `if run.attempt_count < run.max_attempts:` e,
  no ramo terminal, persiste run `failed`, chama `record_final_run_failure`
  e fecha o batch.
- `run_lifecycle.py` é o lar DRY da taxonomia/política (importado pelos
  dois workers) — é lá que a política de retry por reason deve viver.
- `FinalRunFailure.attempts_exhausted` já reflete `attempt_count` no
  momento terminal (passará a ser 1 nos fail-fast — comportamento
  correto).

## Escopo funcional

- **R1 — Política pura:** nova função em `run_lifecycle.py`
  (`should_retry_failure_reason(failure_reason: str) -> bool`):
  `invalid_payload` → `False`; qualquer outro reason (incluindo `timeout`
  e vazio) → `True`. Constante interna para o conjunto determinístico
  (inicialmente `{"invalid_payload"}`).
- **R2 — Guarda nos dois workers:** `_mark_run_failed` de
  `process_ingestion_runs` e de
  `process_ingestion_runs_persistent_session` decide requeue por
  `attempt_count < max_attempts and should_retry_failure_reason(reason)`;
  o ramo terminal existente é reutilizado sem duplicação (fail-fast cai no
  mesmo terminal: `FinalRunFailure` + fechamento de batch + campos
  persistidos idênticos).
- **R3 — Log sanitizado distinto:** no fail-fast, linha de log
  agregada-only (label do run + reason; nada de `str(exc)`), distinguível
  da linha de requeue (ex.: `failed deterministically
  (reason=invalid_payload), fail-fast`).
- **R4 — Regressão preservada:** `timeout` mantém requeue +60s com
  `next_retry_at`; ciclo de attempt (`IngestionRunAttempt`), mensagens
  `safe_error_message` e taxonomia inalterados; batch-bound vazio
  (RPAP-S2, `invalid_payload`) também fail-fasta — é o comportamento
  correto e deve ter teste próprio.

## Arquivos esperados (limite 4, além de `tasks.md`)

1. `apps/ingestion/run_lifecycle.py` (função + constante);
2. `apps/ingestion/management/commands/process_ingestion_runs.py`
   (guarda e log);
3. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
   (guarda e log);
4. `tests/unit/test_retry_policy_by_reason.py` (novo — política pura +
   `_mark_run_failed` dos dois workers).

Proibido: models, migrations, adapter/extractors, health check,
characterization, runbook, `FinalRunFailure` helper, novos alertas. Arquivo
extra exige justificativa no relatório (aceite só se impossível evitar).

## TDD obrigatório

### RED mínimo (todos devem falhar antes da implementação)

1. política pura: `invalid_payload` → False; `timeout`/`navigation`/vazio
   → True;
2. worker persistente `_mark_run_failed` com exc
   `InvalidJsonError` (reason `invalid_payload`) na 1ª tentativa
   (`attempt_count=1`, `max_attempts=3`): run **terminal `failed`** (não
   `queued`), `next_retry_at is None`, `FinalRunFailure` criada com
   `attempts_exhausted=1`, batch sem runs pendentes fecha;
3. worker persistente com `EvolutionPdfTimeoutError`: **requeue**
   (`status=queued`, `next_retry_at=now+60s`, sem `FinalRunFailure`) —
   regressão do comportamento atual;
4. worker clássico `_mark_run_failed`: os mesmos dois casos;
5. `attempt_count == max_attempts` com reason retryável: terminal
   (inalterado);
6. log fail-fast sanitizado: linha contém `fail-fast`/`deterministic` e o
   reason; NÃO contém `str(exc)` nem sentinelas de identidade (seed
   sentinela no exc para provar).

### GREEN

Implementar R1–R3 minimamente; sem tocar em persistência existente além da
guarda.

### REFACTOR

Clean code/DRY/YAGNI: guarda única por worker; sem branches duplicados do
ramo terminal; nomes explícitos; sem flag/mágica; sem `except Exception`
novo.

## Checks de inspeção obrigatórios

```bash
rg -n "should_retry_failure_reason" apps/ingestion/run_lifecycle.py \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "attempt_count < .*max_attempts" apps/ingestion/management/commands/
rg -n "fail-fast|deterministic" apps/ingestion/management/commands/
rg -n "invalid_payload" apps/ingestion/run_lifecycle.py
```

Interprete: os dois workers devem conter a guarda combinada com a função
pura (nenhuma comparação de reason inline no worker); nenhuma mudança em
`classify_failure_reason`.

## Gates de autoavaliação (responder no relatório)

1. Qual teste prova que `invalid_payload` não é reenfileirado em nenhum dos
   dois workers?
2. Qual teste prova que `timeout` continua reenfileirado (regressão)?
3. Onde a decisão vive e por que é única (DRY)?
4. O que mudou nas mensagens persistidas e nos contratos? (Esperado:
   nada.)
5. Por que cada arquivo tocado é necessário?

## Critérios de sucesso binários

- [ ] R1–R4 cobertos RED/GREEN nos dois workers.
- [ ] Fail-fast: terminal na 1ª tentativa + `FinalRunFailure` + batch
      fechado, nos dois workers.
- [ ] `timeout` inalterado (requeue +60s).
- [ ] Log fail-fast sanitizado com prova de sentinela ausente.
- [ ] Máximo 4 arquivos; nenhum model/migration/taxonomia.
- [ ] Gates exit 0; unit final >= baseline, zero failures/errors.

### Condições automáticas de INCOMPLETO

- baseline/RED ausente ou sem falha pelo motivo esperado;
- qualquer worker sem a guarda ou com política duplicada inline;
- `timeout` deixou de reenfileirar ou backoff mudou;
- `FinalRunFailure`/fechamento de batch ausente no fail-fast;
- log fail-fast vaza `str(exc)`/identidade;
- taxonomia/mensagens persistidas alteradas;
- model/migration/dependência tocada; arquivo extra sem justificativa;
- gate falho; relatório ausente/incompleto; task marcada sem evidência.

## Relatório obrigatório

`/tmp/sirhosp-slice-FX-S1-report.md` com: Status; BASE_REF; matriz
requisito→arquivo→teste; RED (comandos + falhas esperadas); GREEN; snippets
antes/depois por arquivo; inspeções `rg` interpretadas; baseline vs final
(exit codes + resumos); gates; justificativas; riscos; `Handoff para
verificador` (arquivos, comandos exatos de rerun, checklist R1–R4).

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, docs/adr/ADR-0008-fullsync-failure-characterization-decision.md and the full fix-fullsync-failure-exhaustion change (proposal.md, design.md section D1, specs delta, tasks.md, slice-prompts/SLICE-FX-S1.md). Implement ONLY FX-S1. Follow the DeepSeek4-Flash protocol in the slice: plan matrix, clean BASE_REF, official unit baseline, real RED for the pure policy and both workers' _mark_run_failed (fail-fast terminal on first invalid_payload attempt with FinalRunFailure and batch closure; EvolutionPdfTimeoutError keeps requeue+60s as regression; sanitized fail-fast log with sentinel proof), minimal GREEN, local REFACTOR (single guard per worker, no duplicated terminal branch), mandatory rg inspections, all official gates with final unit exit 0 and passed >= baseline. Do not change taxonomy, persisted messages, backoff, models, migrations or any other app. Touch only the 4 listed files. Create /tmp/sirhosp-slice-FX-S1-report.md with full evidence and verifier handoff. Any missing/failing item is INCOMPLETE with no task update/commit. If complete, mark only 1.x in tasks.md, commit, push, reply REPORT_PATH=..., then STOP.
```
