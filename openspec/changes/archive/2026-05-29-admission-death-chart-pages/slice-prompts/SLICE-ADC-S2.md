# SLICE-ADC-S2: Template compartilhado com dois gráficos de barras

## Handoff para executor LLM

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-death-chart-pages/proposal.md`
4. `openspec/changes/admission-death-chart-pages/design.md`
5. `openspec/changes/admission-death-chart-pages/tasks.md`
6. `openspec/changes/admission-death-chart-pages/specs/daily-operational-event-charts/spec.md`
7. relatório `/tmp/sirhosp-slice-ADC-S1-report.md`, se existir

Implemente somente o Slice ADC-S2.

## Objetivo

Renderizar a experiência visual completa nas páginas de admissões e óbitos:
grave diário em barras e média por dia da semana em barras.

## Escopo máximo

- `tests/unit/test_services_portal_dashboard.py`
- `apps/services_portal/templates/services_portal/daily_event_chart.html`
- `apps/services_portal/views.py`, somente se ajustes pequenos de contexto forem
  necessários

Se precisar alterar mais arquivos, pare e reporte bloqueio.

## TDD obrigatório

1. Escreva testes RED para:
   - canvas do gráfico diário;
   - canvas da média por dia da semana quando houver dados;
   - estado vazio sem canvas quebrado;
   - títulos específicos de admissões e óbitos.
2. Rode o teste específico e confirme falha.
3. Implemente o template e JavaScript mínimo para GREEN.
4. Refatore apenas duplicação local.

## Validação

Executar no final do slice:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

Rode `./scripts/markdown-lint.sh` se alterar qualquer `.md` versionado.

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-ADC-S2-report.md` com:

- resumo;
- checklist de aceite;
- arquivos alterados;
- fragmentos antes/depois;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Pare após concluir o slice.
