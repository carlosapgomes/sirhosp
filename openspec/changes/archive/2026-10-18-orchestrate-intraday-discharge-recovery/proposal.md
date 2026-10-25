# Proposal: orchestrate-intraday-discharge-recovery

## Why

O timer `:13` (discharges intraday) disputa as mesmas janelas que o
orquestrador adaptativo e, em dias de ciclos encadeados, perde todas as
tentativas: em 2026-09-07 nenhuma das 24 janelas executou (12+ tentativas
`busy`; a execução manual de fim de tarde esgotou os 6 retries contra uma
fila de ~650 runs). O dashboard do dia corrente só atualiza de madrugada
pelo D-1. É o mesmo fenômeno estrutural que motivou a ADR-0010 para o
D-1: quem conhece o estado da fila deve disparar o runtime.

## What Changes

- O `run_loop` do orquestrador passa a disparar o runtime
  `run_exit_reconciliation_runtime --mode hourly` **in-process**
  (`call_command`), com throttle de **uma execução por hora local
  `America/Bahia`** por processo, no mesmo ponto do passo D-1
  (imediatamente após `eligible`, antes de abrir o próximo ciclo).
- Falha do passo hourly **nunca bloqueia** o ciclo de censo (mesma
  isolamento do D-1: `try/except` amplo com log agregado).
- O requisito canônico de extração intraday deixa de ser o timer `:13`:
  a spec `production-exit-reconciliation-runtime` passa a descrever a
  execução orquestrada; o timer/systemd permanece instalado como
  **fallback manual** (desabilitado em produção).
- Sem migrations, sem modelos novos, sem mudanças no runtime S11 nem no
  scheduler.

## Impact

- **Código**: `apps/census/orchestration.py` (guard hourly no `run_loop`);
  testes unitários novos.
- **Specs**: `adaptive-census-orchestration` (ADDED requirement do passo
  intraday), `production-exit-reconciliation-runtime` (MODIFIED do
  requisito hourly).
- **Operação**: após deploy, desabilitar `sirhosp-discharges.timer`
  (registro no runbook da release); o `:47` stale sweep não muda.
- **Efeito esperado**: o card "Saídas hospitalares no dia" passa a
  atualizar ao longo do dia (uma extração por hora nos momentos de fila
  drenada, tipicamente entre ciclos).
