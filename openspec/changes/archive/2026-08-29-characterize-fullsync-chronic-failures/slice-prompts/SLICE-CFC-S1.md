# CFC-S1 — Command read-only de caracterização da coorte fail-only

## Handoff com contexto zero

Leia integralmente:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. o change atual `characterize-fullsync-chronic-failures`
   (proposal/design/specs/tasks);
3. `openspec/specs/ingestion-pipeline-health/spec.md` (contrato sanitizado
   de referência) e `apps/ingestion/pipeline_health.py` (estilo de
   serviço/command);
4. `apps/ingestion/run_lifecycle.py` (taxonomia de reasons);
5. `apps/ingestion/models.py` em `IngestionRun`, `IngestionRunAttempt`,
   `IngestionRunStageMetric`, `FinalRunFailure` (campos consultados);
6. `tests/unit/test_ingestion_pipeline_health.py` (padrão de testes de
   read-only/privacidade).

Estado: o health check expõe a taxa de falha por reason, mas não
caracteriza a coorte crônica (pacientes fail-only), nem timing por estágio
ou padrão horário. Este slice não corrige nada; torna a coorte
caracterizável por agregados.

## Protocolo obrigatório para implementador DeepSeek4-Flash

1. Registre BASE_REF, árvore limpa e matriz requisito→arquivo→teste.
2. Rode baseline unit oficial; falha/error bloqueia.
3. RED primeiro para cada métrica, validação, read-only e privacidade.
4. GREEN mínimo: serviço de consulta + command fino.
5. REFACTOR local: cálculos puros, unidades nos nomes, query count
   controlado, DRY/YAGNI.
6. Rode inspeções `rg` e todos os gates oficiais; final unit exit 0,
   zero failures/errors e passed >= baseline.
7. Relatório antes de marcar 1.1–1.5, commit/push e STOP.

## Objetivo vertical

Entregar `characterize_fullsync_failures`: command read-only que agrega a
coorte fail-only de `full_sync`/`full_admission_sync` na janela, sem nunca
identificar pacientes.

## Requisitos funcionais

### R1 — Janela e validação

`--window-hours` positivo (default 168), `--min-attempts` positivo
(default 3), `--max-per-stage-rows` positivo (default 5000, teto de
segurança para perfis de estágio). Inválido falha antes de query.

### R2 — Coorte fail-only

Pacientes com ≥ `--min-attempts` runs terminais na janela e zero sucessos.
Saída: `cohort_patients` (contagem), `cohort_failed_runs`, mediana e máximo
de tentativas por paciente (`attempts_median`, `attempts_max`), idade da
primeira e da última falha (`first_failure_age_hours`,
`last_failure_age_hours`). Agrupamento por
`parameters_json__patient_record` somente em memória efêmera; a chave nunca
sai do serviço.

### R3 — Reasons e contraste

Distribuição de `failure_reason` dos runs da coorte e, para contraste, dos
runs de pacientes fail-then-ok (mesma janela). Razões vazias agregadas como
`none`. Ordenação determinística.

### R4 — Timing por estágio e histograma horário

Para os runs falhos da coorte: duração por `stage_name` (mediana e p90 em
segundos, teto `--max-per-stage-rows`) e distribuição do estágio terminal
falho. Histograma agregado por hora UTC de `queued_at` dos runs falhos da
coorte (24 posições, `hour=NN=count`).

### R5 — Saída sanitizada e read-only

Exit 0 sempre que a caracterização completa (diagnóstico, não gate). Saída
somente com nomes de métricas, counts, durações, percentis, horas e reasons
allowlisted. Proibir PK, `parameters_json`, patient record, nome, texto,
URL, erro bruto. Zero INSERT/UPDATE/DELETE e zero rede/subprocesso/
playwright/call_command.

## Arquivos esperados e limite

Máximo de **3 arquivos rastreados**, além de `tasks.md`:

1. novo `apps/ingestion/fullsync_failure_characterization.py`;
2. novo
   `apps/ingestion/management/commands/characterize_fullsync_failures.py`;
3. novo `tests/unit/test_fullsync_failure_characterization.py`.

Não editar models, migrations, workers, health check, `run_lifecycle.py`,
docs ou deploy.

## TDD obrigatório

### RED mínimo (dados sintéticos)

