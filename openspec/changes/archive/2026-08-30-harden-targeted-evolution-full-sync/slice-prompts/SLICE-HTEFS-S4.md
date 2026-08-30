# HTEFS-S4 — Guard automático fixo de 60 minutos

## Handoff para implementador LLM com contexto zero

Leia integralmente, nesta ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. este change completo, especialmente `design.md` D5,
   `specs/fullsync-failure-exhaustion-fix/spec.md`, a requirement de follow-up
   na spec do worker e `tasks.md`;
3. relatórios verificados S1–S3 em `/tmp` e tasks 1.x–3.x; bloqueie se ausentes;
4. `apps/ingestion/services.py`:
   `enqueue_most_recent_admission_full_sync` e helpers de enqueue;
5. os dois call sites desse serviço nos workers para confirmar que a política já
   é compartilhada; não os altere;
6. `apps/ingestion/models.py`: `IngestionRun.next_retry_at`, `finished_at`,
   status, intent, parameters e batch;
7. `apps/ingestion/run_lifecycle.py` e `_mark_run_failed` dos dois workers para
   caracterizar, sem mudar, retry +60s e fail-fast `invalid_payload`;
8. `apps/ingestion/views.py` para provar que enqueue manual de
   `full_admission_sync` não chama o helper automático; não o altere;
9. testes existentes de services/enqueue/retry/batch.

Investigação: já há retry intra-run +60 s, cooldown/backoff do orquestrador de
censo em 30 min e circuit breaker de stale recovery para mutação em massa. Não
há guard por internação entre uma falha terminal e a próxima `full_sync`
automática. Este slice preenche só essa lacuna usando histórico e
`next_retry_at`; não cria mecanismo paralelo e nunca espera mais de 60 min após
a falha terminal.

## Protocolo obrigatório para DeepSeek4-Flash

Qualquer falha implica `Status: INCOMPLETE`, sem tasks/commit/push.

1. Capture BASE_REF, árvore limpa, S1–S3 verificados.
2. Matriz requisito→arquivo→teste antes de editar.
3. Baseline oficial unit; falha bloqueia.
4. RED primeiro com relógio determinístico; nenhuma espera real.
5. GREEN mínimo e REFACTOR DRY/YAGNI somente no serviço.
6. Inspeções obrigatórias e prova de que workers/views não mudaram.
7. Gates oficiais + markdown lint, exit 0, unit final >= baseline.
8. Relatório reproduzível por terceiro LLM.

## Objetivo end-to-end

Após uma falha terminal recente da mesma internação, admissions-only ainda
cria o `full_sync` automático e o liga ao batch, mas define
`next_retry_at = finished_at_da_falha + 60 min`. O worker existente não o
reivindica cedo. Prazo vencido ou sucesso terminal mais recente cria run
imediatamente elegível. Manual `full_admission_sync` e retry da mesma run
permanecem intactos.

## Requisitos funcionais

- **R1 — Escopo por internação:** consultar resultado terminal mais recente com
  `parameters_json.admission_id == str(latest.pk)` e intent em `full_sync` ou
  `full_admission_sync`. Não agrupar apenas por paciente.
- **R2 — Resultado mais recente:** considerar status `succeeded`/`failed` com
  `finished_at`, ordenado por término (e PK como desempate determinístico).
- **R3 — Falha recente:** se o mais recente é `failed` e
  `finished_at + 60min > now`, criar a nova run queued com exatamente esse
  deadline em `next_retry_at`; sem arredondar ou somar 60 a `now`.
- **R4 — Sem extensão:** falha com prazo vencido gera `next_retry_at=None`;
  re-enqueues futuros não empurram a janela a partir deles.
- **R5 — Sucesso reseta:** se o terminal mais recente é sucesso, ignorar falhas
  anteriores e usar `next_retry_at=None`.
- **R6 — Sempre enfileirar:** nunca retornar `None` por causa do guard; preservar
  batch e parâmetros existentes. `None` continua apenas quando não há Admission.
- **R7 — Manual intacto:** não alterar view/service de
  `full_admission_sync`; run manual nasce segundo contrato atual, sem aplicar o
  guard automático.
- **R8 — Retry interno intacto:** ambos `_mark_run_failed` continuam +60 s para
  falha retryable e fail-fast para `invalid_payload`; nenhuma constante deles
  muda.
- **R9 — Sem estado novo:** nenhum model/migration/counter/config/scheduler,
  nenhuma exponencial. Constante nomeada de 60 min no serviço.
- **R10 — Sanitização:** helper/log não emite patient/admission/source keys nem
  erro bruto. Preferir nenhuma nova linha de log se não for necessária.

## TDD obrigatório

### RED mínimo

No arquivo novo consolidado, com timezone determinístico, prove:

1. falha terminal há 10 min → run criada no mesmo batch, queued,
   `next_retry_at = failure.finished_at + 60min` (restam 50, não novos 60);
2. falha exatamente/mais de 60 min → imediatamente elegível (`None`);
3. falha antiga seguida por sucesso recente → `None`;
4. sucesso antigo seguido por falha recente → deferida;
5. falha recente de outra internação do mesmo paciente não afeta o alvo;
6. terminal `full_admission_sync` participa do reset/guard conforme outcome;
7. rows queued/running ou terminal sem `finished_at` não substituem o último
   terminal válido;
