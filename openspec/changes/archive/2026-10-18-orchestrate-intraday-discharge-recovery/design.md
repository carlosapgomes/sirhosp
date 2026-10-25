# Design: orchestrate-intraday-discharge-recovery

## Contexto

ADR-0010 estabeleceu o padrão: o orquestrador, dono do estado da fila,
executa o runtime de reconciliação in-process quando `eligible` (fila
drenada + batch fechado). Este change replica o padrão para a extração
intraday de altas (`--mode hourly`), eliminando a disputa de janelas do
timer `:13`.

## Decisões

### D1. Mesmo ponto de inserção, guard independente

O passo hourly executa no mesmo bloco eligible (antes do `run_single_cycle`),
com guard próprio: `last_hourly_run_hour != hora_local_bahia_atual`
(throttle de 1×/hora por processo). Intencionalmente independente do guard
D-1 (data) — ambos podem disparar na mesma iteração (D-1 primeiro, pois
cobre o dia anterior completo; hourly depois).

### D2. Throttle por hora, sem cooldown extra

Uma extração por hora é suficiente para o dashboard intraday (o legado
publica altas ao longo do dia; latência ≤1h é aceitável para a operação).
Flag em memória (`last_hourly_run_hour: int | None`) — restart pode
re-executar dentro da mesma hora; inofensivo (runtime idempotente por data,
advisory locks previnem concorrência).

Risco residual aceito (review OIDR-S1): a chave é hora-do-dia, não
`(data, hora)` — se o loop só for elegível na mesma hora-do-dia em dias
consecutivos (cenário patológico de janela de censo aberta ~24h), a
extração intraday do dia seguinte é adiada até a próxima hora elegível.
Em operação normal o loop é elegível a cada ≤30min e o caso não ocorre;
`America/Bahia` não tem DST desde 2019, então a chave nunca “alia”.
Mudar para `(data, hora)` fica como follow-up opcional de uma linha.

### D3. Isolamento idêntico ao D-1

`try/except (Exception, SystemExit)` com log agregado
(`intraday hourly recovery failed: <ExceptionType>`); início/fim logados
com hora local e duração. Falha nunca aborta o loop nem o ciclo.

### D4. Timer `:13` vira fallback

Sem mudança no scheduler/units (continuam funcionando). A operação
desabilita `sirhosp-discharges.timer` após o deploy; se o orquestrador
estiver parado por manutenção, o timer pode ser reabilitado como caminho
manual. O `:47` (stale sweep, sem Playwright) permanece como está.

### D5. Relogio injetável reaproveitado

O `now_fn` injetado (introduzido no passo D-1) também alimenta o guard
hourly — mesma técnica, sem nova injeção.

## Riscos e alternativas

- **Extração extra por ciclo?** Não: throttle por hora limita a ~1×/h; o
  custo observado é ~3 min de Playwright por execução.
- **Aumentar retries do timer `:13`** (rejeitado): não resolve contenção
  de ciclos encadeados; a spec S12 fixa 6×600s por decisão registrada.
- **Hourly como run enfileirado** (rejeitado pelos mesmos motivos da
  ADR-0010).

## Plano de teste

Unitário (mocks idênticos aos do passo D-1, arquivo
`tests/unit/test_orchestrator_intraday_hourly.py`):

1. eligible em hora nova → `call_command hourly` ANTES do ciclo; flag
   atualizada.
2. mesma hora, segunda iteração elegível → não repete.
3. hora seguinte → executa de novo (throttle por hora, não por dia).
4. falha (`RuntimeError`/`SystemExit`) → ciclo executa; loop segue.
5. blocked → jamais dispara.
6. coexistência: iteração com D-1 e hourly na mesma janela → ambos, D-1
   primeiro.
