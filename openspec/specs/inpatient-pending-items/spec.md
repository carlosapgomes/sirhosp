# inpatient-pending-items Specification

## Purpose

Permitir o registro manual e auditável de impedimentos ao andamento da investigação, tratamento ou alta, preservando o episódio de internação, as alterações e a distinção entre resolução e encerramento sem resolução.

## Requirements

### Requirement: PI-01 Cadastro manual de pendências

O sistema SHALL cadastrar pendências com categoria e tipo válidos, observações opcionais exceto em tipos genéricos Outro/Outros, e campos complementares conforme o perfil do tipo, em estado inicial Ativa. SHALL NOT exigir título, justificativa separada, responsável designado, prazo ou prioridade. SHALL permitir múltiplas pendências do mesmo tipo na mesma internação, sem limiar de permanência.

#### Scenario: Registrar duas pendências do mesmo tipo

- **WHEN** um integrante autorizado cadastra duas pendências com o mesmo tipo e descrições diferentes na internação atual
- **THEN** ambas são preservadas com identidades próprias e estado Ativa
- **AND** cada uma identifica autor e horário de criação

#### Scenario: Rejeitar campos obrigatórios vazios

- **WHEN** um cadastro não informa tipo válido, combina categoria com tipo de outra categoria ou usa Outro/Outros com observação somente de espaços
- **THEN** nenhum registro nem versão histórica é criado
- **AND** o formulário informa o problema sem perder os dados válidos preenchidos

#### Scenario: Cadastrar tipo definido sem observações

- **WHEN** um integrante seleciona Tomografia, responde Não para Agendada e deixa observações vazias
- **THEN** a pendência é criada sem exigir texto que repita o nome do tipo

#### Scenario: Não exigir longa permanência

- **WHEN** o paciente está atualmente internado com episódio identificado e ainda tem poucos dias de internação
- **THEN** o sistema permite o cadastro pelos usuários autorizados

### Requirement: PI-02 Catálogo administrativo com Outro

O sistema SHALL fornecer categorias e tipos do catálogo consolidado desta change, com perfis fixos e complementos RNM. Slugs SHALL ser imutáveis após criação; nomes de categoria SHALL ser únicos e nomes de tipo SHALL ser únicos dentro da categoria. Tipos referenciados por qualquer pendência ou versão SHALL ser considerados usados, protegidos contra exclusão e contra mudança de categoria, perfil, complementos RNM ou obrigatoriedade de observações. Categorias referenciadas SHALL ser protegidas contra exclusão. Outro SHALL ter identidade e contrato fixos mesmo sem uso. Manutenção e carga SHALL preservar conteúdo histórico e seguir as correspondências e colisões explícitas abaixo, sem criar tipos a partir de observações.

#### Scenario: Instalação inicial

- **WHEN** a funcionalidade atualizada é instalada em banco novo
- **THEN** recebe as dez categorias e 46 entradas definidas no catálogo desta change
- **AND** CATE aparece uma vez em Hemodinâmica e RNM usa um tipo por categoria aplicável, com contraste e sedação independentes

#### Scenario: Descrever um tipo não catalogado

- **WHEN** o usuário escolhe Outro e descreve a pendência
- **THEN** o texto fica somente naquele registro e em suas versões
- **AND** nenhum tipo reutilizável é criado

#### Scenario: Manter catálogo sem modificar conteúdo histórico

- **WHEN** o administrador renomeia um tipo utilizado diferente de Outro ou tenta excluí-lo
- **THEN** as versões anteriores continuam mostrando o nome observado na época
- **AND** a exclusão do tipo utilizado é impedida

#### Scenario: Preservar Outro mesmo sem uso

- **WHEN** o administrador tenta renomear, excluir ou alterar categoria/perfil/complementos/obrigatoriedade de Outro, mesmo sem pendências ou versões que o referenciem
- **THEN** a operação é negada e Outro mantém slug outro, nome Outro, categoria outras-pendencias, perfil Registro simples, sem complementos RNM e observações obrigatórias

#### Scenario: Distinguir nomes repetidos

- **WHEN** o usuário procura RNM
- **THEN** pode distinguir Exames de imagem > RNM de CHD > RNM
- **AND** cada tipo possui identidade própria, sem fundir registros entre categorias

#### Scenario: Impedir alteração retroativa de contrato de campos

- **WHEN** o administrador tenta mudar categoria, perfil, complementos RNM ou obrigatoriedade de observações de um tipo já usado
- **THEN** a alteração é rejeitada e o contrato dos registros existentes permanece válido
- **AND** uma mudança desse contrato exige outro tipo, sem reclassificação automática dos registros

#### Scenario: Carga repetida e categorias referenciadas

- **WHEN** a carga do catálogo é reaplicada ou o administrador tenta excluir categoria com tipos
- **THEN** a carga não duplica entradas nem sobrescreve customizações existentes
- **AND** a exclusão da categoria referenciada é impedida
- **AND** colisões incompatíveis de identificador são reportadas sem fusão ou exclusão silenciosa

