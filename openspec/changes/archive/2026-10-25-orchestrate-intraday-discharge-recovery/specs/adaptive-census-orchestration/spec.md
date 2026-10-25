## ADDED Requirements

### Requirement: Orchestrator runs throttled intraday discharge recovery

O loop do orquestrador adaptativo SHALL executar o runtime de extração
intraday de altas (`run_exit_reconciliation_runtime --mode hourly`)
in-process, no bloco elegível e antes de abrir o próximo ciclo, com no
máximo uma execução por hora local `America/Bahia` por execução do
processo.

#### Scenario: Eligible loop in a new local hour triggers hourly

- **WHEN** o loop está elegível e a hora local `America/Bahia` difere da
  última hora em que o passo intraday executou neste processo
- **THEN** o runtime `--mode hourly` executa in-process antes da abertura
  do próximo ciclo de censo
- **AND** início, fim e duração são logados em saída agregada com hora
  local explícita
- **AND** o ciclo de censo seguinte executa normalmente

#### Scenario: Same local hour does not repeat

- **WHEN** o passo intraday já executou na hora local corrente
- **THEN** iterações elegíveis subsequentes na mesma hora não executam o
  passo novamente

#### Scenario: Next local hour triggers again

- **WHEN** uma iteração elegível ocorre em hora local posterior à última
  execução
- **THEN** o passo intraday executa novamente (o throttle é por hora, não
  por dia)

#### Scenario: Failure never blocks census cycles

- **WHEN** o runtime hourly levanta exceção durante o passo
- **THEN** a exceção é capturada e registrada em saída agregada sem
  abortar o loop
- **AND** o ciclo de censo programado executa normalmente

#### Scenario: Blocked loop never triggers the step

- **WHEN** o loop não está elegível
- **THEN** o passo intraday não executa

#### Scenario: D-1 and intraday may run in the same iteration

- **WHEN** uma iteração elegível satisfaz os guards do D-1 (janela
  quieta, data nova) e do passo intraday (hora nova)
- **THEN** ambos executam, o D-1 primeiro e o intraday depois, antes do
  ciclo
