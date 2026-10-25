# inpatient-pending-items Specification

## Purpose

Permitir o registro manual e auditável de impedimentos ao andamento da investigação, tratamento ou alta, preservando o episódio de internação, as alterações e a distinção entre resolução e encerramento sem resolução.

## Requirements

### Requirement: PI-01 Cadastro manual de pendências

O sistema SHALL cadastrar pendências com tipo e descrição/observação não vazios, em estado inicial Ativa, sem exigir título, justificativa separada, responsável designado, prazo ou prioridade. SHALL permitir múltiplas pendências do mesmo tipo na mesma internação, sem limiar de permanência.

#### Scenario: Registrar duas pendências do mesmo tipo

- **WHEN** um integrante autorizado cadastra duas pendências com o mesmo tipo e descrições diferentes na internação atual
- **THEN** ambas são preservadas com identidades próprias e estado Ativa
- **AND** cada uma identifica autor e horário de criação

#### Scenario: Rejeitar campos obrigatórios vazios

- **WHEN** um cadastro não informa tipo válido ou contém somente espaços na descrição
- **THEN** nenhum registro nem versão histórica é criado
- **AND** o formulário informa o problema sem perder os dados válidos preenchidos

#### Scenario: Não exigir longa permanência

- **WHEN** o paciente está atualmente internado com episódio identificado e ainda tem poucos dias de internação
- **THEN** o sistema permite o cadastro pelos usuários autorizados

### Requirement: PI-02 Catálogo administrativo com Outro

O sistema SHALL iniciar o catálogo somente com Outro, permitir que o administrador cadastre e mantenha os demais tipos e proteger tipos em uso contra exclusão. Outro SHALL permanecer disponível e protegido de renomeação/exclusão, inclusive sem referências. Seu uso SHALL ser detalhado na descrição da pendência, sem criar automaticamente novo tipo.

#### Scenario: Instalação inicial

- **WHEN** a funcionalidade é instalada
- **THEN** Outro está disponível e nenhum catálogo clínico adicional é presumido

#### Scenario: Descrever um tipo não catalogado

- **WHEN** o usuário escolhe Outro e descreve a pendência
- **THEN** o texto fica somente naquele registro e em suas versões
- **AND** nenhum tipo reutilizável é criado

#### Scenario: Manter catálogo sem modificar conteúdo histórico

- **WHEN** o administrador renomeia um tipo utilizado diferente de Outro ou tenta excluí-lo
- **THEN** as versões anteriores continuam mostrando o nome observado na época
- **AND** a exclusão do tipo utilizado é impedida

#### Scenario: Preservar Outro mesmo sem uso

- **WHEN** o administrador tenta renomear ou excluir Outro, mesmo sem pendências que o referenciem
- **THEN** a operação é negada e Outro continua disponível com sua identificação original

### Requirement: PI-03 Vínculo conservador com a internação atual

O sistema SHALL vincular a pendência a um único episódio canônico existente. Escritas SHALL exigir presença no censo atual e identificação não ambígua da internação atual ainda aberta. Ausência ou ambiguidade SHALL bloquear cadastro sem criar episódio provisório. Selecionar uma internação antiga SHALL NOT redirecionar uma escrita para outra internação.

#### Scenario: Internação ausente ou ambígua

- **WHEN** o paciente não tem uma internação atual identificável sem ambiguidade
- **THEN** o cadastro é bloqueado
- **AND** a interface informa “Não há registro de internação ativa para o paciente no momento. Entre em contato com o administrador.”
- **AND** nenhum episódio ou pendência provisório é criado

#### Scenario: Seleção de episódio anterior

- **WHEN** um usuário abre uma internação anterior de um paciente atualmente reinternado
- **THEN** somente as pendências daquele episódio são consultadas
- **AND** não é possível criar ou editar naquele episódio nem copiar automaticamente suas pendências para o atual

#### Scenario: Paciente deixa de constar no censo sem saída confirmada

- **WHEN** o paciente não consta mais no censo atual mas sua saída ainda não foi confirmada
- **THEN** a criação e a edição humana são bloqueadas
- **AND** o sistema não encerra pendências apenas por essa ausência

### Requirement: PI-04 Escrita exclusiva do grupo Desospitalização

