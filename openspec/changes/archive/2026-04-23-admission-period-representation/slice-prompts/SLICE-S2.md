<!-- markdownlint-disable MD013 -->

# SLICE-S2 — Persistência de internações + fallback determinístico de associação

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-representation/proposal.md`
4. `openspec/changes/admission-period-representation/design.md`
5. `openspec/changes/admission-period-representation/tasks.md`
6. `openspec/changes/admission-period-representation/specs/patient-admission-mirror/spec.md`
7. `openspec/changes/admission-period-representation/specs/evolution-ingestion-on-demand/spec.md`
8. `/tmp/sirhosp-slice-APR-S1-report.md`
9. este arquivo `slice-prompts/SLICE-S2.md`

## Pré-condição de branch

Obrigatório estar em:

```bash
git checkout feature/admission-period-representation
```

## Objetivo do slice

Implementar o núcleo de domínio para:

- upsert de snapshot de internações;
- associação evento->internação por `admission_key` com fallback determinístico por `happened_at`.

## Escopo permitido (somente)

- `apps/ingestion/services.py`
- `apps/patients/models.py` (somente se estritamente necessário para campos já existentes)
- `tests/unit/test_ingestion_service.py`
- `tests/unit/test_regression_edge_cases.py`
- (opcional) novo teste unitário de serviço, se necessário

## Escopo proibido

- worker/management command
- templates/views
- migrações neste slice

## Limite de alteração

Máximo: **8 arquivos**.

## Regras obrigatórias deste slice

1. Upsert de internações deve aceitar período (`admission_date`/`discharge_date`) quando disponível.
2. `ward/bed` só podem ser atualizados com valor não vazio.
3. Fallback determinístico quando faltar `admission_key` válida:
   - match por período;
   - se múltiplos, `admission_date` mais recente;
   - sem match, mais próxima anterior; se não houver, mais próxima posterior;
   - desempate final por `source_admission_key` ascendente.

## TDD obrigatório

1. **RED**: testes falhando para os 3 blocos acima.
2. **GREEN**: implementação mínima para passar.
3. **REFACTOR**: consolidar funções auxiliares sem ampliar escopo.

## Gates obrigatórios S2

Registrar comando + exit code + resultado:

1. `uv run python manage.py check`
2. `uv run pytest -q tests/unit/test_ingestion_service.py tests/unit/test_regression_edge_cases.py`
3. `uv run ruff check config apps tests manage.py`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-APR-S2-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S3).

Pare ao concluir.
