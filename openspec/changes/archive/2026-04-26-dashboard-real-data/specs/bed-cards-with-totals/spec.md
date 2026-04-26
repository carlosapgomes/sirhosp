# bed-cards-with-totals

## ADDED Requirements

### Requirement: Página /beds/ exibe totalização agregada no topo

O sistema SHALL exibir no topo da página `/beds/` cards de resumo com a contagem
total de leitos por status, agregados de todos os setores do CensusSnapshot mais recente.

#### Scenario: Totais agregados exibidos

- **WHEN** o usuário autenticado acessa `/beds/` e existe CensusSnapshot com leitos
  em múltiplos status
- **THEN** cards no topo da página exibem: total de ocupados, total de vagos,
  total em manutenção, total reservados, total em isolamento e total geral de leitos

#### Scenario: Sem dados de censo

- **WHEN** o usuário autenticado acessa `/beds/` e não existe CensusSnapshot
- **THEN** a página exibe mensagem "Nenhum dado de censo disponível" (comportamento
  existente preservado)

### Requirement: Página /beds/ usa layout de cards em vez de tabela

O sistema SHALL exibir os setores e leitos em layout de cards Bootstrap com
comportamento expand/collapse, substituindo o layout atual baseado em `<table>`.

#### Scenario: Cards de setor com collapse

- **WHEN** o usuário autenticado acessa `/beds/` e há dados de censo
- **THEN** cada setor é exibido como um card com nome do setor e badges de status
  (ocupados, vagos, etc.)
- **AND** ao clicar no card, expande para mostrar a lista de leitos daquele setor
  com detalhes (leito, status, paciente)

#### Scenario: Layout responsivo

- **WHEN** o usuário acessa `/beds/` em viewport mobile
- **THEN** os cards de setor são exibidos em coluna única, empilhados verticalmente
  com toque para expandir

#### Scenario: Card de setor colapsado por padrão

- **WHEN** o usuário acessa `/beds/` pela primeira vez
- **THEN** todos os cards de setor aparecem colapsados (apenas cabeçalho visível),
  mostrando nome do setor e badges de contagem

### Requirement: Sidebar inclui link para Leitos

O sistema SHALL adicionar um item de navegação "Leitos" na sidebar do portal,
apontando para `/beds/`.

#### Scenario: Link de leitos na sidebar

- **WHEN** o usuário autenticado visualiza a sidebar
- **THEN** o menu exibe "Leitos" com ícone `bi bi-door-open` (ou similar) e link
  para `/beds/`

#### Scenario: Link ativo quando na página de leitos

- **WHEN** o usuário está na página `/beds/`
- **THEN** o link "Leitos" na sidebar aparece com classe `active`
