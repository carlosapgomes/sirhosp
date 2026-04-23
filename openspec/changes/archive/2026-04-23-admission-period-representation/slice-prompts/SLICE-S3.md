<!-- markdownlint-disable MD013 -->
# SLICE-S3 — Worker: semântica de falha + métricas de internações no run

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-representation/proposal.md`
4. `openspec/changes/admission-period-representation/design.md`
5. `openspec/changes/admission-period-representation/tasks.md`
6. `openspec/changes/admission-period-representation/specs/evolution-ingestion-on-demand/spec.md`
7. `openspec/changes/admission-period-representation/specs/ingestion-run-observability/spec.md`
8. `/tmp/sirhosp-slice-APR-S2-report.md`
9. este arquivo `slice-prompts/SLICE-S3.md`

## Pré-condição de branch

Obrigatório estar em:

```bash
git checkout feature/admission-period-representation
```

## Objetivo do slice

Aplicar as regras operacionais de execução e observabilidade:

- captura de internações como etapa explícita no worker;
- persistência de internações antes da etapa de evoluções;
- semântica de falha confirmada pelo produto;
- métricas de internações visíveis em `IngestionRun` e no status.

## Escopo permitido (somente)

- `apps/ingestion/models.py`
- `apps/ingestion/migrations/*` (somente migration necessária)
- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `apps/ingestion/templates/ingestion/run_status.html`
- `tests/integration/test_worker_lifecycle.py`
- `tests/integration/test_worker_gap_planning.py`
- `tests/integration/test_ingestion_http.py`

## Escopo proibido

- alterações visuais amplas em portal de pacientes
- mudanças de arquitetura de fila

## Limite de alteração

Máximo: **8 arquivos**.

## Regras obrigatórias deste slice

1. Falha ao capturar internações => `run.failed` imediatamente.
2. Captura/persistência de internações ok + falha nas evoluções => manter internações e `run.failed`.
3. Captura internações ok + nenhuma evolução na janela => `run.succeeded` com zero eventos.
4. Persistir métricas:
   - `admissions_seen`
   - `admissions_created`
   - `admissions_updated`
5. Exibir métricas no template de status.

## TDD obrigatório

1. **RED**: cenários de lifecycle falhando com o contrato novo.
2. **GREEN**: implementar mínimo para passar.
3. **REFACTOR**: reduzir duplicação de fluxo no worker.

## Gates obrigatórios S3

Registrar comando + exit code + resultado:

1. `uv run python manage.py check`
2. `uv run pytest -q tests/integration/test_worker_lifecycle.py tests/integration/test_worker_gap_planning.py tests/integration/test_ingestion_http.py`
3. `uv run ruff check config apps tests manage.py`
4. `uv run mypy config apps tests manage.py`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-APR-S3-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S4).

Pare ao concluir.
