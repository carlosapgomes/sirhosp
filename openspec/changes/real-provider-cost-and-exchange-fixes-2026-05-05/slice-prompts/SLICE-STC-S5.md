# SLICE STC-S5 — Câmbio USD/BRL: correção de providers

## Handoff de entrada

Leia: `AGENTS.md`, `PROJECT_CONTEXT.md`, proposal/design/tasks da change,
`/tmp/sirhosp-slice-STC-S1-report.md` (contrato de parsing), e este arquivo.

## Objetivo

Corrigir o comando `sync_exchange_rates` para que a cotação USD/BRL volte a
ser persistida no banco, habilitando exibição de BRL na UI.

## Problemas identificados (Slice S1)

1. **Frankfurter (primário):** URL `api.frankfurter.dev/latest?...` → 404.
   URL correta: `api.frankfurter.dev/v1/latest?...`.
2. **ExchangeRate-API (fallback):** parser espera `data["rates"]["BRL"]`
   mas API retorna `data["conversion_rates"]["BRL"]`.

## Escopo permitido

- `apps/summaries/management/commands/sync_exchange_rates.py`
- `tests/unit/test_exchange_rate_sync_command.py`

## TDD

1. Ajustar testes para endpoints/parsers corretos (RED se quebrados).
2. Corrigir código (GREEN).
3. Rodar `sync_exchange_rates` no container dev para validar.

## Gates

- `./scripts/test-in-container.sh check`
- `./scripts/test-in-container.sh unit`
- `./scripts/test-in-container.sh lint`

## Relatório

`/tmp/sirhosp-slice-STC-S5-report.md`
