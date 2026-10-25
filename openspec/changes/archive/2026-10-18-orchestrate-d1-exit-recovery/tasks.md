# Tasks: orchestrate-d1-exit-recovery

## 1. SLICE-ODER-S1 — Passo D-1 no loop do orquestrador

- [x] 1.1 Testes unitários do passo D-1 (RED): janela quieta `[01:00, 05:00)`
      Bahia via relógio injetável; execução única por data local;
      `call_command` antes de `run_single_cycle`; falha não bloqueia;
      blocked nunca dispara; boundaries 00:59/01:00/04:59/05:00
- [x] 1.2 Implementação mínima em `apps/census/orchestration.py` (GREEN):
      constantes de janela, flag em memória, try/except com log agregado
- [x] 1.3 Refactor controlado sem mudança de comportamento
- [x] 1.4 Gates: `check`, `unit`, `lint`, `typecheck` verdes; spec delta
      valida em `openspec validate --strict`
- [x] 1.5 Relatório do slice em `/tmp/sirhosp-slice-ODER-S1-report.md`

## 2. Encerramento (controller)

- [x] 2.1 ADR-0010 revisada para Accepted no commit do slice
      (verificado 2026-10-18: `docs/adr/ADR-0010-recuperacao-d1-orquestrada-pelo-ciclo-adaptativo.md`
      Status Accepted, aceita em 2026-09-07)
- [x] 2.2 deploy/README: seção de agendamento atualizada (D-1 orquestrado;
      timer desabilitado; scheduler = fallback)
      (verificado 2026-10-18: seção de agendamento documenta o ciclo
      adaptativo e a tabela de fallback com os seis units)
- [x] 2.3 Release rc.22 e deploy do orquestrador na sequência da operação
      (deploy concluído na sequência da operação em set/2026, era rc.24;
      orquestrador contínuo em produção desde então — hoje rc.40,
      container ativo verificado 2026-10-18)
- [x] 2.4 Observação da primeira noite (janela 01:00–05:00) e registro no
      pack de ativação
      (registro tardio, 2026-10-18: a observação específica da primeira
      noite não foi registrada na época; estado atual verificado em
      produção — loop adaptativo ativo, 17 markers
      `mode=hourly-discharges result=success` nas últimas 26h e
      relatórios diários materializados consecutivamente, o que na
      arquitetura OASF pressupõe o D-1 concluído por data local)
