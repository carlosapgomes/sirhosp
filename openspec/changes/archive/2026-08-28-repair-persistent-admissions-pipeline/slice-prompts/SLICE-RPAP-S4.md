# RPAP-S4 — Recuperação limitada do censo atual

## Handoff com contexto zero

Leia integralmente antes de editar:

1. `AGENTS.md`, `PROJECT_CONTEXT.md` e todo o change atual;
2. prompts e relatórios COMPLETE de S1–S3;
3. delta `current-census-admissions-recovery/spec.md`;
4. `apps/census/models.py` em `CensusSnapshot`/`BedStatus`;
5. `apps/census/services.py` em completude, proveniência e enqueue;
6. `apps/ingestion/models.py` em batch/run/status;
7. `apps/ingestion/services.py` em `queue_admissions_only_run`;
8. `apps/ingestion/management/commands/recover_stale_ingestion_runs.py` como
   referência de command seguro, sem copiar sua finalidade.

Pré-condição: S2 faz vazio batch-bound falhar e S3 impede demografia duplicada.
Não há command para recuperar apenas pacientes do censo atual. Não acessar
produção neste slice.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Se qualquer item falhar, declare `INCOMPLETE`, não marque tasks, não faça
commit/push e pare.

1. Registre BASE_REF, `git status --short` e matriz requisito→arquivo→teste.
2. Confirme S1–S3 COMPLETE e rode baseline oficial unit; falha/error bloqueia.
3. Escreva RED primeiro para dry-run, bloqueios, limite, idempotência,
   atomicidade e privacidade. RED deve falhar pela ausência do command/serviço.
4. Implemente GREEN mínimo sem modelo, migration ou alteração de runs antigos.
5. Refatore somente o novo fluxo: command fino, serviço coeso, queries claras,
   constantes nomeadas, DRY, YAGNI e transação curta.
6. Não execute manage.py contra produção, Docker hospital ou `.env`.
7. Rode inspeções e todos os gates; final unit exit 0, zero failures/errors e
   passed_final >= baseline.
8. Gere relatório e só então marque 4.1–4.6, commit/push e STOP.

## Objetivo vertical

Entregar `recover_current_census_admissions`: dry-run não mutante por padrão e
apply explícito de até 100 pacientes por batch, usando o último censo completo,
sem duplicar trabalho ou reabrir histórico.

## Requisitos funcionais

### R1 — Fonte canônica e determinística

Selecionar o snapshot de `captured_at` mais recente. Exigir proveniência única
para um `IngestionRun` de censo bem-sucedido e completude pelo helper existente.
Planejar prontuários não vazios de beds `OCCUPIED`, deduplicados e ordenados
deterministicamente. Nunca imprimir os valores.

### R2 — Dry-run seguro

Sem `--apply`, validar e imprimir somente contagens: elegíveis, ativos excluídos,
já recuperados, sem identificador e limite aplicável. Não criar ou alterar
batch, run, patient, admission, movement ou event.

### R3 — Apply explicitamente limitado

`--apply` exige `--limit` inteiro entre 1 e 100. Criar no máximo N
`admissions_only` em um único recovery batch, usando
`queue_admissions_only_run`. Batch deve registrar marcador estável, referência
ao census run e agregados seguros, sem PHI.

### R4 — Idempotência e concorrência

Dentro de transação, serializar planejamento/apply para o census run e reavaliar
exclusões. Pular qualquer paciente com `admissions_only` queued/running e
qualquer paciente já presente em recovery batch do mesmo census run,
independentemente do terminal outcome. Repetição não duplica.

### R5 — História imutável

Não atualizar status, attempts, counters, parameters ou timestamps dos runs do
incidente. Não usar bulk reset/requeue. Se nenhum candidato existir, não criar
batch vazio.

### R6 — Composição e operação

O recovery batch usa retry/closure normais. S2 protege vazio; S3 impede
follow-up demográfico; sucesso cria full-sync normal. O help do command deve
descrever dry-run, apply limitado e proibir implicitamente execução sem escolha
explícita; o runbook completo pertence a S5.

### R7 — Privacidade

Command stdout/stderr/error e docs usam apenas contagens e labels fixos. Testes
incluem sentinelas sintéticas e provam sua ausência da saída.

## Arquivos esperados e limite

Máximo de **4 arquivos rastreados**, além de `tasks.md`:

1. novo `apps/census/admissions_recovery.py`;
2. novo
   `apps/census/management/commands/recover_current_census_admissions.py`;
3. novo `tests/unit/test_current_census_admissions_recovery.py`;
4. `apps/census/services.py`, somente para expor/reusar publicamente o helper
   mínimo de proveniência, se necessário.

Não editar models, migrations, ingestion/services, workers, deploy,
Compose/systemd ou specs. Não copiar o algoritmo de completude/proveniência. Se
a implementação não precisar mudar `services.py`, deixe-o intacto; o limite
continua quatro arquivos.

## TDD obrigatório