O sistema SHALL exigir associação ao grupo Desospitalização para toda operação humana de cadastro, edição ou finalização. Integrantes SHALL poder operar registros criados por colegas. Privilégios de administrador ou superusuário SHALL NOT substituir a associação ao grupo. Leituras e exportação SHALL permanecer disponíveis a qualquer usuário autenticado.

#### Scenario: Integrante edita registro de colega

- **WHEN** um integrante do grupo altera uma pendência ativa criada por outro integrante em internação elegível
- **THEN** a alteração é aceita e identifica o novo autor sem substituir a autoria de criação

#### Scenario: Superusuário fora do grupo

- **WHEN** um superusuário não associado ao grupo tenta uma escrita de pendência
- **THEN** a operação é negada, inclusive por chamada direta ao endpoint
- **AND** nenhum dado ou versão é alterado

#### Scenario: Leitor autenticado e perda de associação

- **WHEN** um usuário autenticado fora do grupo tenta escrever, inclusive após perder a associação com um formulário aberto
- **THEN** pode continuar consultando, mas a escrita é negada
- **AND** ocultar botões não é a única proteção aplicada

### Requirement: PI-05 Estados finais imutáveis

O sistema SHALL admitir somente Ativa, Resolvida e Encerrada sem resolução. Uma pendência ativa SHALL poder ter tipo/texto alterados ou ser finalizada com anotação opcional. Pendências finalizadas SHALL NOT ser corrigidas, reabertas ou excluídas. Recorrência SHALL ser registrada em nova pendência, sem reutilização em reinternação.

#### Scenario: Finalizar sem anotação adicional

- **WHEN** um integrante finaliza uma pendência ativa como Resolvida ou Encerrada sem resolução sem acrescentar anotação
- **THEN** a transição é aceita, preservando a descrição existente
- **AND** o horário da transição identifica a finalização

#### Scenario: Registrar motivo opcional e erro de cadastro

- **WHEN** um integrante encerra sem resolução por mudança de conduta, impossibilidade ou cadastro por engano e informa uma anotação
- **THEN** a anotação fica vinculada à versão da transição
- **AND** o registro original permanece consultável

#### Scenario: Tentar alterar uma pendência finalizada

- **WHEN** um usuário tenta mudar tipo, descrição ou status de uma pendência finalizada, ou excluí-la
- **THEN** a operação é rejeitada sem alterar o registro nem o histórico

### Requirement: PI-06 Histórico completo e atômico

O sistema SHALL preservar a versão inicial e cada alteração efetiva com sequência, horário, autor, ação, tipo, descrição, status e anotação opcional. O estado atual e sua versão SHALL ser gravados atomicamente. O histórico SHALL ser somente leitura, preservar autoria anterior e diferenciar usuário humano de Sistema.

#### Scenario: Consultar versões após duas alterações

- **WHEN** uma pendência criada e posteriormente alterada duas vezes é consultada por usuário autenticado
- **THEN** a versão inicial e as duas alterações estão disponíveis em ordem determinística
- **AND** cada versão permite identificar o conteúdo anterior, o conteúdo resultante e o autor

#### Scenario: Falha ao gravar histórico

- **WHEN** ocorre falha na gravação da versão de uma alteração
- **THEN** o estado atual também permanece inalterado

#### Scenario: Edições simultâneas e formulário desatualizado

- **WHEN** uma versão mais recente é gravada antes do envio de um formulário antigo
- **THEN** o envio antigo não sobrescreve silenciosamente o conteúdo mais recente
- **AND** a interface informa o conflito e permite consultar a versão atual

#### Scenario: Histórico protegido da administração e dos logs

- **WHEN** alguém utiliza interfaces administrativas, requisições de alteração ou consulta logs operacionais
- **THEN** não encontra ações para editar/excluir versões ou apagar pendências
- **AND** descrição, anotação, nome e registro do paciente não são copiados para logs

### Requirement: PI-07 Encerramento por saída confirmada

Nos fluxos confiáveis de saída e unificação, o sistema SHALL encerrar as pendências ainda ativas sempre que o estado resultante do episódio estiver fechado, inclusive em confirmação repetida, com autoria Sistema, motivo e horário de processamento. SHALL preservar finalizações humanas e ser idempotente. Ausência no censo, alta médica sem saída efetiva e evidência ambígua/conflitante SHALL NOT disparar encerramento.

