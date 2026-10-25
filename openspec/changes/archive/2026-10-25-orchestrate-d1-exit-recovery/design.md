# Design: orchestrate-d1-exit-recovery

## Contexto

Ver ADR-0010 (`docs/adr/ADR-0010-recuperacao-d1-orquestrada-pelo-ciclo-adaptativo.md`)
para a decisão completa e o incidente que a motivou. Este design define os
detalhes de implementação.

## Objetivos e não-objetivos

- **Objetivo**: o D-1 diário executa no momento em que o próprio orquestrador
  certifica que a fila está drenada e o batch fechado, dentro da janela
  silenciosa `[01:00, 05:00) America/Bahia`.
- **Não-objetivo**: mudar o runtime de reconciliação (S11), o scheduler
  manual, os modos `hourly`/`catchup`, ou adicionar qualquer persistência
  nova (a decisão é explicitamente sem migrations e sem modelos novos).

## Decisões de design

### D1. Ponto de inserção: após `eligible`, antes do ciclo

O `run_loop` já avalia elegibilidade via `compute_orchestrator_state`
(fila ativa, batch aberto, cooldown e stale-running bloqueiam). Quando
`decision.eligible` é `True`, os critérios exigidos pelo runtime D-1
(nenhuma run queued/running, nenhum batch aberto) estão garantidos. O passo
D-1 executa exatamente aí, **antes** de `run_single_cycle` abrir o próximo
batch.

### D2. Janela silenciosa e data Bahia

Janela fixa `[01:00, 05:00)` em `America/Bahia` literal (mesma regra do
resto do change RPSA; nunca fuso herdado). Data de referência do D-1 é
calculada pelo próprio runtime (`--mode d1` = data local Bahia anterior).
Constantes do módulo, sem configuração por ambiente (consistente com a
decisão S12 de valores fixos documentados).

### D3. Uma tentativa por dia, em memória

Flag `last_d1_run_date: date | None` local ao `run_loop`, atualizada para a
data Bahia corrente após a tentativa (sucesso **ou** falha — não há retry
intra-dia; o retry era propriedade do scheduler systemd, que sai de cena).
Reexecução após restart do processo dentro da janela é aceitável e segura:
o runtime é idempotente por data (extratores re-extraem; eventos de
reconciliação são append-only e a leitura canônica usa o evento reconciled
mais recente) e os advisory locks do runtime previnem concorrência com o
scheduler manual.

### D4. Falha do D-1 não bloqueia o censo

`call_command` executa em try/except amplo: exceções são logadas com
resumo agregado (`d1 recovery failed: <ExceptionType>`) e o loop prossegue
para o ciclo normal. Exit 75 não ocorre por construção (passo só roda
quando eligible), mas se ocorrer é tratado como falha registrada, igual a
qualquer exceção — nunca aborta o orquestrador.

### D5. Comando e identidade de saída

`call_command("run_exit_reconciliation_runtime", "--mode", "d1")` no mesmo
processo do orquestrador (o serviço `census_orchestrator` herda o anchor
Playwright e as credenciais `SOURCE_SYSTEM_*` por ambiente — nada em argv,
regra S7A preservada). A saída agregada do runtime vai para os logs do
orquestrador; o passo loga início e fim com data Bahia e duração em
segundos.

## Riscos e alternativas consideradas

- **Mover o timer para a janela quieta** (rejeitado pela operação): mantém o
  adivinhamento de janela; a madrugada ainda tem ciclos encadeados.
- **Aumentar tentativas do scheduler** (rejeitado): a contenção observada
  dura mais de uma hora; e a decisão S12 de seis tentativas fixas foi
  deliberada.
- **D-1 como run enfileirado** (rejeitado): o runtime D-1 usa Playwright e
  advisory locks próprios; enfileirar como `IngestionRun` criaria um novo
  intent de fila e acoplaria o agendador ao worker.

## Plano de teste

Unitário (TDD, sem banco real além de fixtures mínimas): mock de
`compute_orchestrator_state`, `run_single_cycle`, `call_command` e relógio
injetável:

1. eligible + 01:00–04:59 Bahia + não executado hoje → `call_command d1`
   ANTES de `run_single_cycle`, uma única vez; flag atualizada.
2. eligible fora da janela → sem D-1; ciclo direto.
3. segunda iteração elegível no mesmo dia → sem segunda execução.
4. `call_command` levanta → exceção capturada, ciclo executa normalmente.
5. Boundary: 00:59 Bahia não executa; 05:00 Bahia não executa; 01:00 e
   04:59 executam (relógio UTC cruzando meia-noite Bahia incluído).
6. `should_stop` / blocked → D-1 jamais chamado.
