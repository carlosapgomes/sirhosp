# SLICE-SCPED-S1 — Gráfico principal por saída capturada

## Handoff de entrada

Você inicia com contexto zero no repositório SIRHOSP. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, o `proposal.md`, as decisões 1–3 de `design.md` e a delta
spec deste change. Implemente somente este slice com TDD. Não acesse nem altere
produção e não execute backfill.

## Objetivo

Fazer `/painel/altas/` apresentar apenas saídas efetivas capturadas por
`DischargeRecord.saida_em`, com eixo de dias consecutivos, médias móveis,
diferenciação de fim de semana e análise horária por saída.

## Requisitos verificáveis

- **R1:** o gráfico principal contém uma única série de eventos, baseada em
  `saida_em`, e não contém série `alta_em` nem série reconciliada.
- **R2:** todo registro com `saida_em` entra na contagem, independentemente de
  `reconciliation_status`.
- **R3:** `?dias=N` produz N dias consecutivos até ontem; data sem registro entra
  com zero e participa das médias.
- **R4:** SMA-7, EMA-7, SMA-30, weekday average e cores de fim de semana usam a
  mesma série de saídas capturadas.
- **R5:** distribuição horária e resumo por especialidade usam a hora de
  `saida_em`, com limites explícitos de `America/Bahia`.
- **R6:** fixtures são sintéticas e nenhuma identidade aparece em logs ou
  artefatos.

## Escopo e blast radius

```yaml
expected_files:
  - apps/services_portal/views.py
  - apps/services_portal/templates/services_portal/discharge_chart.html
  - tests/integration/test_discharge_indicators.py
  - tests/unit/test_services_portal_dashboard.py
allowed_incidental_files: []
out_of_scope:
  - dashboard card
  - discharge list
  - reconciliation quality surface
  - models, migrations, backfill, production
```

Pare e reporte bloqueio se precisar exceder quatro arquivos ou alterar
`DailyDischargeCount`, modelos ou regras de reconciliação.

## Plano de testes

### RED

Altere primeiro os testes focados para R1–R5 e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_discharge_indicators.py
./scripts/test-in-container.sh unit \
  tests/unit/test_services_portal_dashboard.py
```

Registre a falha pelo comportamento antigo (`DailyDischargeCount`/`alta_em`).

### GREEN

Implemente o mínimo e repita os mesmos comandos. Depois execute:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R5 cobertos por testes que falharam antes e passam depois.
- [ ] Nenhum comportamento fora do gráfico foi antecipado.
- [ ] Nenhum dado real, migration ou mudança de produção.
- [ ] Relatório criado em `/tmp/sirhosp-slice-SCPED-S1-report.md`.
- [ ] `./scripts/markdown-lint.sh` passa para Markdown alterado.
