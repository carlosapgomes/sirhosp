# SLICE-S4 — Contrato de métricas aplicado ao `extract_census`

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-observability/spec.md`
7. `/tmp/sirhosp-slice-IRMD-S3-report.md`
8. este arquivo `slice-prompts/SLICE-S4.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Aplicar o mesmo contrato operacional de métricas no command `extract_census` (lifecycle, falha categorizada e estágios), com testes unitários sem rodar scraping real.

## Escopo permitido (somente)

- `apps/census/management/commands/extract_census.py`
- `tests/unit/test_extract_census_command.py`
- `tests/unit/test_extract_census_management_command.py` (novo, se necessário)

## Escopo proibido

- alterações de parser/classificador de censo sem necessidade
- mudanças em views/templates
- mudanças em worker de ingestão clínica

## Limite de alteração

Máximo: **3 arquivos**.

## Requisitos funcionais do slice

1. `extract_census` deve preencher `processing_started_at` quando iniciar execução efetiva.
2. Em sucesso terminal, preencher `finished_at`, limpar falha e manter `timed_out=False`.
3. Em timeout do subprocess, classificar como `failure_reason="timeout"` e `timed_out=True`.
4. Em erro de subprocess não-timeout, preencher categoria apropriada (`source_unavailable` ou `unexpected_exception`, conforme mapeamento definido no slice S2).
5. Persistir métricas de estágio compatíveis com o modelo de estágios introduzido no S3 (ex.: `census_extraction`, `census_persistence`).
6. Testes não podem depender de Playwright real: usar mock de `subprocess.run` e fixture de CSV sintético.

## TDD obrigatório

1. **RED**: criar testes cobrindo sucesso, retorno não-zero e timeout.
2. **GREEN**: implementar instrumentação no command até testes passarem.
3. **REFACTOR**: isolar helpers internos de atualização de run/stage sem ampliar escopo.

## Gates obrigatórios S4

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S4-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S5).

Pare ao concluir.