1. coorte fail-only detectada (contagem/tentativas/idades);
2. paciente com menos tentativas que `--min-attempts` excluído;
3. paciente fail-then-ok fora da coorte e presente no contraste;
4. distribuição de reasons da coorte e contraste (inclui `none`);
5. perfis de estágio (mediana/p90) e estágio terminal falho;
6. histograma horário;
7. argumentos inválidos rejeitados antes de query (mock do serviço);
8. contagens de models antes/depois idênticas (healthy e com coorte);
9. spies de `subprocess`/`urllib`/`call_command`/`sync_playwright`;
10. sentinelas de patient/nome/texto/URL/erro ausentes de
    stdout/stderr/qualquer erro.

### GREEN

Value objects congelados + `characterize_fullsync_failures(config, *,
now=None)` + command fino (padrão `pipeline_health`).

### REFACTOR

Sem mega-query ilegível, sem N+1, sem floats sem unidade, sem threshold
mágico, sem `except Exception` com texto bruto.

## Checks de inspeção obrigatórios

```bash
rg -n "window.hours|min.attempts|max.per.stage|median|p90|percentile|age.hours" \
  apps/ingestion/management/commands/characterize_fullsync_failures.py \
  apps/ingestion/fullsync_failure_characterization.py
rg -n "\.create\(|\.save\(|\.update\(|\.delete\(|bulk_|call_command|subprocess|playwright|requests|http" \
  apps/ingestion/fullsync_failure_characterization.py \
  apps/ingestion/management/commands/characterize_fullsync_failures.py
rg -n "parameters_json|patient_source|prontuario|nome|content|error_message|pk|_id" \
  apps/ingestion/fullsync_failure_characterization.py \
  apps/ingestion/management/commands/characterize_fullsync_failures.py
rg -n "cohort|fail.only|contrast|stage|hour|median|sentinel|read.only" \
  tests/unit/test_fullsync_failure_characterization.py
```

Interpretar: `parameters_json__patient_record` apenas em agrupamento
efêmero; `_id`/PK nunca em DTO/output; zero método mutante ou rede.

## Gates oficiais obrigatórios

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate characterize-fullsync-chronic-failures --strict
./scripts/markdown-lint.sh
```

## Critérios binários de sucesso

- [ ] R1–R5 cobertos RED/GREEN.
- [ ] Coorte fail-only caracterizada sem identidade.
- [ ] Reasons/contraste, timing por estágio e histograma agregados.
- [ ] Command read-only e sem ações externas (spies + contagens).
- [ ] Saída sem nenhuma sentinela identificável.
- [ ] Máximo três arquivos; sem model/migration/dependência.
- [ ] Gates exit 0; unit final >= baseline sem failures/errors.

### Condições automáticas de INCOMPLETO

- baseline/RED ausente ou falho;
- métrica/threshold sem teste;
- serviço/command muta DB ou chama fonte/rede;
- saída inclui ID/parâmetro/sentinela/texto clínico;
- identidade de paciente escapa em qualquer nível;
- model/migration/provider/infra adicionado;
- arquivo extra/gate falho/relatório ausente/task prematura.

## Gates de autoavaliação

1. Qual teste prova a exclusão por `--min-attempts`?
2. Como o contraste fail-then-ok é isolado da coorte?
3. Onde as chaves de paciente deixam de existir antes do output?
4. Como foi provado read-only e sem rede?
5. Por que cada arquivo é necessário?

## Relatório obrigatório

Criar `/tmp/sirhosp-slice-CFC-S1-report.md` com Status, BASE_REF, matriz,
RED/GREEN, snippets, inspeções, baseline/final, gates, rerun,
arquivos/justificativas, riscos e `Handoff para verificador` R1–R5.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md, the full
characterize-fullsync-chronic-failures change and SLICE-CFC-S1.md. Implement
ONLY S1. Follow the DeepSeek4-Flash protocol: clean BASE_REF, official unit
baseline, real RED for every metric/validation/privacy/read-only contract,
minimal GREEN, local clean-code/DRY/YAGNI refactor, mandatory rg and all
official gates, final unit exit 0 with zero failures/errors and passed >=
baseline. Deliver a read-only aggregate characterize_fullsync_failures
service/command; never mutate DB, call network, output identifiers or add
models/migrations/dependencies. Touch only three listed files. Create
/tmp/sirhosp-slice-CFC-S1-report.md with evidence and verifier handoff. Any
missing/failing item is INCOMPLETE with no task update/commit. If complete,
mark only S1, commit, push, reply REPORT_PATH=..., then STOP.
```
