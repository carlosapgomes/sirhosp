# pending-items-portal Specification

## Purpose

Disponibilizar consulta contextual e institucional de pendências de internados, com edição autorizada, histórico, filtros, indicadores hospitalares e exportação que respeite o mesmo recorte dos resultados.

## Requirements

### Requirement: PP-01 Navegação contextual e consulta histórica

O portal SHALL disponibilizar pendências a partir da internação selecionada em /patients/<id>/admissions/ e oferecer consulta de todas as suas pendências e versões. Episódios anteriores e internações com saída SHALL permanecer somente para leitura. Anônimos SHALL ser redirecionados ao login em todas as superfícies, inclusive histórico, formulários e exportação.

#### Scenario: Abrir pendências da internação selecionada

- **WHEN** um usuário autenticado seleciona uma internação e acessa suas pendências
- **THEN** paciente e período ficam identificados e somente os registros desse episódio são apresentados

#### Scenario: Consultar depois da saída

- **WHEN** um usuário autenticado abre uma internação com saída confirmada
- **THEN** consulta pendências e versões preservadas, sem ações humanas de escrita

#### Scenario: Requisitar recursos sem autenticação

- **WHEN** um anônimo solicita agregado, detalhe, histórico, formulário ou XLSX
- **THEN** recebe o fluxo de login, sem conteúdo clínico ou arquivo exportado

### Requirement: PP-02 Agregado dos internados atuais

O portal SHALL oferecer Pendências no menu lateral, com agregado restrito às internações atuais dos pacientes do último censo ocupado. O padrão SHALL mostrar somente Ativas, omitindo pacientes sem correspondências. SHALL permitir selecionar Resolvidas, Encerradas sem resolução ou todos os status, sem incluir episódios anteriores de pacientes reinternados.

#### Scenario: Padrão mostra somente pendências ativas atuais

- **WHEN** o usuário abre Pendências sem filtros
- **THEN** aparecem somente pendências ativas da internação atual e seus pacientes
- **AND** cada paciente é identificado por nome, registro, unidade atual e leito

#### Scenario: Incluir finalizadas da internação atual

- **WHEN** o usuário seleciona Resolvidas, Encerradas sem resolução ou todos os status
- **THEN** o resultado inclui os estados selecionados da internação atual
- **AND** pendências de internações anteriores continuam disponíveis apenas na consulta contextual correspondente

#### Scenario: Censo ausente ou episódio não identificável

- **WHEN** não existe censo atual ou não é possível identificar o episódio atual sem ambiguidade
- **THEN** não são inventados pacientes ou vínculos para preencher o agregado
- **AND** a interface apresenta estado vazio ou orientação apropriada, sem falhar nem criar dados

#### Scenario: Ocupações conflitantes ou duas internações abertas

- **WHEN** o mesmo paciente ocupa leitos conflitantes na foto atual, sua identidade é ambígua ou existem duas internações abertas canônicas candidatas
- **THEN** o caso é excluído das duas visualizações, dos indicadores e do XLSX pelo mesmo critério conservador
- **AND** a escrita humana é bloqueada, sem escolher arbitrariamente leito ou episódio
- **AND** a consulta contextual autenticada de episódios explicitamente selecionados permanece disponível

#### Scenario: Repetições equivalentes da mesma ocupação

- **WHEN** a foto atual repete de forma equivalente a mesma identidade e ocupação sem conflito
- **THEN** o paciente e cada pendência correspondente entram uma única vez no recorte atual compartilhado

### Requirement: PP-03 Duas visualizações responsivas

O agregado SHALL oferecer visão por paciente como padrão e alternativa por pendência, compartilhando filtros e conteúdo. Ambas SHALL funcionar em desktop e celular, apresentar categoria, tipo, detalhes aplicáveis, estado atual, autoria e horários, permitir abrir histórico recolhível e acessar a internação correspondente. A listagem contextual e o histórico SHALL apresentar os mesmos detalhes, distinguindo Não, Não informado e Não aplicável.

#### Scenario: Agrupar por paciente

- **WHEN** um paciente tem três pendências correspondentes ao recorte
- **THEN** a visão padrão apresenta um grupo de paciente com as três pendências, sem ocultar registros por paginação interna do grupo

#### Scenario: Alternar para visão por pendência

- **WHEN** o usuário troca de modo com filtros ativos
- **THEN** cada pendência correspondente aparece como item independente
- **AND** filtros e correspondência dos registros são preservados

