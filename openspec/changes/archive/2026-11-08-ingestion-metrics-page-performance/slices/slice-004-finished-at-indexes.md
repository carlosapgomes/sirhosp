# Slice 004 — Índices concorrentes em `finished_at`

- Slice ID: S4
- Change: `2026-11-08-ingestion-metrics-page-performance`
- Task: S4 em `tasks.md`
- Depende de: S3 aceito (ordem sequencial da change).

## Objective

`IngestionRun.finished_at` e `CensusExecutionBatch.finished_at` passam a
ter índice btree criado por migration concorrente, acelerando os
filtros/contagens por período sem lock de escrita prolongado.

## Read first

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/proposal.md`
  — riscos (migration concorrente)
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/design.md`
  — D6, impacto em banco/operação
- `apps/ingestion/models.py` — `IngestionRun`, `CensusExecutionBatch`
  (Meta sem `indexes` hoje)
- `apps/ingestion/migrations/` — padrão das migrations existentes
  (nenhuma usa `AddIndexConcurrently` ainda — este slice estabelece o
  padrão)

Follow the repository engineering policy in `AGENTS.md` and preserve
existing conventions. Prefer the smallest correct change; avoid
speculative abstraction and unrelated refactoring.

## Requirements

- R1 — `IngestionRun.Meta.indexes` declara btree em `finished_at`;
  `CensusExecutionBatch.Meta.indexes` declara btree em `finished_at`.
- R2 — Migration dedicada (`apps/ingestion/migrations/0007_*.py`) cria
  ambos os índices com `AddIndexConcurrently` e `atomic = False`, sem
  `RunPython` e sem alteração de dados.
- R3 — `sqlmigrate` da migration contém `CREATE INDEX CONCURRENTLY`
  para ambos os índices.
- R4 — A migration aplica e reverte limpamente no banco de teste
  (container) — suíte existente continua verde, incluindo setup do banco
  de teste que roda as migrations.
- R5 — Nenhum outro schema, dado ou comportamento muda.

## Expected blast radius

Provavelmente afetados:

- `apps/ingestion/models.py` — `Meta.indexes` das duas classes.
- `apps/ingestion/migrations/0007_*.py` — nova migration.
- Teste de presença de índice (local a definir pelo worker — sugerido
  `tests/unit/test_ingestion_models.py` se existir, ou novo teste
  focado próximo aos testes de ingestão).

Sensíveis / fora de escopo (escalar se precisar tocar):

- Qualquer outra migration (não editar migrations aplicadas).
- Índices em `status`/`intent`/`failure_reason` — explicitamente fora
  (D6); views, templates, workers.

Comportamento anterior que permanece: todas as queries retornam os
mesmos resultados; apenas o plano de execução muda.

## Failing-before plan

TDD adaptado a schema (test seam: introspecção do banco de teste):

1. Teste de presença (RED antes): via `connection.introspection` (ou
   `pg_indexes`), afirmar que existe índice cobrindo
   `ingestion_ingestionrun(finished_at)` e
   `ingestion_censusexecutionbatch(finished_at)`. Hoje não existem →
   falha. Após `Meta.indexes` + migration, o banco de teste (recriado
   pelas fixtures Django) contém os índices → passa.
2. Verificação de concorrência (executável, não necessariamente teste
   automatizado): `uv run python manage.py sqlmigrate ingestion 0007`
   deve conter `CONCURRENTLY`; worker registra o output no report. Se o
   harness de teste preferir, transformar em teste que chama o comando
   — decisão do worker, sem over-engineering.
3. Verificação de rollback (executável, obrigatória para R4): ciclo
   containerizado apply → reverse → reapply da migration no Postgres de
   teste, fora de qualquer transação externa — subir `db` com
   `compose.yml` + `compose.test.yml` (mesmo padrão de
   `scripts/test-in-container.sh`), rodar via serviço `test-runner`:
   `migrate ingestion 0007` (forward), `migrate ingestion 0006`
   (reverse), `migrate ingestion` (reapply); afirmar exit status 0 nas
   três etapas e presença/ausência/presença dos índices via `pg_indexes`.
   Registrar comandos, outputs e exit status no report. Não basta
   `sqlmigrate`: este é o primeiro `AddIndexConcurrently` do repo e o
   caminho reverso precisa de prova executável.

Nota: gerar a migration com `makemigrations` e depois convertê-la para
`AddIndexConcurrently` + `atomic = False` manualmente é o fluxo esperado
e deve estar registrado no report.

## Implementation constraints

- Nomes de índice dentro do limite do Postgres (30 chars no padrão
  Django) — deixar o Django nomear salvo colisão.
- Migration com exatamente 2 operações (`AddIndexConcurrently` × 2);
  nada mais.
- Não rodar a migration contra o banco de desenvolvimento compartilhado
  de forma destrutiva — aplicar via fluxo normal de teste/migrate; o
  deploy em produção ocorre fora desta change.
- Registrar no report que o deploy deve ocorrer fora de pico (tabela com
  2,1 M linhas), mesmo com `CONCURRENTLY`.

## Validation

Focused validation (worker):

```bash
uv run python manage.py makemigrations --check --dry-run
./scripts/test-in-container.sh check
uv run pytest -q <teste-de-índice-do-slice>
```

Project-required gates: referenciar `AGENTS.md` — este slice toca
schema, então o `quality-gate` do controller ao final da change é
obrigatório; worker garante ao menos `check` + focados + suíte de
ingestão afetada verde.

Runtime/verification evidence: output de `sqlmigrate` com `CONCURRENTLY`
registrado no report; opcional: `EXPLAIN` de um count por janela
mostrando Index Scan (registrar se feito).

## Acceptance criteria

- [ ] R1 demonstrado: `Meta.indexes` declarado e teste de presença verde.
- [ ] R2 demonstrado: migration dedicada, concorrente, não-atômica.
- [ ] R3 demonstrado: `sqlmigrate` com `CONCURRENTLY` registrado.
- [ ] R4 demonstrado: focados + setup de banco de teste verdes **e**
      ciclo apply/reverse/reapply containerizado com exit 0 registrado.
- [ ] R5 demonstrado: diff restrito a models + 1 migration + teste.
- [ ] `makemigrations --check` limpo (sem migration pendente).

## Escalation conditions

Parar com `BLOCKED_NEEDS_DECISION` se descobrir: `AddIndexConcurrently`
incompatível com o setup de teste do projeto; nome de índice colide;
qualquer dado precisa migrar junto; planner não usa o índice e o ganho
exige índice composto (decisão nova de schema); necessidade de downtime.

## Evidence report

Produzir `/tmp/sirhosp-slice-S4-report.md` com: status, requirements →
evidence, arquivos alterados (incluindo `sqlmigrate`), failing-before
evidence, passing-after evidence, comandos + exit status,
runtime/verification evidence, expansão de blast radius (se houver),
nota de deploy fora de pico, riscos/limitações, decisões pendentes.

## Worker handoff

Implement only this approved slice. Treat the slice and referenced
OpenSpec artifacts as the implementation contract. Reconstruct context
from the listed files; do not rely on prior conversation. Follow the
repository engineering policy. Produce failing-before evidence,
implement the smallest correct change, run focused validation, and
produce the required evidence report. Do not update `tasks.md`, commit,
push, merge, archive, or start another slice. If a new decision is
required, stop with `BLOCKED_NEEDS_DECISION` and evidence. Otherwise
finish with `READY_FOR_REVIEW` and `REPORT_PATH=<path>`.
