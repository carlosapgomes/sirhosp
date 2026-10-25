# SLICE-SCPED-S2 — Card e listagem por saída capturada

## Handoff de entrada

Você inicia com contexto zero no repositório SIRHOSP. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, os artefatos deste change e o relatório
`/tmp/sirhosp-slice-SCPED-S1-report.md`. Confirme que S1 está concluído antes de
editar. Implemente somente este slice com TDD. Não acesse produção nem execute
backfill.

## Objetivo

Alinhar o card diário e a listagem acessada pelo gráfico à métrica gerencial de
`saida_em`, removendo do dashboard principal a competição com o indicador de
sumários.

## Requisitos verificáveis

- **R1:** o card do dia conta `DischargeRecord.saida_em` na data Bahia corrente,
  inclusive evidência pendente, ambígua ou em conflito.
- **R2:** `alta_em` sem `saida_em` não entra no card de saída.
- **R3:** o dashboard não apresenta sumários como segundo card primário de alta.
- **R4:** a listagem de uma data consulta `DischargeRecord` por `saida_em` local e
  seu total coincide com o gráfico.
- **R5:** a listagem não depende de `daily_count`, `records` ou `raw_data`.
- **R6:** autenticação e proteção de identidade existentes são preservadas.

## Escopo e blast radius

```yaml
expected_files:
  - apps/services_portal/views.py
  - apps/services_portal/templates/services_portal/dashboard.html
  - apps/services_portal/templates/services_portal/discharge_list.html
  - tests/unit/test_services_portal_dashboard.py
  - tests/integration/test_discharge_indicators.py
allowed_incidental_files: []
out_of_scope:
  - reconciliation quality surface
  - models, migrations, backfill, production
```

Limite de cinco arquivos. Pare se a coerência da listagem exigir schema ou
mudança de autorização não prevista.

## Plano de testes

### RED

Adicione testes R1–R5 e execute:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_services_portal_dashboard.py
./scripts/test-in-container.sh integration \
  tests/integration/test_discharge_indicators.py
```

### GREEN

Implemente o mínimo, repita os testes focados e execute:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R5 passam com fixtures sintéticas.
- [ ] Card, gráfico e lista compartilham a semântica `saida_em`.
- [ ] Nenhuma mudança em reconciliação ou persistência.
- [ ] Relatório criado em `/tmp/sirhosp-slice-SCPED-S2-report.md`.
- [ ] `./scripts/markdown-lint.sh` passa.
