# SLICE-ADC-S1: Backend e rotas dos gráficos de admissões/óbitos

## Handoff para executor LLM

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-death-chart-pages/proposal.md`
4. `openspec/changes/admission-death-chart-pages/design.md`
5. `openspec/changes/admission-death-chart-pages/tasks.md`
6. `openspec/changes/admission-death-chart-pages/specs/daily-operational-event-charts/spec.md`
7. `openspec/changes/admission-death-chart-pages/specs/services-portal-navigation/spec.md`

Implemente somente o Slice ADC-S1.

## Objetivo

Expor páginas autenticadas para gráficos de admissões e óbitos com contexto de
série diária e média por dia da semana, usando dados já existentes.

## Escopo máximo

- `tests/unit/test_services_portal_dashboard.py`
- `apps/services_portal/views.py`
- `apps/services_portal/urls.py`
- opcionalmente um template mínimo compartilhado se necessário para HTTP 200

Se precisar alterar mais arquivos, pare e reporte bloqueio.

## TDD obrigatório

1. Escreva testes RED para:
   - autenticação das novas rotas;
   - HTTP 200 autenticado;
   - uso de `DailyAdmissionCount` e `DailyDeathCount`;
   - respeito a `?dias=30`.
2. Rode o teste específico e confirme falha.
3. Implemente o mínimo para GREEN.
4. Refatore apenas nomes/helpers locais.

## Validação

Executar no final do slice:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

Como arquivos Markdown podem ser tocados apenas no relatório fora do repositório,
rode `./scripts/markdown-lint.sh` se alterar qualquer `.md` versionado.

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-ADC-S1-report.md` com:

- resumo;
- checklist de aceite;
- arquivos alterados;
- fragmentos antes/depois;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Pare após concluir o slice.
