## ADDED Requirements

### Requirement: Orchestrator runs quiet-window D-1 exit recovery

O loop do orquestrador adaptativo SHALL executar o runtime de recuperação
D-1 (`run_exit_reconciliation_runtime --mode d1`) in-process, imediatamente
antes de abrir um novo ciclo, quando o loop está elegível (fila drenada e
nenhum batch de censo aberto), a hora local está na janela silenciosa
`[01:00, 05:00)` em `America/Bahia` literal, e a tentativa D-1 daquela data
local ainda não ocorreu nesta execução do processo.

#### Scenario: Quiet-window eligible loop triggers D-1 before the cycle

- **WHEN** o loop está elegível às 02:30 `America/Bahia` e nenhum D-1 foi
  tentado naquela data local nesta execução do processo
- **THEN** o runtime `--mode d1` executa in-process via `call_command`
  antes da abertura do próximo ciclo de censo
- **AND** o início, o fim e a duração do passo são logados em saída
  agregada, com data local Bahia explícita
- **AND** o ciclo de censo seguinte executa normalmente após o passo

#### Scenario: Outside the quiet window

- **WHEN** o loop está elegível às 00:59, 05:00 ou 14:00 `America/Bahia`
- **THEN** o passo D-1 não executa e o ciclo de censo segue direto

#### Scenario: One attempt per local date

- **WHEN** o passo D-1 já foi tentado para a data local Bahia corrente
  nesta execução do processo
- **THEN** iterações elegíveis subsequentes no mesmo dia não executam o
  D-1 novamente

#### Scenario: D-1 failure never blocks census cycles

- **WHEN** o runtime D-1 levanta uma exceção durante o passo
- **THEN** a exceção é capturada e registrada em saída agregada sem
  abortar o loop
- **AND** o ciclo de censo programado executa normalmente

#### Scenario: Blocked loop never triggers D-1

- **WHEN** o loop não está elegível (fila ativa, batch aberto, cooldown ou
  stale running)
- **THEN** o passo D-1 não executa
