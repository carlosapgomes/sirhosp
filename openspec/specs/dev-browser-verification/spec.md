# dev-browser-verification Specification

## Purpose

Definir verificações complementares pela interface real do portal dev, com
cenários repetíveis e exploração assistida, observações de JavaScript/rede
e evidências verificáveis sobre dataset fictício confirmado.

## Requirements

### Requirement: Exercise the real authenticated user journey

A suíte SHALL executar login, navegação e logout pela interface real, em
contextos isolados dos usuários de verificação. Uma prova de browser MUST NOT
substituir login por autenticação simulada, setters internos ou endpoints
artificiais de sucesso.

#### Scenario: A common user completes the smoke journey

- **WHEN** o usuário comum entra pelo formulário e segue o roteiro inicial
- **THEN** o painel e as páginas autorizadas exibem identidade autenticada
- **AND** logout encerra acesso às páginas protegidas
- **AND** o resultado registra ações e estados observados, não somente HTTP 200

#### Scenario: Administrative visibility differs from a common user

- **WHEN** os dois papéis navegam em contextos separados
- **THEN** cada um exibe sua própria identidade
- **AND** a visibilidade do item Estatísticas corresponde ao papel autorizado

### Requirement: Limit verification to declared business-read-only actions

A suíte SHALL declarar ações permitidas, incluindo exceções de autenticação.
O runner repetível MUST bloquear rotas/métodos de negócio não autorizados,
inclusive GETs mutantes. As verificações iniciais SHALL NOT executar ingestão,
sumários, exportação, alteração de senha ou CRUD administrativo.

#### Scenario: A scenario attempts to enqueue a job by GET

- **WHEN** uma ação do runner tenta acessar uma rota de enfileiramento
- **THEN** a requisição é bloqueada antes do efeito
- **AND** a execução falha sem apagar jobs para esconder o desvio

#### Scenario: Login and logout write only expected authentication state

- **WHEN** o roteiro realiza login/logout
- **THEN** alterações de sessão e das contas de teste são permitidas
- **AND** não há alteração de dados de negócio ou criação de jobs

### Requirement: Verify JavaScript behavior and responsive navigation

A suíte SHALL observar interações reais de JavaScript, atualização periódica
do shell e navegação em larguras desktop/mobile. Presença de HTML estático
SHALL NOT substituir prova de funcionamento da interação.

#### Scenario: Periodic shell refresh keeps working

- **WHEN** o navegador permanece no shell durante dois ciclos de atualização
- **THEN** duas chamadas periódicas reais e seus swaps são observados
- **AND** existe somente um badge de sincronização, sem formulário de login inserido

#### Scenario: The mobile navigation is operated

- **WHEN** o usuário abre e fecha o menu no viewport móvel
- **THEN** o menu e o conteúdo permanecem acessíveis
- **AND** não existe overflow global indevido além de regiões roláveis previstas

#### Scenario: Census filters use known synthetic expectations

- **WHEN** um registro fictício esperado existe e o usuário filtra pela interface
- **THEN** o resultado corresponde ao descritor fornecido previamente
- **AND** controles JavaScript inicializados e seleção mantida são observados

### Requirement: Distinguish failures from missing prerequisites

Cada caso SHALL retornar PASS, FAIL, BLOCKED ou SKIPPED com motivo e prova.
Ausência de browser, isolamento, dataset esperado ou capacidade requerida
MUST NOT resultar em PASS. Sucesso agregado SHALL exigir aprovação de todos
os casos solicitados e do cleanup.

#### Scenario: A synthetic record required by a filter is missing

- **WHEN** o descritor ou registro necessário não está disponível
- **THEN** o caso é BLOCKED, não PASS por encontrar uma tabela vazia
- **AND** nenhum seed, reset de banco ou processamento externo é iniciado automaticamente

#### Scenario: A page fails or credentials remain active

- **WHEN** há erro JavaScript/HTTP inesperado ou cleanup sem revogação comprovada
- **THEN** o resultado agregado não é sucesso
- **AND** evidências de diagnóstico e recuperação são preservadas

### Requirement: Preserve scoped evidence without credentials

Cada execução SHALL produzir evidências identificadas, com cenários, papel,
ações, assertions, resultados e caminhos de artefatos. Relatórios MUST NOT
incluir senhas, cookies, tokens ou payloads de autenticação. Cleanup SHALL
preservar evidências e remover somente recursos que a execução criou.

#### Scenario: A successful or failed run is cleaned up

- **WHEN** o navegador e a sessão de verificação são encerrados
- **THEN** o relatório e as screenshots relevantes continuam disponíveis
- **AND** dados de sessão e senhas não são apresentados como evidência pública

### Requirement: Provide an executable and honest assisted verification skill

A skill local SHALL documentar preflight, abertura, direção por MCP, evidências,
encerramento e mapa de funcionalidades. Uma funcionalidade SHALL ser dirigida
end-to-end antes da entrega. Entradas futuras ou não comprovadas SHALL ser
marcadas explicitamente; não se assume proteção de transporte pelo texto da skill.

#### Scenario: The skill is demonstrated

- **WHEN** o roteiro de uma funcionalidade é executado com MCP disponível
- **THEN** login real, ações, evidências e revogação são demonstrados
- **AND** a sessão pessoal do operador não é reutilizada
- **AND** evidências sobrevivem ao fechamento

#### Scenario: MCP cannot provide the required isolation

- **WHEN** o recurso necessário não funciona na instalação disponível
- **THEN** a demonstração é BLOCKED e a skill permanece não comprovada
- **AND** não se conecta silenciosamente a browser pessoal ou altera configuração MCP

### Requirement: Complement rather than replace official tests

A suíte de browser SHALL ser acionada explicitamente como camada complementar.
Sua inclusão MUST NOT remover testes, enfraquecer gates ou exigir dev público
ligado para executar unit/integration em CI.

#### Scenario: Existing official gates run independently

- **WHEN** os comandos oficiais de check/unit/integration/lint/typecheck são executados
- **THEN** continuam usando seu ambiente de testes isolado
- **AND** não ativam contas ou sessões no banco de desenvolvimento
