# SLICE-ADC-S3: Navegação a partir das listagens e hardening final

## Handoff para executor LLM

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/admission-death-chart-pages/proposal.md`
4. `openspec/changes/admission-death-chart-pages/design.md`
5. `openspec/changes/admission-death-chart-pages/tasks.md`
6. `openspec/changes/admission-death-chart-pages/specs/services-portal-navigation/spec.md`
7. relatórios `/tmp/sirhosp-slice-ADC-S1-report.md` e
   `/tmp/sirhosp-slice-ADC-S2-report.md`, se existirem

Implemente somente o Slice ADC-S3.

## Objetivo

Tornar os gráficos descobríveis a partir das listagens de admissões e óbitos,
sem regredir seletor de data nem retorno ao dashboard.

## Escopo máximo

- `tests/unit/test_services_portal_dashboard.py`
- `apps/services_portal/templates/services_portal/admission_list.html`
- `apps/services_portal/templates/services_portal/death_list.html`
- ajustes mínimos em view/urls somente se algum link reverso estiver ausente

Se precisar alterar mais arquivos, pare e reporte bloqueio.

## TDD obrigatório

1. Escreva testes RED para:
   - link `Ver gráfico de admissões` na listagem de admissões;
   - link `Ver gráfico de óbitos` na listagem de óbitos;
   - preservação do seletor de data;
   - preservação do botão de retorno ao dashboard.
2. Rode o teste específico e confirme falha.
3. Implemente os botões nos templates.
4. Faça hardening final de labels e estados vazios.

## Validação

Executar no final do slice:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-ADC-S3-report.md` com:

- resumo;
- checklist de aceite;
- arquivos alterados;
- fragmentos antes/depois;
- comandos executados e resultados;
- riscos, pendências e próximo passo sugerido.

Pare após concluir o slice.