#### Scenario: Consultar histórico no celular

- **WHEN** um usuário abre o histórico recolhível de uma pendência em viewport móvel
- **THEN** consegue consultar versões, autores e horários sem perder a identificação do paciente
- **AND** a disposição não causa overflow global indevido

#### Scenario: Mostrar detalhes sem texto redundante

- **WHEN** o painel contém Tomografia agendada sem observação e Antibióticos com início e término previsto
- **THEN** cada registro exibe categoria, tipo e seus respectivos campos em resumo legível
- **AND** a ausência de observação não oculta o registro nem exige texto substituto
- **AND** o status Ativa permanece distinto de Agendada

#### Scenario: Histórico completo e informações desconhecidas

- **WHEN** uma RNM não possui informação de sedação e uma revisão antiga não contém campos novos
- **THEN** a RNM distingue Sedação não informada de Sedação Não
- **AND** a revisão antiga não recebe valores ou classificação inventados

### Requirement: PP-04 Filtros combináveis e tempo em aberto

O agregado SHALL filtrar por status, unidade/leito atuais, especialidade, categoria, tipo, criador, último atualizador e limites de tempo em aberto, combinando critérios. Tempo em aberto SHALL ser medido desde a criação até agora para Ativas e até a finalização para os demais estados, sem continuar crescendo após o encerramento.

#### Scenario: Combinar filtros antes de agrupar

- **WHEN** o usuário combina tipo, criador, setor e status
- **THEN** aparecem somente pendências que satisfazem todos os critérios
- **AND** a visão por paciente agrupa apenas essas correspondências, sem incluir pendências não correspondentes do mesmo paciente

#### Scenario: Filtrar autoria humana e Sistema

- **WHEN** o usuário filtra por criador ou último atualizador
- **THEN** os dois critérios são independentes
- **AND** Sistema pode ser identificado como último atualizador de encerramentos automáticos, sem ser confundido com um usuário humano

#### Scenario: Medir tempo de pendências ativas e finalizadas

- **WHEN** duas pendências foram criadas há dez dias e uma foi finalizada há três dias
- **THEN** a ativa tem dez dias de tempo em aberto e a finalizada tem sete dias
- **AND** a medição e os limites aplicados são iguais nas duas visualizações e no XLSX

#### Scenario: Combinar categoria e tipo

- **WHEN** o usuário seleciona CHD e o tipo RNM de Exames de imagem por requisição direta
- **THEN** não recebe resultados fora da interseção dos filtros
- **AND** a interface orienta corrigir a combinação sem ignorar silenciosamente um filtro
- **AND** a mesma combinação produz recorte vazio no XLSX

### Requirement: PP-05 Primeira unidade registrada no episódio

O portal e o XLSX SHALL mostrar a primeira unidade registrada durante a internação correspondente, incluindo pronto-socorro quando for o primeiro registro. A informação SHALL NOT usar uma passagem de outro episódio, inferir setor real não observado ou confundir a unidade atual com a primeira. Sem evidência suficiente SHALL mostrar Primeira unidade não identificada.

#### Scenario: Percurso conhecido inclui pronto-socorro

- **WHEN** o episódio contém registros ordenáveis de Pronto-Socorro, UTI e Enfermaria
- **THEN** Primeira unidade de internação apresenta Pronto-Socorro
- **AND** a unidade atual continua apresentada separadamente

#### Scenario: Histórico incompleto ou de outro episódio

- **WHEN** somente existem movimentações de outra internação ou nenhuma movimentação é atribuível ao episódio sem ambiguidade
- **THEN** é apresentada Primeira unidade não identificada
- **AND** o sistema não usa o primeiro setor de toda a vida do paciente como substituto

### Requirement: PP-06 Edição rápida segura

Integrantes do grupo Desospitalização SHALL poder abrir edição rápida de uma pendência ativa em ambas as visões, identificando paciente e internação. A edição SHALL permitir classificação, observações e campos do perfil com as mesmas regras do cadastro. Após salvar, o portal SHALL refletir o estado confirmado e permitir consultar a nova versão sem perder filtros e modo. Leitores e pendências imutáveis SHALL NOT oferecer ações de escrita.

#### Scenario: Editar pelo modal

- **WHEN** um integrante abre uma pendência ativa, altera sua descrição e salva
- **THEN** o modal informa sucesso somente após a gravação confirmada
- **AND** a listagem e o histórico mostram a nova versão com autor e horário corretos

