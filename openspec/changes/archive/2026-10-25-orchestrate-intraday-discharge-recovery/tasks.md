# Tasks: orchestrate-intraday-discharge-recovery

## 1. SLICE-OIDR-S1 — Passo intraday throttled no loop

- [x] 1.1 RED: testes do passo intraday (hora nova executa antes do ciclo;
      mesma hora não repete; hora seguinte repete; falha isolada; blocked
      jamais; coexistência com D-1 com D-1 primeiro)
- [x] 1.2 GREEN: guard `last_hourly_run_hour` no `run_loop` de
      `apps/census/orchestration.py` reutilizando `now_fn` e isolamento
      try/except do passo D-1
- [x] 1.3 Gates do slice: check + unit + lint + typecheck;
      `openspec validate orchestrate-intraday-discharge-recovery --strict`

## 2. Encerramento (controller)

- [x] 2.1 Review independente (worker fresh implementa; reviewer fresh
      valida R1..Rn; fix cycle P0/P1 máx. 2 rodadas)
- [x] 2.2 Gate final do change (quality-gate completo)
- [x] 2.3 Release e runbook: desabilitar `sirhosp-discharges.timer` em
      produção após o deploy; registrar no evidence pack de ativação
      (verificado 2026-10-25 no upgrade rc.40: timer
      `sirhosp-discharges.timer` `disabled`/`inactive` em produção;
      fallback documentado no `deploy/README.md`)
- [x] 2.4 Observar o primeiro dia intraday orquestrado (cards do dia
      corrente atualizando por hora)
      (registro tardio, 2026-10-25: verificação em produção mostra o ciclo
      adaptativo executando a recuperação intraday por hora — 17 markers
      `mode=hourly-discharges result=success` nas últimas 26h)
