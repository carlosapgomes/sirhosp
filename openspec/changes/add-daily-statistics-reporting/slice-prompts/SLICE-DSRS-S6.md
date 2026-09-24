# SLICE-DSRS-S6 — Página e navegação autorizadas

## Handoff de entrada

Você inicia com contexto zero após DSRS-S5 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, as decisões 7–9 de `design.md`, os
requisitos de autorização, default de data, collapsibles, badges e ordenação,
a delta `services-portal-navigation` e os relatórios S1–S5 em `/tmp`. Use
`/beds/` somente como padrão visual; não copie cálculos de ocupação.

## Objetivo

Entregar `/statistics/` somente leitura, protegida por permissão, com data
default segura, período/qualidade explícitos e accordions por setor consumindo
exclusivamente a revisão materializada.

## Requisitos verificáveis

- **R1:** rota canônica `/statistics/` exige autenticação e permissão de consulta;
  negação não renderiza identidade.
- **R2:** sem data, seleciona ontem se pronto, senão o último dia pronto, nunca
  hoje; data indisponível tem estado explícito.
- **R3:** resposta nominal usa política `private, no-store`.
- **R4:** setor mostra badges persistidos de pacientes, capacidade, lotação,
  saldo ou excedente sem recalcular métricas.
- **R5:** accordion do setor contém entradas, saídas, eventos com origem ou
  destino não identificado e pacientes; cada lista mantém badge zero e estado
  vazio quando aplicável.
- **R6:** controles de collapse preservam rótulos e estados acessíveis.
- **R7:** pacientes/eventos usam ordenação natural compartilhada.
- **R8:** item `Estatísticas` aparece somente com permissão, entre `Leitos` e
  `Fluxo Hospitalar`, e fica ativo na rota.
- **R9:** orçamento de queries não cresce linearmente com setores/eventos.

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/urls.py
  - apps/statistics_reports/views.py
  - apps/statistics_reports/presentation.py
  - apps/statistics_reports/templates/statistics_reports/daily_report.html
  - config/urls.py
  - templates/includes/sidebar.html
  - tests/integration/test_daily_statistics_page.py
allowed_incidental_files: []
out_of_scope:
  - XLSX e log de exportação
  - edição, correção ou aprovação manual
  - cálculos oficiais no template/view
  - mudanças visuais amplas em /beds
  - systemd e produção
```

Limite: sete arquivos. Pare se precisar duplicar o grafo do catálogo, expor a
página apenas por `is_staff` ou aumentar queries por setor.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R3 | urls/view | auth, permission, default e headers |
| R4–R7 | presentation/template | badges, collapses, vazios e sort |
| R8 | sidebar/view | ordem, visibilidade e estado ativo |
| R9 | view/projection | teste de query budget com volumes distintos |

## Plano de testes

### RED

Crie os testes primeiro e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_page.py
```

Falha esperada: rota/menu/template inexistentes e ausência dos contratos de
autorização/apresentação.

### GREEN / verificação local

Implemente o mínimo e repita o RED. Depois:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_materialization.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R9 cobertos por RED→GREEN.
- [ ] HTML e menu não expõem identidade sem permissão.
- [ ] View/template não recalculam ocupação.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S6-report.md`.
- [ ] Checks e Markdown alterado passam.
