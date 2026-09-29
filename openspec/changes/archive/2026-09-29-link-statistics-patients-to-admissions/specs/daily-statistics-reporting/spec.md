## ADDED Requirements

### Requirement: Linhas nominais navegam para a página de internações do paciente

O sistema SHALL tornar clicável cada linha nominal das listas de entradas,
saídas, eventos com origem ou destino não identificado e pacientes do
fechamento, apontando para a página de internações do paciente quando o
prontuário da linha resolver para exatamente um paciente, e SHALL oferecer a
busca por prontuário quando a resolução não for possível. A resolução MUST
ocorrer apenas em tempo de leitura, sem alterar a revisão materializada, a
impressão digital, o conteúdo exportado em XLSX ou as permissões existentes.
O sistema MUST NOT escolher arbitrariamente um paciente quando o prontuário
corresponder a mais de um candidato.

#### Scenario: Prontuário resolve exatamente um paciente

- **WHEN** uma linha nominal de qualquer lista possui prontuário que
  corresponde a exatamente um paciente no cadastro
- **THEN** o nome do paciente é um link para a página de internações daquele
  paciente
- **AND** o link abre a mesma página usada pela lista de pacientes de
  `/beds/`

#### Scenario: Prontuário não corresponde a paciente

- **WHEN** o prontuário da linha não corresponde a nenhum paciente
- **THEN** o nome do paciente é um link para a busca de pacientes filtrada
  pelo prontuário
- **AND** a linha não é omitida nem marcada como erro

#### Scenario: Prontuário corresponde a mais de um paciente

- **WHEN** o prontuário da linha corresponde a mais de um paciente, em
  sistemas de origem distintos ou não
- **THEN** a linha usa o link de busca por prontuário
- **AND** o sistema não vincula a linha a um único paciente arbitrário

#### Scenario: Linha sem prontuário

- **WHEN** uma linha nominal não possui prontuário
- **THEN** o nome permanece como texto simples, sem link

#### Scenario: Navegação não altera a revisão materializada nem o XLSX

- **WHEN** a página do relatório é renderizada com links de navegação
- **THEN** a revisão materializada, a impressão digital e o conteúdo exportado
  em XLSX permanecem inalterados, nas mesmas colunas e valores
- **AND** nenhum identificador resolvido é persistido pelo render
- **AND** o workbook não contém coluna ou valor derivado da resolução

#### Scenario: Cobertura inclui linhas sem setor atribuível

- **WHEN** a revisão contém linhas na seção `Setor não identificado`
- **THEN** essas linhas recebem a mesma navegação das linhas de setores
  oficiais
