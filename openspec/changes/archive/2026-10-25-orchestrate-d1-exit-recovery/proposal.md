# Proposal: orchestrate-d1-exit-recovery

## Why

O timer systemd do D-1 (05:00 `America/Bahia`, seis tentativas de dez
minutos) colide estruturalmente com o orquestrador adaptativo: durante a
madrugada o orquestrador encadeia ciclos com batches longos, e em produção
(2026-09-06) todas as seis tentativas falharam com `75` (`busy`) contra
batches de ~1000 runs. Quem conhece o estado da fila é o orquestrador; um
timer de calendário só pode adivinhar janelas. A operação confirmou que a
janela 01:00–05:00 tem movimentação mínima no legado — atrasar o primeiro
ciclo do censo nessa janela para executar o D-1 é imperceptível.

## What Changes

- O `run_loop` do orquestrador adaptativo executa o runtime D-1
  (`run_exit_reconciliation_runtime --mode d1`) **in-process** via
  `call_command`, imediatamente antes de abrir um novo ciclo, quando: o
  loop está `eligible` (fila drenada + batch fechado), a hora Bahia está em
  `[01:00, 05:00)`, e o D-1 ainda não rodou na data corrente nesta
  execução do processo (flag em memória).
- Uma tentativa por dia; falha do D-1 é registrada com saída agregada e
  **não bloqueia** o ciclo de censo.
- O requisito canônico deixa de ser o timer 05:00: a spec
  `production-exit-reconciliation-runtime` é modificada para descrever a
  execução orquestrada, e o scheduler manual permanece como fallback
  documentado (sem mudanças de código no scheduler).
- Produção: o timer `sirhosp-historical-recovery.timer` é desabilitado
  (operação), e a ADR-0010 registra a decisão.

## Impact

- **Código**: `apps/census/orchestration.py` (inserção de passo no
  `run_loop`); testes unitários novos. Nenhuma migration, nenhum modelo
  novo, nenhuma mudança no runtime de reconciliação (S11 intocado) nem no
  scheduler.
- **Specs**: `adaptive-census-orchestration` (novo requisito do passo D-1),
  `production-exit-reconciliation-runtime` (requisito do D-1 modificado de
  timer para orquestrado).
- **Docs**: ADR-0010; deploy/README (seção do agendamento).
- **Implícito**: o horário da execução diária passa a ser variável dentro da
  janela — monitoramento olha coverage/health, não timestamp de calendário.
