# verification-origin-configuration Specification

## Purpose
Configurar privadamente as origens operacionais da verificação, manter CLI e
MCP no mesmo alvo autorizado e impedir que a ausência dessa configuração
comprometa a revogação de sessões ou publique FQDNs na árvore atual.

## Requirements

### Requirement: Resolve operational origins from one private local file

O verificador SHALL ler `SIRHOSP_VERIFY_DEV_ORIGIN` e
`SIRHOSP_VERIFY_PROD_ORIGIN` de `~/.config/sirhosp/verification.env`.
MUST NOT usar hostname compilado, `.env` da aplicação, hosts Django ou
variáveis do processo como fallback. MUST NOT criar/preencher o arquivo
quando ele estiver ausente.

#### Scenario: The operator supplies both origins

- **WHEN** o arquivo privado contém as duas origens válidas
- **THEN** CLI e MCP usam o mesmo resultado canônico da configuração
- **AND** somente o alvo dev pode ser verificado

#### Scenario: A process variable conflicts with the private file

- **WHEN** uma variável de ambiente contém outra origem
- **THEN** ela não substitui o valor do arquivo privado
- **AND** a origem não é deduzida de configurações da aplicação

### Requirement: Reject unsafe configuration before opening effects

Doctor, open e run SHALL retornar BLOCKED se o arquivo for ausente,
inacessível ou tiver origem obrigatória ausente, vazia ou inválida.
MUST NOT iniciar serviços, gravar estado de abertura, registrar timer,
alterar contas, emitir senhas ou navegar antes da validação.

#### Scenario: No private configuration exists

- **WHEN** doctor, open ou run é solicitado sem o arquivo privado
- **THEN** o comando retorna BLOCKED com diagnóstico acionável
- **AND** nenhum efeito de abertura ou navegação acontece

#### Scenario: The profile contains invalid values

- **WHEN** uma origem usa HTTP, userinfo, query, fragmento ou caminho de aplicação
- **THEN** a operação é BLOCKED antes dos efeitos de abertura
- **AND** o diagnóstico identifica a chave inválida sem reproduzir seu valor

### Requirement: Compare normalized origins and refuse production

As origens SHALL ser HTTPS absolutas com host e porta válidos, sem userinfo,
query ou fragmento e com caminho vazio ou `/`. SHALL ser comparadas por
scheme, host normalizado e porta efetiva. Dev equivalente à produção MUST
ser BLOCKED. A origem de produção MUST NOT ser consultada ou dirigida.

#### Scenario: Dev and production differ only in representation

- **WHEN** os valores diferem somente em caixa do host, barra final ou porta 443 explícita
- **THEN** são reconhecidos como a mesma origem
- **AND** a abertura é BLOCKED sem contato com produção

#### Scenario: A journey leaves the authorized dev origin

- **WHEN** uma navegação ou redirect aponta à produção configurada ou a outra origem não permitida
- **THEN** o runner recusa o transporte conforme os fences já existentes
- **AND** o roteiro MCP não segue esse destino nem alega possuir um firewall

### Requirement: Expose canonical dev origin as additive CLI metadata

Doctor PASS e open bem-sucedido SHALL incluir `origin`, a origem dev validada,
no JSON, preservando os campos e flags existentes. A origem SHALL permanecer
a mesma durante uma operação. Produção não será emitida como alvo utilizável.

#### Scenario: A fresh executor prepares an assisted run

- **WHEN** doctor retorna PASS
- **THEN** o executor obtém `origin` do resultado canônico, sem ler o `.env` da aplicação
- **AND** open informa a origem efetivamente associada à nova sessão

#### Scenario: Doctor and open resolve different origins

- **WHEN** a configuração muda entre doctor e open no roteiro MCP
- **THEN** o executor não navega para nenhuma das origens nessa tentativa
- **AND** fecha a sessão owned pelo mecanismo canônico e retorna BLOCKED para revalidação

