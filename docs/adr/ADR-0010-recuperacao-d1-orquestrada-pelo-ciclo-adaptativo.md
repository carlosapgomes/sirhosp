# ADR-0010: Recuperação D-1 orquestrada pelo ciclo adaptativo de censo

- **Status:** Proposed
- **Data:** 2026-09-06
- **Contexto de decisão:** incidente de contenção do timer D-1 em produção
  (2026-09-06, ver `docs/releases/2026-09-05_v0.1.0-rc.21.md` e o pack de
  ativação em andamento)
- **Decisões relacionadas:** ADR-0009 (reconciliação canônica), change
  arquivado `reconcile-patient-exits-and-stale-admissions` (S11/S12)

## Contexto

O runtime de recuperação D-1 (`run_exit_reconciliation_runtime --mode d1`)
sai com `75` quando existe fila ativa ou batch de censo aberto — contenção
real, por design (S11). O agendamento systemd (S12) às 05:00
`America/Bahia` com seis tentativas de dez minutos mostrou-se
estruturalmente insuficiente em produção: o orquestrador adaptativo encadeia
ciclos durante a madrugada com batches longos (observado em 2026-09-06:
quatro tentativas consecutivas colidiram com batches de ~1000 runs; a quinta
e sexta também falharam). Quem conhece o estado da fila é o orquestrador; um
timer de calendário não tem essa informação e só pode adivinhar janelas.

## Decisão

1. O **orquestrador adaptativo** (`run_loop` de `apps/census/orchestration.py`)
   passa a executar o D-1 **in-process** (`call_command` do runtime de
   reconciliação) imediatamente **antes de abrir um novo ciclo**, quando:
   - o loop está `eligible` (fila drenada e batch fechado — exatamente os
     critérios que o runtime exige);
   - a hora local `America/Bahia` está na janela silenciosa
     `[01:00, 05:00)`;
   - o D-1 ainda não foi executado naquela execução do processo (flag em
     memória por data local Bahia).
2. Uma **tentativa por dia**. Falha do D-1 **não bloqueia** o ciclo de censo:
   registra-se o erro agregado e o loop segue; a próxima tentativa é no dia
   seguinte (ou manual via scheduler).
3. O **timer systemd 05:00 é desabilitado** em produção. O scheduler
   (`exit-reconciliation-scheduler.sh`) permanece como caminho manual e para
   catch-up; os timers `:13`/`:47` (se habilitados) seguem independentes —
   têm 24 janelas por dia e contenção autolimitada, diferente do D-1, que
   tinha uma única chance diária.
4. **Sem persistência nova**: re-execução após restart dentro da janela é
   aceitável — o runtime é idempotente por data (extratores re-extraem;
   eventos de reconciliação são append-only e a leitura canônica usa o
   evento reconciled mais recente), e locks advisory já previnem execução
   concorrente.

## Consequências

- O D-1 deixa de disputar janelas às cegas: executa exatamente quando o
  sistema está drenado, na janela de menor movimentação do legado (a
  operação relatou alteração mínima entre 01:00 e 04:00; atraso de um ciclo
  de censo nessa janela é imperceptível).
- O orquestrador assume mais uma responsabilidade (acoplamento consciente;
  inverte parcialmente a motivação S12 de desacoplamento via systemd — o
  systemd se mantém para o que não depende do estado da fila).
- O custo de um D-1 (~7 min observados) atrasa em igual medida o primeiro
  ciclo da madrugada — aceito pela janela silenciosa.
- Horário da execução passa a ser variável (dentro da janela), não fixo:
  monitoramento passa a olhar o resultado diário (coverage/health), não um
  timestamp de calendário.