8. paciente sem admission mantém retorno `None`;
9. parâmetros/batch do follow-up são idênticos ao contrato anterior, exceto
   `next_retry_at` quando aplicável;
10. enqueue manual exercitado pela função/view existente não recebe deferral;
11. regressão real dos dois `_mark_run_failed`: timeout continua requeue em
    aproximadamente +60 s; invalid_payload continua terminal fail-fast.

Não teste tempo com `sleep`. Não faça asserts sobre SQL textual; prove outcome
persistido.

### GREEN

Implementar R1–R10 somente no helper automático compartilhado e helpers privados
puros/consulta mínima.

### REFACTOR

- cálculo `not_before` em função pequena, se útil;
- uma query de latest terminal; sem loops/counters;
- nenhum branch duplicado nos workers;
- não tocar no orquestrador, health check ou stale recovery.

## Arquivos permitidos

Limite de **2 arquivos**, além de `tasks.md`:

1. `apps/ingestion/services.py`;
2. `tests/unit/test_automatic_fullsync_deferral.py` (novo).

Workers, views e models são somente leitura. Proibido migration, settings,
orchestration, deploy/docs/specs/design, dependência. Arquivo extra = bloqueio.

## Inspeções obrigatórias

```bash
rg -n "enqueue_most_recent_admission_full_sync|next_retry_at|60|timedelta" \
  apps/ingestion/services.py
rg -n "enqueue_most_recent_admission_full_sync" \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "next_retry_at = now \+ timedelta\(seconds=60\)|should_retry_failure_reason" \
  apps/ingestion/management/commands/process_ingestion_runs.py \
  apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py
rg -n "full_admission_sync" apps/ingestion/views.py
rg -n "other.*admission|success|expired|manual|invalid_payload|timeout" \
  tests/unit/test_automatic_fullsync_deferral.py
git diff --check
git diff --name-only
git diff -- apps/ingestion/management/commands apps/ingestion/views.py \
  apps/ingestion/models.py
```

Último diff deve estar vazio. Interprete que ambos workers reutilizam o serviço,
manual não o usa, retry interno não mudou e não há estado novo.

## Critérios binários de aceite

- [ ] R1–R10 têm RED/GREEN.
- [ ] Deadline deriva de `failed.finished_at`, nunca de `now`.
- [ ] Teto fixo 60 min, sem extensão/exponencial.
- [ ] Escopo é admission id; outra admission não interfere.
- [ ] Sucesso mais recente reseta e manual ignora.
- [ ] Follow-up sempre existe, mantém batch/parâmetros.
- [ ] Retry interno +60s e invalid_payload fail-fast provados nos dois workers.
- [ ] Somente 2 arquivos + tasks; diff dos read-only vazio.
- [ ] Gates exit 0 e unit final >= baseline.

### Condições automáticas de INCOMPLETO

S1–S3 não verificados; baseline/RED ausente; janela calculada de `now`; espera

> 60 min; reenqueue estende janela; guard por paciente; não enfileira; manual
> diferido; retry interno alterado; model/migration/orchestrator tocado; arquivo
> extra; gate/markdown falho; relatório incompleto; task marcada sem prova.

## Gates de autoavaliação

1. Qual teste distingue `failure+60` de `now+60`?
2. Qual prova reset por sucesso e isolamento entre admissions?
3. Por que o batch não fecha/perde follow-up durante a espera?
4. Qual prova manual imediato?
5. Qual prova que mecanismos +60s/fail-fast existentes não mudaram?
6. Por que isto complementa, em vez de duplicar, cooldown/stale recovery?

## Validação mínima

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
```

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-HTEFS-S4-report.md` com Status, BASE_REF, verificação
S1–S3, matriz, baseline, RED/GREEN, snippets antes/depois de services, teste novo
e tasks, inspeções (incluindo diffs read-only vazios), gates, riscos e `Handoff
para verificador` com reruns/checklist R1–R10.

Se completo, marque somente 4.x, markdown lint, commit/push e STOP. Não inicie
S5.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full harden-targeted-evolution-full-sync change and verified S1-S3 reports. Implement ONLY HTEFS-S4 per its complete slice prompt. Require clean BASE_REF and official unit baseline. RED first with deterministic time: latest terminal result per admission, recent failure sets exactly failure.finished_at+60min, expired failure no delay, later success reset, other admission isolation, full_admission terminal participation, invalid/nonterminal rows ignored, same batch/parameters, manual immediate, and both workers' existing timeout+60s/invalid_payload fail-fast regression. Minimal GREEN only in shared services helper; no model/migration/worker/view/orchestrator edits and no exponential state. Touch only services.py plus one new test and tasks.md. Run all rg/read-only diff inspections, official gates and markdown lint. Write /tmp/sirhosp-slice-HTEFS-S4-report.md with before/after per file and verifier reruns. Any unmet item is INCOMPLETE without task mark/commit. If complete mark only 4.x, commit, push and STOP before S5.
```