### RED

Criar testes sintéticos para:

1. ausência de snapshot;
2. snapshot incompleto e proveniência ambígua;
3. dry-run padrão sem mutação;
4. apply sem limit, zero, negativo e acima de 100 falha antes de mutar;
5. dedupe do mesmo paciente em múltiplos beds;
6. exclusão de prontuário vazio, ativo e recovery anterior;
7. apply N cria um batch e no máximo N runs explícitos;
8. repetição idempotente;
9. concorrência/segunda avaliação não duplica;
10. zero candidatos não cria batch;
11. runs históricos permanecem byte-for-byte nos campos relevantes;
12. stdout/stderr não contêm sentinelas de paciente.

### GREEN

Implementar dataclasses/estruturas pequenas para plano/resultado se úteis,
queries em serviço e command apenas para argumentos/apresentação/CommandError.
Reusar `validate_snapshot_completeness` e `queue_admissions_only_run`.

### REFACTOR

Evitar lógica ORM complexa em `handle`, N+1 por candidato, duplicação do gate de
40, parâmetros JSON clínicos novos além do helper canônico e abstração genérica
de recovery. Não criar tabela de job.

## Checks de inspeção obrigatórios

```bash
rg -n "dry.run|--apply|--limit|100|CommandError" \
  apps/census/management/commands/recover_current_census_admissions.py
rg -n "validate_snapshot_completeness|resolve_single_census_run|queue_admissions_only_run|atomic|select_for_update|recovery" \
  apps/census/admissions_recovery.py apps/census/services.py
rg -n "\.update\(|bulk_update|status=|attempt|requeue|sys\.exit|call_command" \
  apps/census/admissions_recovery.py \
  apps/census/management/commands/recover_current_census_admissions.py
rg -n "dry.run|idempot|ambiguous|incomplete|active|histor|sentinel|100" \
  tests/unit/test_current_census_admissions_recovery.py
```

Esperado: reuso dos helpers públicos, transação/lock, nenhuma atualização
histórica e nenhum `call_command` interno ou segredo.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate repair-persistent-admissions-pipeline --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] R1–R7 cobertos RED/GREEN.
- [ ] Dry-run padrão tem zero mutações.
- [ ] Apply exige limite 1–100 e nunca excede.
- [ ] Fonte é último censo completo com proveniência única.
- [ ] Ativo/prior recovery/dedupe/concorrência não duplicam.
- [ ] Runs históricos permanecem imutáveis.
- [ ] Recovery batch compõe com S2/S3 e full-sync normal.
- [ ] Saída/help não têm identificadores clínicos.
- [ ] Quatro arquivos no máximo; sem model/migration.
- [ ] Gates exit 0 e unit final >= baseline sem failures/errors.

### Condições automáticas de INCOMPLETO

- S1–S3/report ou baseline não confirmado;
- RED ausente/acidental;
- dry-run muta qualquer tabela;
- apply sem limite ou limite >100 aceito;
- snapshot incompleto/ambíguo é usado;
- execução repetida/concomitante duplica;
- run histórico é alterado/reaberto;
- batch vazio/model/migration/queue nova é criada;
- command imprime prontuário, nome, IDs ou erro bruto;
- produção/.env é acessada;
- arquivo extra/gate falho/relatório ausente/task prematura.

## Gates de autoavaliação

1. Qual teste prova zero mutações no dry-run?
2. Como a proveniência e completude são reutilizadas?
3. Qual transação/lock impede duas execuções concorrentes?
4. Como prior recovery e active work são deduplicados?
5. Qual teste prova história imutável?
6. Qual teste prova privacidade da saída?
7. Por que cada arquivo é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-RPAP-S4-report.md` com Status, BASE_REF, matriz,
RED/GREEN, snippets antes/depois, queries/atomicidade, inspeções, baseline/final,
gates, markdown lint, rerun, arquivos/justificativas, riscos e
`Handoff para verificador` R1–R7. Não executar nem relatar dados de produção.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the complete
repair-persistent-admissions-pipeline change, SLICE-RPAP-S4.md and COMPLETE
S1-S3 reports. Implement ONLY S4. Follow the DeepSeek4-Flash protocol: clean
BASE_REF, official unit baseline, real RED, minimal GREEN, local
clean-code/DRY/YAGNI refactor, mandatory rg and every official gate, final unit
exit 0 with zero failures/errors and passed >= baseline. Add a dry-run-by-default
current-census admissions recovery with explicit apply limit 1..100, complete
unambiguous latest census, atomic idempotency, no historical requeue and
aggregate-only output. Touch only the four listed files, with services.py
limited to a public provenance helper if needed; no models, migrations, worker
changes, production commands or .env access. Create
/tmp/sirhosp-slice-RPAP-S4-report.md with evidence and verifier handoff. Any
missing/failing item means INCOMPLETE with no task update/commit. If complete,
mark only S4, commit, push, reply REPORT_PATH=..., then STOP.
```