#### Scenario: Finalização retira item do filtro de ativas

- **WHEN** um integrante finaliza uma pendência no recorte padrão
- **THEN** o item deixa de aparecer entre Ativas e permanece consultável pelos filtros de finalizadas
- **AND** um grupo de paciente sem outras correspondências é removido do resultado

#### Scenario: Conflito ou perda de elegibilidade durante edição

- **WHEN** outra pessoa altera a versão, a saída é confirmada ou o usuário perde autorização enquanto o modal está aberto
- **THEN** o salvamento não sobrescreve o estado atual
- **AND** a interface explica o conflito ou bloqueio, sem anunciar sucesso nem perder silenciosamente os dados digitados, inclusive campos complementares

#### Scenario: Editar somente dados de agendamento

- **WHEN** a equipe altera somente data agendada em uma RNM pelo modal
- **THEN** a listagem e o histórico refletem a nova data
- **AND** observações, contraste e sedação não são apagados por omissão do formulário

### Requirement: PP-07 Indicadores hospitalares independentes dos filtros

O portal SHALL exibir o número de pacientes distintos com pendências ativas na internação atual e a média e o máximo de idade dessas pendências desde a criação. O recorte SHALL ser hospitalar, independente de filtros, paginação e visualização. Sem pendências ativas, SHALL mostrar zero pacientes e ausência explícita de durações, sem valores inválidos.

#### Scenario: Calcular por pendência e contar pacientes distintos

- **WHEN** um paciente tem duas pendências ativas com idades de dois e oito dias e outro tem uma com cinco dias
- **THEN** o número de pacientes é dois, a idade média é cinco dias e a máxima é oito dias
- **AND** finalizadas e episódios fora do recorte atual não entram no cálculo

#### Scenario: Filtros não mudam a situação hospitalar

- **WHEN** o usuário aplica filtros sem correspondências, seleciona finalizadas ou muda de modo/página
- **THEN** os três indicadores continuam representando todas as pendências ativas atuais do hospital

#### Scenario: Casos ambíguos não contribuem para indicadores

- **WHEN** há ocupação conflitante ou mais de uma internação aberta candidata para um paciente com pendências
- **THEN** suas pendências não entram em contagem, média ou máximo do recorte atual
- **AND** pacientes identificados sem ambiguidade continuam contribuindo normalmente, sem contagem dupla por repetição equivalente da foto

### Requirement: PP-08 XLSX dos estados atuais filtrados

Qualquer usuário autenticado SHALL poder exportar XLSX com todos os resultados filtrados, não apenas a página visível, uma linha por pendência em seu estado atual, independentemente da visualização. O arquivo SHALL incluir contexto do paciente e episódio, primeira unidade, categoria, tipo, observações, campos complementares, status e autoria/horários. SHALL usar datas nativas, textos literais, campos não aplicáveis vazios, filtros e cabeçalho fixo, sem versões históricas, fórmulas de texto ou resíduos persistidos no servidor.

#### Scenario: Leitor exporta resultado completo

- **WHEN** um usuário autenticado fora do grupo Desospitalização exporta um resultado com várias páginas
- **THEN** recebe um XLSX válido com todas as pendências correspondentes aos filtros
- **AND** o modo por paciente não concatena várias pendências em uma única linha

#### Scenario: Colunas e estado atual

- **WHEN** o arquivo é aberto em leitor compatível com Excel
- **THEN** contém ID da pendência, ID da internação, Registro, Nome, Unidade atual, Leito, Primeira unidade de internação, Especialidade, Categoria, Tipo, Descrição/observação, Agendada?, Data agendada, Contraste, Sedação, Início do tratamento, Previsão de término, Assinatura do sumário em, Status, Criado em, Criado por, Atualizado em e Atualizado por, nessa ordem
- **AND** não contém versões históricas nem apresenta nome de usuário humano como autor de uma alteração do Sistema

#### Scenario: Texto potencialmente interpretável como fórmula

- **WHEN** qualquer campo textual exportado contém conteúdo que poderia ser tratado como fórmula pelo leitor de planilhas
- **THEN** ele permanece texto literal, não uma fórmula executável
- **AND** as células de data continuam sendo datas nativas, sem tratar todo o arquivo como texto

#### Scenario: Exportação usa o mesmo recorte conservador

- **WHEN** a foto contém ocupações conflitantes, episódios abertos ambíguos e repetições equivalentes de casos válidos
- **THEN** o XLSX exclui os mesmos casos ambíguos das duas visualizações e exporta os válidos sem duplicação

