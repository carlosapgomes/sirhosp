# pending-items-portal — Delta

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: PP-10 Cadastro individual progressivo

O portal SHALL cadastrar uma pendência por vez, mantendo paciente e internação identificados. SHALL permitir selecionar categoria e depois tipo, ou buscar tipo com categoria visível; exibir somente campos aplicáveis; oferecer Salvar e Salvar e adicionar outra; e preservar entradas válidas em erros. Cadastro, edição contextual e edição rápida SHALL compartilhar regras de preenchimento e acessibilidade por teclado.

#### Scenario: Selecionar categoria e descobrir campos

- **WHEN** a equipe escolhe Controle infeccioso e Antibióticos
- **THEN** vê início e previsão de término opcionais, sem campos de agendamento, contraste ou assinatura
- **AND** pode salvar sem observações e sem datas

#### Scenario: Buscar RNM com contexto

- **WHEN** a equipe busca RNM e seleciona Exames de imagem > RNM
- **THEN** categoria e tipo ficam coerentes e aparecem Agendada?, Contraste e Sedação
- **AND** selecionar Sim em Agendada? disponibiliza a data opcional
- **AND** os controles possuem rótulos acessíveis e funcionam por teclado

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
