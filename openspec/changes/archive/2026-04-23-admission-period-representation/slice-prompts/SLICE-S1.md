<!-- markdownlint-disable MD013 -->
# SLICE-S1 — Snapshot de internações no conector/extractor

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-period-representation/proposal.md`
4. `openspec/changes/admission-period-representation/design.md`
5. `openspec/changes/admission-period-representation/tasks.md`
6. `openspec/changes/admission-period-representation/specs/patient-admission-mirror/spec.md`
7. este arquivo `slice-prompts/SLICE-S1.md`

## Pré-condição de branch

Se ainda não existir, criar e trocar para branch dedicada:

```bash
git checkout -b feature/admission-period-representation
```

Se já existir:

```bash
git checkout feature/admission-period-representation
```

## Objetivo do slice

Capturar lista de internações conhecidas do paciente no conector Playwright e torná-la consumível pelo extractor Django sem quebrar API atual de evoluções.

## Escopo permitido (somente)

- `automation/source_system/medical_evolution/path2.py`
- `apps/ingestion/extractors/playwright_extractor.py`
- `tests/unit/test_evolution_extractor.py`
- (opcional) novo teste unitário específico do extractor, se realmente necessário

## Escopo proibido

- worker / command `process_ingestion_runs`
- models/migrations
- views/templates do portal

## Limite de alteração

Máximo: **7 arquivos**.

## Requisitos funcionais do slice

1. `path2.py` deve exportar snapshot de internações conhecidas do paciente (lista completa encontrada na tabela), em artefato JSON dedicado.
2. Cada item de snapshot deve conter, no mínimo:
   - `admission_key`
   - `admission_start`
   - `admission_end`
   - `ward` (quando houver)
   - `bed` (quando houver)
3. `PlaywrightEvolutionExtractor` deve disponibilizar método explícito para obter snapshot de internações, sem quebrar `extract_evolutions()`.
4. Ausência/falha do artefato de internações deve gerar erro claro e tipado.

## TDD obrigatório

1. **RED**: testes falhando para parse/normalização do snapshot.
2. **GREEN**: implementar mínimo para passar.
3. **REFACTOR**: limpeza de nomes/duplicações sem ampliar escopo.

## Gates obrigatórios S1

Registrar comando + exit code + resultado:

1. `uv run python manage.py check`
2. `uv run pytest -q tests/unit/test_evolution_extractor.py`
3. `uv run ruff check config apps tests manage.py`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-APR-S1-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S2).

Pare ao concluir.
