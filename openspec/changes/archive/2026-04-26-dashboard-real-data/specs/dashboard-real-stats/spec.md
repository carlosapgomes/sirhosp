# dashboard-real-stats

## ADDED Requirements

### Requirement: Dashboard mostra indicadores reais de internados

O sistema SHALL exibir na página de dashboard o número de pacientes atualmente
internados, obtido do CensusSnapshot mais recente filtrando por `bed_status="occupied"`.

#### Scenario: CensusSnapshot com leitos ocupados

- **WHEN** o usuário autenticado acessa o dashboard e existe ao menos um CensusSnapshot
  com leitos em status "occupied"
- **THEN** o dashboard exibe o número exato de leitos ocupados no card "Internados"

#### Scenario: Nenhum CensusSnapshot ao tentar exibir internados

- **WHEN** o usuário autenticado acessa o dashboard e não existe nenhum CensusSnapshot
- **THEN** o dashboard exibe "0" no card "Internados"

### Requirement: Dashboard mostra total real de pacientes cadastrados

O sistema SHALL exibir no dashboard o número total de pacientes cadastrados,
obtido via `Patient.objects.count()`.

#### Scenario: Pacientes cadastrados

- **WHEN** o usuário autenticado acessa o dashboard
- **THEN** o dashboard exibe o número total de registros na tabela Patient no card
  "Cadastrados"

### Requirement: Dashboard mostra altas nas últimas 24 horas

O sistema SHALL exibir no dashboard o número de admissões com `discharge_date`
dentro das últimas 24 horas (a partir do momento da requisição).

#### Scenario: Pacientes receberam alta nas últimas 24h

- **WHEN** o usuário autenticado acessa o dashboard e existem Admissions com
  `discharge_date` nas últimas 24 horas
- **THEN** o dashboard exibe a contagem exata no card "Altas (24h)"

#### Scenario: Nenhuma alta nas últimas 24h

- **WHEN** o usuário autenticado acessa o dashboard e não há Admissions com
  `discharge_date` nas últimas 24 horas
- **THEN** o dashboard exibe "0" no card "Altas (24h)"

### Requirement: Dashboard mostra status real da coleta de dados

O sistema SHALL substituir os dados demo da seção "Status da Coleta de Dados" por
informações reais obtidas do CensusSnapshot mais recente.

#### Scenario: CensusSnapshot disponível para coleta

- **WHEN** o usuário autenticado acessa o dashboard e existe ao menos um CensusSnapshot
- **THEN** o dashboard exibe o número de setores distintos presentes no snapshot
  mais recente em "Setores monitorados" e a data/hora do `captured_at` em "Última
  varredura completa"

#### Scenario: Sem CensusSnapshot para status de coleta

- **WHEN** o usuário autenticado acessa o dashboard e não existe nenhum CensusSnapshot
- **THEN** o dashboard exibe mensagem informativa de que não há dados de coleta
  disponíveis

### Requirement: Dashboard tem card "Leitos Vagas" com link para /beds/

O sistema SHALL exibir um card adicional na seção de ações rápidas do dashboard
com ícone, título "Leitos" (ou "Leitos Vagas"), descrição e link para `/beds/`.

#### Scenario: Card de leitos no dashboard

- **WHEN** o usuário autenticado acessa o dashboard
- **THEN** um card com link para `/beds/` está visível na seção de ações rápidas
  do dashboard