#### Scenario: Saída por alta hospitalar óbito ou transferência

- **WHEN** uma alta hospitalar, óbito ou transferência externa resulta em saída confirmada da internação
- **THEN** cada pendência ainda ativa desse episódio recebe uma única transição para Encerrada sem resolução
- **AND** o histórico identifica Sistema e saída confirmada como motivo
- **AND** nenhuma pendência de outro episódio é alterada

#### Scenario: Repetir ou corrigir evidência de saída

- **WHEN** a mesma saída é processada novamente ou seu horário é corrigido
- **THEN** não é criada nova finalização para pendências já finalizadas
- **AND** os registros já resolvidos manualmente permanecem Resolvidos com sua autoria preservada

#### Scenario: Reprocessar fechamento anterior com ativas residuais

- **WHEN** um fluxo confiável reprocessa um episódio já fechado e ainda encontra pendências ativas, inclusive em resultado de evidência já reconciliada
- **THEN** encerra essas ativas uma única vez com autoria Sistema
- **AND** preserva sem nova versão as pendências já finalizadas

#### Scenario: Unificar para episódio fechado sem nova data de fim na confirmação

- **WHEN** uma unificação válida resulta em internação fechada por fim já presente na canônica ou na duplicata, mesmo sem fim no snapshot de confirmação
- **THEN** pendências ativas transferidas e preexistentes da canônica são encerradas
- **AND** não é exigida uma nova transição da internação de aberta para fechada

#### Scenario: Falha em um item de snapshot preserva os anteriores

- **WHEN** um item de internação já foi persistido e o item seguinte falha ao gravar uma revisão de encerramento
- **THEN** a saída, pendências, revisões, aliases e alterações de consolidação do item que falhou são desfeitos juntos
- **AND** a falha é propagada, o item anterior permanece persistido e itens seguintes não são processados naquela chamada
- **AND** não é criada auditoria de reconciliação fictícia para um snapshot

#### Scenario: Saída concorre com edição ou cadastro

- **WHEN** a confirmação de saída, inclusive pelo snapshot compartilhado, concorre com uma edição ou cadastro humano
- **THEN** a identidade do episódio é revalidada sob proteção transacional e a ordem das alterações é preservada
- **AND** nenhuma escrita cria pendência ativa ou altera pendência depois da saída confirmada
- **AND** um cadastro anterior ao fechamento é encerrado como parte da operação de saída

### Requirement: PI-08 Preservação na reconciliação de episódios

O sistema SHALL preservar pendências e versões na unificação confirmada de internações duplicadas, sem misturar episódios diferentes. Nenhuma consolidação legada SHALL apagar esse conteúdo. Rollbacks estruturais SHALL preservar o histórico das pendências e SHALL NOT reabrir estados finais automaticamente.

#### Scenario: Unificar duplicatas confirmadas

- **WHEN** duas internações são confirmadas como o mesmo episódio e unificadas
- **THEN** suas pendências ficam acessíveis pela internação canônica, sem duplicação de versões
- **AND** a movimentação estrutural fica rastreável pela auditoria da unificação

#### Scenario: Consolidação legada encontra pendências

- **WHEN** uma consolidação legada sem a confirmação exigida encontra pendências em alguma internação candidata
- **THEN** a etapa destrutiva é impedida para esse conjunto sem apagar pendências ou versões
- **AND** a resolução permanece sujeita ao caminho canônico já existente

#### Scenario: Cadastro confirmado entre guarda e exclusão legada

- **WHEN** uma pendência é criada depois da verificação da guarda e antes de uma tentativa destrutiva de consolidação
- **THEN** a proteção da relação impede a exclusão e a operação perdedora falha sem transferências parciais
- **AND** a falha é propagada, sem anunciar sucesso ou apagar pendências/versões
- **AND** uma repetição pelo fluxo existente reavalia a guarda e a identidade

#### Scenario: Desfazer uma reconciliação estrutural

- **WHEN** um rollback autorizado restaura a propriedade das relações ou o estado de uma internação
- **THEN** as versões de pendências permanecem preservadas
- **AND** pendências já finalizadas não voltam automaticamente a Ativa
