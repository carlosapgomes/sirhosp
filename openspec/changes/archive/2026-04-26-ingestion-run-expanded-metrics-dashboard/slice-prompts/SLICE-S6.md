# SLICE-S6 — Dashboard com cards de métricas e navegação

## Handoff de entrada (contexto zero)

Leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/ingestion-run-expanded-metrics-dashboard/proposal.md`
4. `openspec/changes/ingestion-run-expanded-metrics-dashboard/design.md`
5. `openspec/changes/ingestion-run-expanded-metrics-dashboard/tasks.md`
6. `openspec/changes/ingestion-run-expanded-metrics-dashboard/specs/ingestion-run-metrics-portal/spec.md`
7. `/tmp/sirhosp-slice-IRMD-S5-report.md`
8. este arquivo `slice-prompts/SLICE-S6.md`

## Pré-condição de branch

```bash
git checkout feature/ingestion-run-expanded-metrics-dashboard
```

## Objetivo do slice

Adicionar visão resumida de métricas de ingestão no dashboard (janela padrão 24h) e criar a rota/página inicial para drill-down.

## Escopo permitido (somente)

- `apps/services_portal/views.py`
- `apps/services_portal/urls.py`
- `apps/services_portal/templates/services_portal/dashboard.html`
- `apps/services_portal/templates/services_portal/ingestion_metrics.html` (novo, versão inicial)
- `tests/unit/test_services_portal_dashboard.py` (ajustes)
- `tests/unit/test_services_portal_ingestion_metrics.py` (novo)

## Escopo proibido

- filtros avançados da página detalhada (deixar para S7)
- alterações em app de pacientes/censo fora do necessário

## Limite de alteração

Máximo: **6 arquivos**.

## Requisitos funcionais do slice

1. Dashboard deve calcular e exibir cards de ingestão para últimas 24h:
   - total de runs finalizados;
   - taxa de sucesso;
   - taxa de timeout;
   - duração média de execução.
2. Quando não houver runs na janela, cards devem renderizar valores zerados sem erro.
3. Adicionar CTA/card no dashboard apontando para `services_portal:ingestion_metrics`.
4. Criar rota autenticada e view inicial `ingestion_metrics` (página placeholder funcional) para receber o clique do dashboard.

## TDD obrigatório

1. **RED**: criar/ajustar testes de dashboard para novos cards e fallback vazio.
2. **RED**: criar teste da nova rota autenticada (200 para autenticado, redirect para anônimo).
3. **GREEN**: implementar agregação e navegação até os testes passarem.
4. **REFACTOR**: extrair helper de agregação no `views.py` se necessário, sem ampliar escopo.

## Gates obrigatórios S6

Registrar comando + exit code + resultado:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-IRMD-S6-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados;
- snippets before/after por arquivo;
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S7).

Pare ao concluir.
