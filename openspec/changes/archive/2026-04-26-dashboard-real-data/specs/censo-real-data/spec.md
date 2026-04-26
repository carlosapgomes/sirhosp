# censo-real-data

## ADDED Requirements

### Requirement: Página de censo exibe pacientes reais do CensusSnapshot

O sistema SHALL exibir na página `/censo/` a lista de pacientes atualmente
internados, obtida do CensusSnapshot mais recente filtrando por `bed_status="occupied"`.

#### Scenario: CensusSnapshot com pacientes ocupados

- **WHEN** o usuário autenticado acessa `/censo/` e existe ao menos um CensusSnapshot
  recente com leitos ocupados
- **THEN** a página exibe uma lista de pacientes com leito, nome, prontuário e
  setor, ordenados por leito

#### Scenario: Nenhum dado de censo disponível

- **WHEN** o usuário autenticado acessa `/censo/` e não existe nenhum CensusSnapshot
- **THEN** a página exibe mensagem informativa de que não há dados disponíveis

### Requirement: Filtro de setor usa valores reais do CensusSnapshot

O sistema SHALL gerar a lista de opções do dropdown "Setor" a partir dos setores
distintos com leitos ocupados no CensusSnapshot mais recente.

#### Scenario: Dropdown populado dinamicamente

- **WHEN** o usuário autenticado acessa `/censo/` e há CensusSnapshots com
  leitos ocupados em setores como "UTI Adulto" e "Clínica Médica"
- **THEN** o dropdown "Setor" exibe exatamente esses setores como opções (mais
  a opção "Todos os setores")

#### Scenario: Filtro por setor funciona

- **WHEN** o usuário seleciona um setor específico no dropdown e submete o filtro
- **THEN** a página exibe apenas pacientes daquele setor

### Requirement: Busca textual no censo funciona com dados reais

O sistema SHALL permitir busca por nome ou prontuário nos pacientes do censo,
filtrando os registros do CensusSnapshot ocupado mais recente.

#### Scenario: Busca por nome

- **WHEN** o usuário digita parte do nome de um paciente no campo de busca e submete
- **THEN** a página exibe apenas pacientes cujo nome contém o termo buscado

#### Scenario: Busca por prontuário

- **WHEN** o usuário digita um número de prontuário no campo de busca e submete
- **THEN** a página exibe apenas o paciente com aquele prontuário

### Requirement: Página de censo mantém visualização mobile

O sistema SHALL manter o layout responsivo da página de censo, com visualização
em tabela no desktop e cards no mobile, usando os mesmos breakpoints e classes
CSS existentes (`sirhosp-censo-table-wrapper` e `sirhosp-censo-cards`).

#### Scenario: Layout responsivo preservado

- **WHEN** o usuário acessa `/censo/` em viewport desktop
- **THEN** a tabela é exibida normalmente
- **WHEN** o usuário acessa `/censo/` em viewport mobile
- **THEN** os cards substituem a tabela

### Requirement: Linhas da tabela de censo linkam para prontuário

O sistema SHALL manter o comportamento de clique na linha/card do censo redirecionando
para a busca de paciente pelo prontuário (`/patients/?q=<prontuario>`).

#### Scenario: Clique em paciente do censo

- **WHEN** o usuário clica em um paciente na página de censo
- **THEN** o sistema redireciona para `/patients/?q=<prontuario>` com o prontuário
  daquele paciente
