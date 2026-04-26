# SLICE-S7 — Página detalhada de métricas com filtros

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-metrics-portal/spec.md`
7. `/tmp/sirhosp-slice-IRMD-S6-report.md`
8. este arquivo `slice-prompts/SLICE-S7.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Transformar a página `ingestion_metrics` em visão operacional completa com filtros e tabela de runs, mantendo agregações coerentes com o conjunto filtrado.

## Escopo permitido (somente)

- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
- `tests/unit/test_services_portal_ingestion_metrics.py`

## Escopo proibido

- alterações de modelo/migração
- alterações de worker/commands
- alterações em admin

## Limite de alteração

Máximo: **3 arquivos**.

## Requisitos funcionais do slice

1. Suportar filtros por querystring:
   - período (`24h`, `7d`, `30d`)
   - `status`
   - `intent`
   - `failure_reason`
2. Tabela deve listar runs filtrados com colunas operacionais:
   - id
   - intent
   - status
   - queued_at
   - queue latency
   - processing duration
   - total duration
   - failure_reason
   - timed_out
3. Resumo agregado da página deve refletir exatamente o dataset filtrado.
4. Página deve continuar protegida por autenticação.

## TDD obrigatório

1. **RED**: ampliar testes para filtros e coerência entre resumo e tabela.
2. **GREEN**: implementar parsing de filtros + queryset + renderização.
3. **REFACTOR**: extrair função auxiliar de construção de queryset agregada, sem ampliar escopo.

## Gates obrigatórios S7

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh integration`
4. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S7-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S8).

Pare ao concluir.
