# pending-items-portal — Delta

## MODIFIED Requirements

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
