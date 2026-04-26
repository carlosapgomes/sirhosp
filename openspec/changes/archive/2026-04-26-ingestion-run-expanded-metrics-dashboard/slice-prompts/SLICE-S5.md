# SLICE-S5 — Consulta operacional no Django Admin

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-metrics-admin/spec.md`
7. `/tmp/sirhosp-slice-IRMD-S4-report.md`
8. este arquivo `slice-prompts/SLICE-S5.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Expor métricas operacionais de ingestão no Django Admin para suporte/diagnóstico, incluindo listagem filtrável de runs e visualização read-only de estágios.

## Escopo permitido (somente)

- `apps/ingestion/admin.py` (novo)
- `tests/integration/test_ingestion_admin.py` (novo)
- `apps/ingestion/models.py` (apenas se for estritamente necessário para `__str__`/meta do stage)

## Escopo proibido

- views/templates do portal
- alterações no worker/commands
- mudanças arquiteturais de autenticação/permissão

## Limite de alteração

Máximo: **3 arquivos**.

## Requisitos funcionais do slice

1. Registrar `IngestionRun` no admin com colunas operacionais úteis:
   - status
   - intent
   - queued_at
   - processing_started_at
   - finished_at
   - timed_out
   - failure_reason
2. Adicionar filtros por `status`, `intent`, `timed_out`, `failure_reason` e janela temporal.
3. Adicionar busca por ID de run e por conteúdo relevante de `parameters_json` (quando viável).
4. Expor `IngestionRunStageMetric` como inline read-only no detalhe do run.
5. Evitar edição acidental de métricas históricas no admin (read-only para campos de observabilidade).

## TDD obrigatório

1. **RED**: criar testes de integração do admin para:
   - acesso ao changelist;
   - aplicação de filtros;
   - renderização de estágios no detalhe.
2. **GREEN**: implementar `ModelAdmin` + inline até os testes passarem.
3. **REFACTOR**: ajustar ergonomia do `list_display` e ordenação sem ampliar escopo.

## Gates obrigatórios S5

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh integration`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S5-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S6).

Pare ao concluir.
