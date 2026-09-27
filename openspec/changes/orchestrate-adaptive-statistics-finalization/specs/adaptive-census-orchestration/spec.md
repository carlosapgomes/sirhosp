## ADDED Requirements

### Requirement: Orchestrator finalizes D-1 statistics after adaptive recovery

O loop adaptativo SHALL tornar a data local D-1 pendente para finalização após
sua tentativa diária de recuperação D-1 e SHALL materializá-la uma única vez
por processo na primeira iteração em que não existam runs `queued`/`running`
nem batch de censo aberto. Depois das 05:00 `America/Bahia`, se o processo atual ainda não tentou essa
data, o loop MUST usar a ausência de revisão `ready` para D-1 como marcador
durável de uma finalização perdida por restart e SHALL fazer uma tentativa de
recuperação na primeira drenagem segura. A materialização MUST ocorrer antes da recuperação intradiária
e da abertura do próximo ciclo censitário.

#### Scenario: D-1 termina sem ocupar a fila

- **WHEN** o loop elegível conclui a tentativa D-1 da data Bahia corrente
- **AND** a reavaliação confirma fila drenada e nenhum batch aberto
- **THEN** o sistema materializa explicitamente a data local anterior
- **AND** somente depois prossegue para a recuperação intradiária e o próximo
  ciclo censitário

#### Scenario: D-1 deixa processamento pendente

- **WHEN** a tentativa D-1 termina com runs ativos ou batch aberto
- **THEN** o sistema não chama a materialização naquele instante
- **AND** preserva a data-alvo pendente
- **AND** chama a materialização uma única vez na primeira iteração posterior em
  que a fila esteja drenada e nenhum batch esteja aberto

#### Scenario: Loop permanece bloqueado

- **WHEN** existe uma data estatística pendente e a fila ou o batch continuam
  ocupados
- **THEN** o loop apenas observa e espera conforme sua cadência normal
- **AND** não repete tentativas de materialização enquanto o bloqueio existir

#### Scenario: Recovery fails before finalization

- **WHEN** a recuperação D-1 falha com uma exceção ou saída não bem-sucedida
- **THEN** a data D-1 ainda se torna pendente para materialização
- **AND** a chamada de materialização carrega o aviso técnico enumerado
  `d1_recovery_incomplete`
- **AND** o ciclo censitário não é abortado por essa falha

#### Scenario: Process restarts after the quiet window with no report

- **WHEN** o processo inicia ou reinicia a partir das 05:00 `America/Bahia`
- **AND** a data D-1 é igual ou posterior à ativação
- **AND** não existe revisão `ready` para essa data
- **AND** o processo atual ainda não tentou materializar essa data
- **THEN** o sistema trata D-1 como finalização pendente
- **AND** chama a materialização uma única vez por processo na primeira
  drenagem segura com o aviso `d1_recovery_not_confirmed`
- **AND** não executa novamente a recuperação D-1 fora de sua janela

#### Scenario: Process restarts after the quiet window with a ready report

- **WHEN** o processo inicia ou reinicia a partir das 05:00 `America/Bahia`
- **AND** já existe revisão `ready` para D-1
- **THEN** o sistema não cria pendência de recuperação para essa data
- **AND** não chama a materialização apenas por causa do restart

#### Scenario: Finalization fails

- **WHEN** a materialização falha ou a data não possui janela censitária
  completa
- **THEN** o loop registra somente a classe técnica e a data-alvo agregada
- **AND** considera consumida a tentativa lógica daquela data nesta execução do
  processo
- **AND** a recuperação pós-05:00 não tenta a mesma data novamente nesse
  processo
- **AND** prossegue para o ciclo censitário sem inventar relatório

#### Scenario: Process restarts inside the quiet window

- **WHEN** o processo reinicia dentro da janela D-1 depois de uma tentativa
  anterior
- **THEN** uma nova execução idempotente do D-1 e da mesma data estatística é
  permitida
- **AND** fontes inalteradas não duplicam a revisão corrente

#### Scenario: Statistics activation is absent or target predates it

- **WHEN** a fronteira estatística não está configurada ou a data D-1 precede a
  fronteira declarada
- **THEN** nenhuma pendência ou chamada estatística é criada para essa data
- **AND** nenhum relatório anterior à ativação é criado
- **AND** o orquestrador continua seus ciclos normais com saída agregada