#### Scenario: The profile changes after a session opens

- **WHEN** o arquivo muda ou desaparece durante a jornada
- **THEN** a jornada mantém a origem validada daquela abertura
- **AND** outro comando de abertura precisa validar sua própria configuração

### Requirement: Apply explicit origin consistently to browser journeys

O runner SHALL transmitir a origem validada a browser, contexts, jornadas,
assets locais e allowlist de requests. MUST NOT manter defaults operacionais
fixos ou probes que dependam de hostname real compilado.

#### Scenario: The operator configures a different approved dev origin

- **WHEN** uma origem HTTPS distinta é explicitamente configurada e os demais fences são satisfeitos
- **THEN** as jornadas de login, navegação, filtros e logout usam essa origem
- **AND** scheme, porta, método, path, redirects, popups, SW/WS e CDNs continuam restritos

### Requirement: Keep cleanup independent of origin configuration

Close, recovery, callback e status SHALL continuar disponíveis sem o arquivo
privado ou com conteúdo inválido. Importar os módulos MUST NOT exigir esse
arquivo. As verificações de identidade do banco e ownership SHALL permanecer
obrigatórias; ausência da URL MUST NOT impedir revogação.

#### Scenario: The profile is removed while accounts are active

- **WHEN** close ou callback executa após a remoção do arquivo
- **THEN** a operação tenta a revogação fenced e o cleanup owned normalmente
- **AND** não reativa contas nem anuncia sucesso se a revogação falhar

#### Scenario: Recovery runs with malformed origin configuration

- **WHEN** o estado exige recovery e a configuração de origem está inválida
- **THEN** recovery usa identidade e ownership já definidos pelo contrato de sessão
- **AND** a configuração não causa falha de import ou bloqueio artificial

### Requirement: Preserve existing environment and session fences

Configurar uma origem MUST NOT substituir a confirmação de dataset nem os
fences existentes de checkout, engine, containers, volume, banco, ownership,
FSM, isolamento, timer e cleanup. Nenhuma origem SHALL habilitar um target
prod ou serviço de negócio mutante.

#### Scenario: A valid URL accompanies an invalid local target

- **WHEN** a URL é válida mas o engine, banco, checkout ou dataset não passa no preflight
- **THEN** a abertura permanece BLOCKED
- **AND** nenhuma conta é ativada por causa da configuração de URL

### Requirement: Publish recipes and fixtures without operational FQDNs

A árvore atual versionável SHALL deixar de conter os FQDNs operacionais
identificados na baseline. Template, testes e exemplos SHALL usar valores
vazios, origens sintéticas ou referências ao resultado validado. A skill
SHALL usar `origin` canônica e preservar cobertura MCP/Playwright honesta.

#### Scenario: The current tree is checked before acceptance

- **WHEN** os arquivos tracked e candidatos do slice são inspecionados
- **THEN** os FQDNs operacionais da baseline não aparecem nessa árvore
- **AND** a verificação registra somente paths/contagens, sem versionar os nomes em uma blacklist

#### Scenario: A user follows the updated MCP recipe

- **WHEN** o executor inicia autenticação usando o roteiro atualizado
- **THEN** utiliza doctor/open e a origem validada, com TLS e contexto exclusivo
- **AND** login/logout e revogação são comprovados sem copiar a URL real para documentos versionados

### Requirement: Separate current-tree remediation from history rewriting

A correção SHALL limitar-se à árvore atual e a novos commits autorizados.
MUST NOT reescrever commits antigos, tags, branches ou referências remotas.
Sua evidência SHALL distinguir remoção atual de eliminação do histórico.

#### Scenario: The current tree no longer contains the operational names

- **WHEN** a implementação é aceita
- **THEN** o relatório declara que as versões antigas ainda podem conter os nomes
- **AND** nenhuma purga, force-push ou archive é executado implicitamente
