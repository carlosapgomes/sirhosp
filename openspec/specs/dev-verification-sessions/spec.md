# dev-verification-sessions Specification

## Purpose

Definir o ciclo operacional de sessões de verificação no desenvolvimento,
com contas exclusivas e credenciais efêmeras revogadas ao encerrar, preservando
o banco fictício e impedindo atuação acidental em produção.

## Requirements

### Requirement: Validate the development target before activation

O controlador SHALL validar o destino de desenvolvimento e a declaração de
dataset fictício antes de modificar contas ou emitir credenciais. Produção,
schema pendente, destino ambíguo e workers ativos MUST bloquear a abertura;
um healthcheck HTTP isolado SHALL NOT ser considerado prova suficiente.

#### Scenario: Development is ready

- **WHEN** o destino local, o banco, o schema e os serviços autorizados são confirmados
- **THEN** a abertura pode prosseguir no dev explicitamente autorizado
- **AND** nenhuma configuração de produção ou serviço compartilhado é alterada

#### Scenario: Production or an ambiguous target is selected

- **WHEN** o alvo é produção ou não corresponde ao desenvolvimento confirmado
- **THEN** o controlador retorna BLOCKED
- **AND** não altera contas, não emite senha e não dirige páginas desse alvo

#### Scenario: Schema is outdated or workers are running

- **WHEN** há migration pendente ou worker ativo
- **THEN** a abertura retorna BLOCKED com diagnóstico sem dados sensíveis
- **AND** não aplica migrations nem inicia/para workers automaticamente

### Requirement: Activate only owned verification accounts

Uma abertura SHALL ativar somente as contas reservadas de verificação, com
perfis comum e administrativo definidos. Contas ausentes SHALL ser criadas;
colisão sem comprovação de ownership MUST bloquear a operação sem adotar
ou alterar uma conta humana.

#### Scenario: Owned accounts are activated

- **WHEN** uma abertura autorizada encontra contas de teste ausentes ou owned
- **THEN** somente essas contas recebem novas credenciais fortes e ficam ativas
- **AND** o usuário comum não ganha permissões administrativas
- **AND** o fluxo normal não obriga uma troca de senha não solicitada

#### Scenario: Reserved name belongs to an unrelated account

- **WHEN** uma conta existente usa o nome reservado sem marcador de ownership
- **THEN** a abertura falha antes de alterar qualquer conta do par
- **AND** a conta existente e suas credenciais permanecem intactas

### Requirement: Use disposable credentials without a permanent password store

As senhas de abertura SHALL ser geradas por execução, distintas e imprevisíveis.
A sessão assistida SHALL permitir sua emissão explícita para o operador/LLM,
com aceitação de exposição temporária no histórico. O modo automático SHALL
consumi-las sem impressão. Arquivos de estado, relatórios e argumentos de
processo MUST NOT conter senhas, cookies ou tokens de sessão.

#### Scenario: A new session starts after closure

- **WHEN** as mesmas contas são abertas em outra execução
- **THEN** as novas senhas não reutilizam as anteriores
- **AND** não é necessário recuperar uma senha permanente de arquivo

#### Scenario: Automated verification obtains credentials

- **WHEN** o runner automático prepara o login
- **THEN** as credenciais são consumidas pelo executor sem constar no relatório
- **AND** somente o hash de autenticação é persistido no banco

### Requirement: Close verification accounts idempotently

O fechamento SHALL desativar as contas owned e tornar suas senhas
inutilizáveis, sem gerar ou emitir uma senha final utilizável. Repetir close
SHALL ser seguro. A revogação SHALL impedir novo login e invalidar a
autenticação de sessões Django anteriores na próxima requisição.

#### Scenario: Closing a session prevents further authentication

- **WHEN** uma sessão é fechada após login de teste
- **THEN** suas contas ficam inativas e sem senha utilizável
- **AND** a senha usada durante o teste não autentica
- **AND** a próxima requisição da sessão antiga perde acesso autenticado

#### Scenario: Close is repeated

- **WHEN** close é executado novamente para uma sessão já encerrada
- **THEN** nenhuma conta é reativada ou excluída
- **AND** o resultado confirma o estado revogado sem emitir credenciais

#### Scenario: Readiness changed after activation

- **WHEN** close é solicitado com DEBUG verdadeiro, worker ativo ou outra migration pendente
- **THEN** contas owned são revogadas se o destino e o banco de autenticação continuam acessíveis
- **AND** o fechamento não depende de reparar o ambiente ou alterar outros serviços

### Requirement: Prevent overlapping sessions and stale cleanup

O controlador SHALL permitir uma sessão ativa por destino de verificação e
identificar execução e ownership dos recursos. Um fechamento antigo MUST NOT
revogar uma execução nova. Estado inconsistente SHALL exigir recovery das
contas owned antes de nova ativação.

#### Scenario: A second session is opened concurrently

- **WHEN** uma abertura ocorre enquanto existe outra sessão válida
- **THEN** a segunda é bloqueada sem trocar as senhas da primeira

#### Scenario: An old callback runs after another session started

- **WHEN** chega um fechamento referente a uma execução antiga
- **THEN** a execução atual não é revogada ou parada

#### Scenario: An orphaned session is detected

- **WHEN** uma abertura encontra contas owned ativas sem sessão válida
- **THEN** o controlador exige ou realiza o recovery explicitamente documentado
- **AND** somente depois de comprovar revogação pode emitir novas credenciais

### Requirement: Bound active sessions and report cleanup failures

Uma abertura SHALL registrar prazo máximo e preparar encerramento independente
antes de entregar credenciais. Falha na preparação SHALL revogar a abertura
e retornar BLOCKED. Sucesso/falha controlada do runner SHALL executar cleanup.
Falha de revogação MUST NOT ser anunciada como fechamento bem-sucedido.

#### Scenario: The agent disappears while the host remains active

- **WHEN** o prazo de uma sessão expira com o serviço local de agendamento ativo
- **THEN** o encerramento independente revoga aquela sessão

#### Scenario: Independent cleanup cannot be armed

- **WHEN** o encerramento independente não pode ser preparado
- **THEN** credenciais não são entregues para uma sessão desprotegida
- **AND** as contas da abertura são revogadas e o bloqueio é informado

#### Scenario: The host rebooted or revocation failed

- **WHEN** o encerramento não pode ser comprovado após reboot ou falha
- **THEN** o controlador informa recovery necessário, sem alegar inacessibilidade
- **AND** a próxima abertura não reutiliza a sessão órfã

### Requirement: Operate only explicitly selected development services

O controlador SHALL oferecer início/parada explícitos somente de web/db do dev,
preservando volumes e serviços compartilhados. Fechar contas SHALL NOT ser
descrito como fechamento do portal inteiro quando outras contas/páginas
públicas permanecerem acessíveis.

#### Scenario: Development services are stopped after verification

- **WHEN** o operador solicita parar o dev ao fechar
- **THEN** as contas são revogadas antes de parar web/db
- **AND** volumes, workers parados e infraestrutura edge permanecem preservados

#### Scenario: An attached instance is kept running

- **WHEN** o operador fecha a sessão sem pedir parada de serviços
- **THEN** as contas de teste ficam revogadas e web/db continuam disponíveis
- **AND** o relatório não afirma que todas as contas ou páginas públicas foram bloqueadas