#### Scenario: Proteger identificadores após criação

- **WHEN** o administrador tenta alterar o slug de categoria ou tipo já criado, ainda que nunca usado
- **THEN** a operação é rejeitada sem modificar a identidade
- **AND** renomear somente o nome visível, salvo Outro, não altera o slug nem gera duplicação em reaplicação

#### Scenario: Proteger tipo usado somente no histórico

- **WHEN** um tipo não tem mais nenhuma pendência atual que o use, mas continua referenciado por uma versão anterior
- **THEN** continua protegido contra exclusão e mudanças de categoria, perfil, complementos RNM e obrigatoriedade de observações
- **AND** mudar seu nome visível não reescreve essa versão

#### Scenario: Adotar identidade canônica na inicialização

- **WHEN** a primeira carga encontra tipo preexistente com slug e nome exatamente iguais aos canônicos
- **THEN** mantém sua identidade e inicializa uma única vez categoria, perfil, complementos RNM e regra de observação conforme o catálogo
- **AND** preserva pendências e versões existentes, sem atribuir classificação presumida ao passado

#### Scenario: Rejeitar colisão de slug na inicialização

- **WHEN** a primeira carga encontra slug reservado com nome divergente
- **THEN** toda a carga é rejeitada sem alterações parciais, renomeação, exclusão ou fusão
- **AND** o diagnóstico identifica somente o conflito de catálogo, sem dados de pacientes

#### Scenario: Preservar homônimo de identidade distinta

- **WHEN** um tipo preexistente tem nome canônico, mas slug diferente
- **THEN** permanece distinto em Outras pendências como Registro simples e a entrada canônica é criada separadamente
- **AND** se isso conflitar com nome na mesma categoria final, toda a carga é rejeitada sem renomear ou fundir registros
- **AND** categorias de mesmo nome com slugs diferentes também provocam rejeição, sem adoção por nome

#### Scenario: Reaplicar sem restaurar defaults

- **WHEN** a carga é reaplicada após renomeação de nome visível ou customização legítima de contrato antes de uso
- **THEN** reconhece a entrada pelo slug e preserva nome, categoria, perfil, complementos e obrigatoriedade existentes
- **AND** não usa as regras de adoção inicial nem altera pendências ou versões
- **AND** entradas ausentes só são recriadas quando não há colisão de nome; colisão ou contrato de Outro inconsistente rejeita a carga atomicamente

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

O sistema SHALL admitir somente Ativa, Resolvida e Encerrada sem resolução. Uma pendência ativa SHALL poder ter classificação, observações e campos complementares alterados ou ser finalizada com anotação opcional. Pendências finalizadas SHALL NOT ser corrigidas, reabertas ou excluídas. Recorrência SHALL ser registrada em nova pendência, sem reutilização em reinternação. Agendamento, datas de tratamento e assinatura SHALL NOT provocar finalização automática; o encerramento por saída confirmada continua conforme PI-07.

#### Scenario: Finalizar sem anotação adicional

- **WHEN** um integrante finaliza uma pendência ativa como Resolvida ou Encerrada sem resolução sem acrescentar anotação
- **THEN** a transição é aceita, preservando a descrição e os campos complementares existentes
- **AND** o horário da transição identifica a finalização

#### Scenario: Registrar motivo opcional e erro de cadastro

- **WHEN** um integrante encerra sem resolução por mudança de conduta, impossibilidade ou cadastro por engano e informa uma anotação
- **THEN** a anotação fica vinculada à versão da transição
- **AND** o registro original permanece consultável

#### Scenario: Tentar alterar uma pendência finalizada

- **WHEN** um usuário tenta mudar tipo, observações, campos complementares ou status de uma pendência finalizada, ou excluí-la
- **THEN** a operação é rejeitada sem alterar o registro nem o histórico

#### Scenario: Datas não resolvem automaticamente

- **WHEN** uma data de exame ou previsão de término passa, ou alguém registra a assinatura do sumário
- **THEN** o registro permanece Ativo até finalização humana ou encerramento por saída confirmada
- **AND** não são gerados novos estados como Agendada ou Assinada para substituir o estado da pendência

#### Scenario: Preservar exceção de saída confirmada

- **WHEN** alta hospitalar, óbito ou transferência externa confirma a saída de um episódio com pendências ativas e finalizadas
- **THEN** somente as ativas são encerradas sem resolução com autoria Sistema
- **AND** campos complementares e finalizações humanas são preservados, sem duplicar versões no reprocessamento

### Requirement: PI-06 Histórico completo e atômico

O sistema SHALL preservar a versão inicial e cada alteração efetiva com sequência, horário, autor, ação, observações, campos complementares, status e anotação opcional. A classificação observada SHALL incluir nome e identificador estável de categoria e tipo, perfil, habilitação dos complementos RNM e obrigatoriedade de observações, sem depender do contrato atual do catálogo. O estado atual e sua versão SHALL ser gravados atomicamente. O histórico SHALL ser somente leitura, preservar autoria anterior e diferenciar usuário humano de Sistema. Ausência de mudança efetiva SHALL NOT criar versão nova.

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