#### Scenario: Resultado vazio

- **WHEN** nenhum registro corresponde ao recorte
- **THEN** o XLSX permanece válido, com cabeçalhos e nenhuma linha de pendência
- **AND** a exportação não cria arquivo clínico residual no servidor

#### Scenario: Ausente não significa Não

- **WHEN** o arquivo contém RNM sem sedação informada, Tomografia não agendada e Regulação sem campos de agendamento
- **THEN** Sedação da RNM informa Não informado, Agendada? da Tomografia informa Não e Agendada? de Regulação fica vazia
- **AND** Sim sem data exporta Sim e uma célula de data vazia
- **AND** dados aplicáveis desconhecidos de registros antigos não são convertidos em Não

#### Scenario: Datas e usabilidade da planilha

- **WHEN** o usuário abre um XLSX com período de tratamento e assinatura
- **THEN** pode ordenar e filtrar as datas como datas, com formato brasileiro e horário institucional nos instantes
- **AND** o cabeçalho permanece fixo durante rolagem e os filtros abrangem todas as colunas

### Requirement: PP-09 Proteção de cache das superfícies clínicas

Respostas autenticadas da feature que contenham informação clínica SHALL declarar Cache-Control com private e no-store, incluindo HTML contextual/agregado, formulários, fragmentos de histórico e XLSX. A proteção SHALL permanecer na reexibição de formulários com erros, sem depender apenas da autenticação.

#### Scenario: HTML e fragmentos impedem armazenamento compartilhado

- **WHEN** um usuário autenticado consulta contexto, agregado, formulário ou histórico, ou recebe formulário com erro
- **THEN** a resposta contém as diretivas private e no-store em Cache-Control

#### Scenario: Download mantém proteção de cache

- **WHEN** um autenticado baixa o XLSX, inclusive vazio
- **THEN** a resposta do arquivo contém as diretivas private e no-store em Cache-Control

### Requirement: PP-10 Cadastro individual progressivo

O portal SHALL cadastrar uma pendência por vez, mantendo paciente e internação identificados. SHALL permitir selecionar categoria e depois tipo, com cada opção de tipo exibindo sua categoria para distinguir homônimos; exibir somente campos aplicáveis; oferecer Salvar e Salvar e adicionar outra; e preservar entradas válidas em erros. Cadastro, edição contextual e edição rápida SHALL compartilhar regras de preenchimento e acessibilidade por teclado.

#### Scenario: Selecionar categoria e descobrir campos

- **WHEN** a equipe escolhe Controle infeccioso e Antibióticos
- **THEN** vê início e previsão de término opcionais, sem campos de agendamento, contraste ou assinatura
- **AND** pode salvar sem observações e sem datas

#### Scenario: Buscar RNM com contexto

- **WHEN** a equipe procura RNM na lista de tipos e há duas entradas RNM em categorias distintas
- **THEN** cada opção exibe Categoria > Tipo, distinguindo Exames de imagem > RNM de CHD > RNM
- **AND** selecionar uma delas define a categoria correspondente automaticamente

#### Scenario: Adicionar outra sem duplicação

- **WHEN** a equipe salva uma pendência com Salvar e adicionar outra
- **THEN** vê confirmação do registro e um formulário novo para o mesmo paciente e internação
- **AND** os campos específicos anteriores não são copiados nem gravados novamente ao atualizar a página

#### Scenario: Trocar classificação com detalhes preenchidos

- **WHEN** a equipe troca um tipo com detalhes preenchidos por um tipo de outro perfil
- **THEN** a interface avisa sobre os detalhes que deixarão de se aplicar e permite cancelar a troca
- **AND** somente uma confirmação explícita permite salvar a remoção desses detalhes, preservados no histórico em edições

#### Scenario: Observações condicionais e erro de preenchimento

- **WHEN** a equipe tenta cadastrar Regulação > Outros sem observações
- **THEN** vê erro junto ao campo, sem perder categoria, tipo ou entradas válidas
- **AND** selecionar um tipo definido retira a exigência de texto, sem apagar automaticamente o texto digitado

#### Scenario: Usar em celular

- **WHEN** um integrante cadastra e edita uma pendência em viewport móvel
- **THEN** consegue selecionar classificação, preencher detalhes, salvar e acessar histórico sem rolagem horizontal global
- **AND** não precisa navegar por um checklist com todos os tipos e campos simultaneamente
