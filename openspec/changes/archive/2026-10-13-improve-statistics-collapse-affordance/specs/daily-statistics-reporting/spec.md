# Spec Delta

## MODIFIED Requirements

### Requirement: Setores e listas usam collapsibles acessíveis e badges

A página SHALL apresentar uma lista expansível por agrupamento oficial, com
métricas sempre visíveis e listas internas de entradas, saídas, eventos com
origem ou destino não identificado e pacientes do fechamento. Os controles dos
dois níveis SHALL indicar visualmente ação e estado sem depender de hover ou
apenas de cor, preservando operação acessível e contagens.

#### Scenario: Cabeçalho do setor é exibido

- **WHEN** um setor possui relatório materializado
- **THEN** seu cabeçalho mostra badges de pacientes, capacidade, lotação, saldo
  ou excedente conforme aplicável
- **AND** as métricas podem ser lidas sem expandir o setor

#### Scenario: Listas internas são expandidas

- **WHEN** o usuário expande um setor
- **THEN** pode expandir as listas de entradas, saídas, eventos com origem ou
  destino não identificado e pacientes
- **AND** cada lista mostra badge com sua quantidade
- **AND** cada evento sem um endpoint usa um dos rótulos descritivos definidos
  pela sua natureza confirmada
- **AND** controles expansíveis expõem estado acessível

#### Scenario: Lista vazia é exibida

- **WHEN** uma categoria não possui eventos
- **THEN** seu título e badge zero continuam visíveis
- **AND** a interface apresenta estado vazio explícito

#### Scenario: Linha nominal não possui setor atribuível

- **WHEN** um evento materializado não possui setor de origem nem de destino ou
  um paciente do fechamento não possui setor atribuível
- **THEN** a página exibe a linha uma única vez na seção de relatório
  `Setor não identificado`
- **AND** não a omite nem a atribui arbitrariamente a um agrupamento oficial

#### Scenario: Controles fechados possuem indicador de expansão

- **WHEN** um cabeçalho de setor ou categoria interna está visível e fechado
- **THEN** um chevron visível antes do título aponta à direita
- **AND** o controle comunica estado recolhido às tecnologias assistivas
- **AND** o ícone decorativo não é anunciado como parte do nome acessível

#### Scenario: Chevron acompanha abertura e fechamento nos dois níveis

- **WHEN** o usuário abre um setor ou uma categoria interna
- **THEN** o conteúdo correspondente fica visível e seu chevron aponta para baixo
- **AND** o estado acessível indica expansão
- **WHEN** o usuário recolhe o mesmo controle
- **THEN** o conteúdo é ocultado e seu chevron volta a apontar à direita
- **AND** o estado acessível volta a indicar recolhimento
- **AND** título, métricas e contador permanecem inalterados

#### Scenario: Categorias são reconhecíveis sem hover

- **WHEN** o setor está aberto e o ponteiro não está sobre suas categorias
- **THEN** cada categoria possui fundo neutro claro e borda discreta visíveis
- **AND** chevron, título e contador continuam legíveis
- **AND** o setor conserva maior destaque hierárquico que as categorias
- **AND** as categorias não recebem cores distintas por natureza do evento

#### Scenario: Categoria aberta mantém diferenciação discreta

- **WHEN** uma categoria interna está aberta sem hover nem foco
- **THEN** seu fundo apresenta diferenciação neutra em relação ao estado fechado
- **AND** o chevron para baixo também comunica a abertura sem depender da cor
- **AND** não é acrescentado texto repetido de expandir ou recolher

#### Scenario: Controles funcionam com teclado e toque

- **WHEN** o usuário navega por teclado até um setor ou categoria
- **THEN** o foco é visível e o título identifica o controle
- **AND** Enter ou Espaço alternam somente a expansão correspondente
- **WHEN** o usuário clica ou toca na linha do controle fora do texto
- **THEN** a mesma ação de expansão ou recolhimento é executada
- **AND** a área do controle possui altura mínima de 44 pixels CSS

#### Scenario: Título longo quebra sem comprometer indicador e contador

- **WHEN** a página é exibida em viewport de 375 pixels de largura e uma
  categoria possui título longo
- **THEN** o título quebra em múltiplas linhas, alinhadas após o chevron
- **AND** chevron e contador permanecem visíveis sem sobreposição ou compressão
- **AND** o contador permanece à direita do controle
- **AND** os cabeçalhos não introduzem rolagem horizontal

#### Scenario: Listas e setores preservam expansão independente

- **WHEN** o usuário abre uma categoria enquanto outra categoria ou setor está aberto
- **THEN** os outros controles mantêm seus estados de expansão
- **WHEN** o usuário recolhe e reabre o setor que contém uma categoria aberta
- **THEN** essa categoria preserva seu estado e seu chevron continua coerente
- **AND** nenhum controle é aberto automaticamente na carga inicial da página

#### Scenario: Indicadores abrangem a seção sem setor identificado

- **WHEN** a seção `Setor não identificado` é apresentada
- **THEN** seu cabeçalho e suas listas internas usam os mesmos indicadores
  dinâmicos e interação acessível dos demais grupos
- **AND** seus títulos, contagens e sinalização de qualidade são preservados

#### Scenario: Outros controles do portal permanecem inalterados

- **WHEN** o usuário consulta a navegação lateral ou outras páginas do portal
- **THEN** os ajustes visuais dos collapsibles estatísticos não alteram seus
  indicadores, cores ou comportamento