#### Scenario: Versionar somente alteração de campo complementar

- **WHEN** a equipe informa uma data agendada sem alterar tipo ou observações
- **THEN** é criada uma nova versão com o estado completo e autoria da alteração
- **AND** reenviar os mesmos dados não cria outra versão

#### Scenario: Preservar classificação observada

- **WHEN** a categoria ou o nome de um tipo é renomeado administrativamente
- **THEN** revisões anteriores mantêm nomes/identificadores de categoria e tipo, perfil, habilitação RNM e obrigatoriedade de observações observados na época
- **AND** o histórico não apresenta a nova classificação como se sempre tivesse existido
- **AND** dados novos desconhecidos de revisões anteriores à atualização permanecem ausentes, não convertidos em Não

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

### Requirement: PI-09 Informações estruturadas por perfil

O sistema SHALL registrar campos próprios de agendamento, período de tratamento ou assinatura conforme o tipo. Nos novos cadastros de agendamento SHALL exigir Sim/Não explícito e aceitar Sim sem data. Datas SHALL ser opcionais. RNM SHALL admitir contraste e sedação independentes como Não informado, Sim ou Não. Campos não aplicáveis SHALL permanecer ausentes, sem interpretar ausência como Não.

#### Scenario: Agendamento sem data conhecida

- **WHEN** a equipe marca Sim para cirurgia agendada sem conhecer a data
- **THEN** a pendência pode ser salva e informa Agendada, data não informada
- **AND** não é inventada uma data nem alterado seu estado Ativa

#### Scenario: Exigir resposta de agendamento e validar coerência

- **WHEN** um novo cadastro de agendamento omite Sim/Não ou envia Não junto de data agendada
- **THEN** a gravação é rejeitada com erro nos campos correspondentes
- **AND** nenhuma versão é criada

#### Scenario: Combinar características RNM

- **WHEN** uma RNM recebe Contraste Sim e Sedação Não
- **THEN** ambas as respostas são preservadas independentemente
- **AND** Não informado continua diferente de Não

#### Scenario: Tratamento com informação parcial

- **WHEN** a equipe registra antibióticos apenas com data de início, ou sem ambas as datas
- **THEN** o cadastro é aceito sem calcular duração ou previsão de término
- **AND** se ambas as datas forem informadas, término anterior ao início é rejeitado

#### Scenario: Assinatura sem efeito clínico ou operacional automático

- **WHEN** a equipe registra data/hora da assinatura do sumário de alta
- **THEN** o dado é preservado com horário institucional e não altera o estado da pendência ou da internação
- **AND** não constitui assinatura eletrônica nem consulta a sistema externo

#### Scenario: Impedir campos incompatíveis e troca com resíduos

- **WHEN** um cadastro envia data de assinatura para Tomografia ou dados RNM para um tipo que não admite esses complementos
- **THEN** o envio é rejeitado sem persistir dados incompatíveis
- **AND** ao trocar o tipo na edição, a interface explica quais detalhes deixarão de se aplicar e permite confirmar a remoção antes de salvar
- **AND** versões anteriores preservam os detalhes removidos

### Requirement: PI-10 Preservação dos registros anteriores

A atualização SHALL manter identidades, vínculos, textos, estados e revisões existentes, sem interpretar observações para preencher campos novos. Ausência de informação anterior SHALL NOT virar Não ou uma data inventada. Tipos administrativos fora do catálogo SHALL permanecer disponíveis em Outras pendências como Registro simples. Descarte de dados de produção SHALL NOT integrar esta atualização.

#### Scenario: Atualizar banco com registros anteriores

- **WHEN** a atualização encontra pendências e revisões anteriores
- **THEN** todas permanecem identificáveis, vinculadas ao mesmo episódio e com o mesmo conteúdo e autoria
- **AND** campos novos sem evidência permanecem ausentes, e versões históricas não recebem categoria presumida

#### Scenario: Editar registro antigo sem informação complementar

- **WHEN** um registro anterior não possui resposta de agendamento e passa a usar um tipo de agendamento em edição
- **THEN** a interface apresenta ausência explícita de informação e exige Sim/Não para salvar o novo estado
- **AND** não altera a versão anterior nem presume uma resposta

### Requirement: PI-11 Finalidade administrativa dos tipos

Todos os tipos SHALL representar acompanhamentos administrativos com o mesmo ciclo de vida. Risco de óbito, Melhora clínica, Quimioterapia e demais nomes SHALL NOT produzir cálculo de gravidade, prognóstico, prioridade, alertas clínicos ou decisões terapêuticas.

#### Scenario: Registrar Risco de óbito

- **WHEN** a equipe cadastra Risco de óbito em Quadro clínico
- **THEN** o sistema registra uma pendência administrativa Ativa
- **AND** não altera a internação, presume óbito ou atribui prioridade clínica
