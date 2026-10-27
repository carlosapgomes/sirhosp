# Tasks: orchestrate-date-only-death-recovery

## 1. SLICE-ODR-S1 — Passo de óbitos date-only no runtime D-1

- [x] 1.1 RED: testes do passo D-1 (fecha match único da data com marcador + portadora + proveniência runtime; ambíguo/não-resolvido sem
      escrita e contabilizado; exceção em um registro não aborta os
      demais; sem registros na data → marker com zero; falha total → sem
      marker e sem abortar o recovery; `--mode hourly` inalterado como
      regressão)
- [x] 1.2 GREEN: passo pós-extração no `run_exit_reconciliation_runtime
    --mode d1` (D1/D2/D3/D5) + marker `mode=d1-deaths` em
      `apps/census/orchestration.py` (D4)
- [x] 1.3 Verificação local + gates do slice
      (worker: 16 unit do passo + 14 integração afetados + regressões;
      controller: quality-gate completo — ver evidence)

## 2. Encerramento (controller)

- [x] 2.1 Review independente do slice (worker fresh + reviewer fresh;
      fix cycle P0/P1 máx. 2 rodadas) — REQUEST_CHANGES 1ª (P1 side
      effects) → correção dirigida → ACCEPT 2ª
- [x] 2.2 Gate final do change (quality-gate completo + integration)
      (2026-10-25 em 413a38e: unit 4409, integration 1072, ruff, mypy 487
      — evidence/final-gate.md)
- [x] 2.3 Release e deploy; observação da primeira noite (janela
      01:00–05:00): marker `mode=d1-deaths result=success` presente,
      episódios da data fechados por morte com marcador, sem regressão
      nas altas D-1; registro no evidence pack da release
      (2026-10-27: rc.42 deployada 2026-10-26; primeira noite OK — marker
      com contagens agregadas, 4 óbitos da data já fechados por via de
      ingest (pré-existente, rc.41), passo sem escritas, altas sem
      regressão; evidência em `docs/releases/2026-10-25_v0.1.0-rc.42.md`)

## Sequência e autoridade

Reuso integral de `reconcile_death_record` (sem lógica nova de matching).
Guardrails do backfill NÃO se aplicam ao passo (volume limitado pela
própria data, D5) — o comando delimitado permanece para massa histórica.
Sem mudanças em `/painel/`, `/obitos` (`DailyDeathCount`) ou indicadores
de altas (D6).
