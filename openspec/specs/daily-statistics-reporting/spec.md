# daily-statistics-reporting Specification

## Purpose

Definir o relatório estatístico diário, nominal e auditável por setor, baseado
em fotografias censitárias aceitas e evidências clínicas persistidas, com
consulta protegida, revisão automática e exportação XLSX reproduzível.

## Requirements

### Requirement: O dia estatístico usa censos concluídos em limites locais explícitos

O sistema SHALL avaliar abertura e fechamento em `America/Bahia` usando o
momento de conclusão dos censos aceitos, sem usar a conclusão tardia do lote de
sincronizações clínicas como procedência da fotografia.

#### Scenario: Censo de abertura é escolhido

- **WHEN** um dia possui censos aceitos concluídos a partir de 00:00 e antes de
  03:00 no horário local
- **THEN** o primeiro desses censos é escolhido como censo de abertura
- **AND** ele pode ter iniciado no dia civil anterior

#### Scenario: Censo de fechamento é escolhido

- **WHEN** um dia possui censos aceitos iniciados a partir de 20:00 e concluídos
  antes da meia-noite local
- **THEN** o último desses censos é escolhido como censo de fechamento

#### Scenario: Dia não atende aos dois limites

- **WHEN** falta um censo de abertura ou um censo de fechamento distinto
- **THEN** o dia não é marcado como completo
- **AND** ele não é escolhido como data default do relatório

#### Scenario: Lote clínico termina em outro dia

- **WHEN** o lote de sincronizações clínicas associado ao ciclo termina depois
  do dia da fotografia censitária
- **THEN** seu horário de conclusão não altera os censos de abertura e
  fechamento selecionados

### Requirement: Somente censos aceitos participam do relatório

O sistema MUST usar somente fotografias completas, com procedência única e
medição oficial exata, e MUST manter indisponíveis valores que não possam ser
associados com segurança ao censo selecionado.

#### Scenario: Censo completo possui procedência exata

- **WHEN** um censo concluído com sucesso possui a cobertura mínima exigida,
  todas as linhas pertencem à mesma execução e existe medição oficial dessa
  execução
- **THEN** ele é elegível como censo aceito

#### Scenario: Censo incompleto ou de procedência mista

- **WHEN** uma fotografia é incompleta, mistura execuções ou não possui medição
  oficial exata
- **THEN** ela não é elegível como abertura ou fechamento
- **AND** o sistema não reutiliza medição de outro censo

#### Scenario: Falha intermediária não é ocultada

- **WHEN** existem falhas ou intervalos de qualidade entre abertura e fechamento
  sem invalidar os dois limites obrigatórios
- **THEN** o relatório registra aviso de qualidade
- **AND** não apresenta o período como livre de lacunas

### Requirement: A primeira transição usa uma âncora anterior

O sistema SHALL comparar o censo de abertura com o último censo aceito anterior
para detectar mudanças já visíveis na primeira fotografia, usando essa
fotografia anterior apenas como âncora.

#### Scenario: Paciente surge no primeiro censo do dia

- **WHEN** um paciente estava ausente na âncora anterior e presente no censo de
  abertura
- **THEN** a mudança é candidata a evento de entrada no novo dia
- **AND** a âncora não integra a fotografia final nem as métricas do novo dia

#### Scenario: Não existe âncora anterior

- **WHEN** não existe censo aceito anterior ao censo de abertura
- **THEN** o relatório sinaliza qualidade degradada
- **AND** não inventa entradas a partir de uma comparação inexistente

### Requirement: Movimentações são derivadas de fotografias consecutivas

O sistema SHALL comparar todos os censos aceitos consecutivos do período e
MUST representar somente movimentos confirmados ou detectados pelas fontes
disponíveis.

#### Scenario: Paciente muda de agrupamento oficial

- **WHEN** o mesmo paciente aparece no agrupamento A e depois no agrupamento B
  em censos consecutivos
- **THEN** o sistema registra uma transferência interna única de A para B
- **AND** a transferência aparece como saída de A e entrada em B

#### Scenario: Paciente muda apenas de leito no mesmo agrupamento

- **WHEN** o paciente troca de leito sem mudar de agrupamento oficial
- **THEN** o sistema não registra nova entrada nem nova saída setorial

#### Scenario: Movimento ocorre integralmente entre dois censos

- **WHEN** uma movimentação não altera nenhuma das fotografias persistidas
- **THEN** o sistema não afirma tê-la observado
- **AND** a interface informa que o relatório contém eventos confirmados ou
  detectados, não observação contínua

### Requirement: Entradas seguem classificação institucional explícita

O sistema SHALL classificar a chegada ao setor como internação ou transferência
interna sem inferir origem desconhecida como origem externa.

#### Scenario: Origem externa ao hospital

- **WHEN** a entrada possui origem classificada como externa ao hospital
- **THEN** o evento é classificado como internação

#### Scenario: Origem hospitalar monitorada ou não monitorada

- **WHEN** a origem é emergência, centro cirúrgico ou outro setor hospitalar,
  ainda que não monitorado
- **THEN** o evento é classificado como admissão por transferência interna

#### Scenario: Origem insuficiente ou contraditória

- **WHEN** as fontes não permitem classificar a natureza ou a origem da entrada
  com segurança
- **THEN** o sistema exibe `Entrada no setor — origem não identificada`
- **AND** não a converte silenciosamente em internação

#### Scenario: Transferência é confirmada sem setor de origem

- **WHEN** evidência independente confirma transferência interna, mas o setor de
  origem não pode ser identificado
- **THEN** o sistema exibe `Transferência interna — origem não identificada`
- **AND** preserva o destino confirmado sem inventar a origem

### Requirement: Saídas seguem precedência determinística

O sistema MUST classificar saídas na ordem óbito, saída hospitalar,
transferência interna e saída com destino não identificado, sem contar o mesmo
episódio em mais de uma categoria final.

#### Scenario: Óbito e alta concorrem

- **WHEN** evidências de óbito e alta correspondem ao mesmo episódio
- **THEN** o evento final é classificado como óbito
- **AND** não é contado também como saída hospitalar

#### Scenario: Saída hospitalar possui saída efetiva

- **WHEN** existe uma saída hospitalar efetiva válida para o episódio e não
  existe óbito prevalente
- **THEN** o evento é classificado como saída hospitalar/alta

#### Scenario: Paciente aparece em outro setor

- **WHEN** um paciente deixa um setor e aparece posteriormente em outro setor
  hospitalar sem óbito ou saída hospitalar prevalente
- **THEN** o evento é classificado como saída por transferência interna

#### Scenario: Transferência é confirmada sem setor de destino

- **WHEN** evidência independente confirma transferência interna, mas o setor de
  destino não pode ser identificado
- **THEN** o sistema exibe `Transferência interna — destino não identificado`
- **AND** não inventa um setor de destino

#### Scenario: Desaparecimento não possui explicação

- **WHEN** um paciente deixa de aparecer e nenhuma evidência permite aplicar as
  categorias anteriores
- **THEN** o sistema exibe `Saída do setor — destino não identificado`
- **AND** não chama o evento de transferência
- **AND** não o conta como alta hospitalar

### Requirement: Horário clínico e detecção permanecem distintos

O sistema SHALL preservar data e hora clínicas quando disponíveis e SHALL
mostrar separadamente o momento ou intervalo em que o evento foi detectado.

#### Scenario: Evento possui data e hora clínicas

- **WHEN** a fonte informa data e hora válidas
- **THEN** o relatório exibe essa data e hora como momento do evento
- **AND** exibe a detecção separadamente quando ela difere

#### Scenario: Evento possui somente data

- **WHEN** a fonte informa data válida sem hora
- **THEN** o relatório exibe `hora não informada`
- **AND** não sintetiza 00:00, 12:00 ou fim do dia
- **AND** exibe o horário ou intervalo de detecção

#### Scenario: Evento possui apenas observação censitária

- **WHEN** não existe momento clínico mais preciso que a transição entre dois
  censos
- **THEN** o relatório preserva o intervalo entre a observação anterior e a
  detecção
- **AND** não apresenta `detected_at` como horário clínico

### Requirement: Setor de alta ou óbito pode ser inferido com procedência

O sistema SHALL atribuir alta ou óbito ao último setor conhecido anterior ao
evento quando a evidência não trouxer setor, mantendo explícita a natureza
inferida dessa atribuição.

#### Scenario: Último setor anterior é unívoco

- **WHEN** uma alta ou óbito não informa setor e existe uma última posição
  censitária unívoca anterior ao evento
- **THEN** o evento é associado àquele agrupamento oficial
- **AND** a interface identifica o setor como inferido

#### Scenario: Setor não pode ser atribuído

- **WHEN** não existe posição anterior unívoca e confiável
- **THEN** o evento permanece com setor não determinado
- **AND** não é atribuído arbitrariamente ao setor final do paciente

### Requirement: A fotografia final preserva o contexto histórico oficial

O sistema SHALL usar o censo de fechamento, a medição exata e o catálogo
vigente naquele censo para apresentar os agrupamentos oficiais e os pacientes
presentes ao final do dia.

#### Scenario: Agrupamento possui capacidade calculável

- **WHEN** a medição final contém um agrupamento oficial calculável
- **THEN** o relatório apresenta pacientes, capacidade, lotação, saldo e
  excedente persistidos para aquele agrupamento

#### Scenario: Agrupamento não possui capacidade calculável

- **WHEN** o catálogo final classifica o agrupamento como não tarifado, pendente
  ou sem capacidade
- **THEN** o relatório preserva esse estado
- **AND** não calcula percentual ou saldo ad hoc

#### Scenario: Catálogo possui partições oficiais

- **WHEN** o catálogo histórico divide um código de origem em mais de um
  agrupamento, como as partições da 3A
- **THEN** o relatório mantém as partições e seus valores independentes

#### Scenario: Lista nominal representa o fechamento

- **WHEN** o usuário consulta um dia completo
- **THEN** a lista de pacientes de cada setor corresponde ao censo de
  fechamento daquele dia
- **AND** não usa a situação hospitalar atual

### Requirement: Relatórios diários são materializados e versionados

O sistema SHALL materializar uma revisão reproduzível por dia completo, SHALL
permitir regeneração idempotente e MUST preservar procedência suficiente para
auditar revisões automáticas.

#### Scenario: Dia posterior à ativação é finalizado

- **WHEN** o dia possui abertura e fechamento válidos após a ativação da
  feature
- **THEN** o sistema materializa uma revisão pronta para consulta

#### Scenario: Dia anterior à ativação é consultado

- **WHEN** o usuário seleciona uma data anterior à ativação
- **THEN** o sistema informa que não existe relatório
- **AND** não tenta reconstruí-lo automaticamente

#### Scenario: Materialização é repetida sem mudança de fonte

- **WHEN** o mesmo dia é materializado novamente sem mudança das evidências
- **THEN** o conteúdo lógico não é duplicado
- **AND** a revisão corrente permanece determinística

#### Scenario: Evidência tardia altera o relatório

- **WHEN** uma alta, óbito ou correção de evidência chega depois da primeira
  materialização
- **THEN** o sistema pode gerar nova revisão automática auditável
- **AND** preserva a mesma fotografia censitária de fechamento
- **AND** a revisão anterior não é apresentada como corrente

#### Scenario: Usuário tenta corrigir evento manualmente

- **WHEN** um usuário acessa a página nesta versão da capability
- **THEN** nenhuma ação de inclusão, reclassificação ou exclusão manual é
  oferecida

### Requirement: Página estatística exige autorização dedicada

O sistema MUST proteger a consulta nominal e a exportação com permissões
dedicadas e MUST impedir cache compartilhado do conteúdo sensível.

#### Scenario: Usuário possui permissão de consulta

- **WHEN** um usuário autenticado com permissão de consulta abre
  `/statistics/`
- **THEN** a página do relatório é exibida
- **AND** a resposta impede armazenamento em cache

#### Scenario: Usuário autenticado não possui permissão

- **WHEN** um usuário autenticado sem permissão de consulta abre
  `/statistics/`
- **THEN** o acesso é negado
- **AND** nenhum dado nominal é renderizado

#### Scenario: Permissão de consulta não implica exportação

- **WHEN** um usuário possui consulta, mas não possui permissão de exportação
- **THEN** o usuário não consegue baixar o XLSX

### Requirement: Seletor de data usa o último dia completo seguro

O sistema SHALL abrir ontem quando ontem estiver completo e, caso contrário,
SHALL usar o dia completo mais recente, sem selecionar hoje automaticamente.

#### Scenario: Ontem possui relatório completo

- **WHEN** o usuário abre a página sem informar data e ontem está completo
- **THEN** ontem é selecionado

#### Scenario: Ontem não está completo

- **WHEN** ontem não possui relatório completo e existe um dia completo anterior
- **THEN** o dia completo mais recente é selecionado

#### Scenario: Hoje possui censos parciais

- **WHEN** hoje já possui fotografias censitárias e a página é aberta sem data
- **THEN** hoje não é selecionado automaticamente

### Requirement: Setores e listas usam collapsibles acessíveis e badges

A página SHALL apresentar uma lista expansível por agrupamento oficial, com
métricas sempre visíveis e listas internas de entradas, saídas, eventos com
origem ou destino não identificado e pacientes do fechamento.

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

### Requirement: Pacientes são ordenados naturalmente por leito

O sistema SHALL ordenar pacientes por leito em ordem natural alfanumérica,
colocando ausência de leito ao final e usando nome e prontuário como desempate.

#### Scenario: Leitos numéricos e alfanuméricos são misturados

- **WHEN** uma lista contém `2`, `10`, `101A`, `UTI02` e `UTI10`
- **THEN** a ordenação respeita a progressão numérica dentro dos componentes
  textuais

#### Scenario: Paciente não possui leito

- **WHEN** um paciente não possui leito informado
- **THEN** ele aparece depois dos pacientes com leito
- **AND** nome e prontuário definem a ordem entre pacientes sem leito

### Requirement: Exportação XLSX reproduz a revisão selecionada

O sistema SHALL exportar a revisão corrente da data selecionada em um workbook
com uma folha por agrupamento oficial e MUST preservar as mesmas categorias e
ordenação apresentadas na página.

#### Scenario: Workbook possui folha por setor

- **WHEN** um usuário autorizado exporta um relatório
- **THEN** o workbook contém uma folha por agrupamento oficial exibido
- **AND** cada folha identifica o nome completo do setor

#### Scenario: Workbook possui linhas sem setor atribuível

- **WHEN** a revisão selecionada contém evento sem origem nem destino setorial
  ou paciente do fechamento sem setor atribuível
- **THEN** o workbook contém também a folha condicional
  `Setor não identificado`
- **AND** essa folha preserva essas linhas sem representá-las como agrupamento
  oficial

#### Scenario: Folha contém todas as tabelas

- **WHEN** uma folha é gerada
- **THEN** ela contém, nesta ordem, internações, admissões por transferência,
  óbitos, saídas por transferência, altas hospitalares, eventos com origem ou
  destino não identificado e pacientes do fechamento
- **AND** cada seção mostra sua quantidade
- **AND** seções vazias permanecem presentes

#### Scenario: Campos nominais e temporais são exportados

- **WHEN** uma linha de evento é exportada
- **THEN** ela inclui leito, nome, prontuário, especialidade, data/hora clínica,
  origem ou destino, tipo e detecção conforme disponíveis

#### Scenario: Nome de folha é incompatível com Excel

- **WHEN** nomes de setores excedem limites, contêm caracteres inválidos ou
  colidem depois da normalização
- **THEN** o sistema gera nomes de folha válidos e únicos
- **AND** preserva o nome completo dentro da folha

#### Scenario: Valor nominal parece fórmula

- **WHEN** um valor textual começa por um caractere interpretável como fórmula
- **THEN** o workbook o grava como texto seguro

### Requirement: Toda exportação servida produz auditoria

O sistema MUST registrar cada workbook gerado e servido, sem registrar dados
nominais no log e sem persistir o arquivo exportado.

#### Scenario: Exportação é servida com sucesso

- **WHEN** o sistema gera e serve o XLSX ao usuário
- **THEN** registra usuário, data/hora, data selecionada, revisão e contagens
  agregadas da exportação
- **AND** o arquivo não é persistido no servidor

#### Scenario: Geração falha antes da resposta

- **WHEN** a geração do workbook falha antes de ele ser servido
- **THEN** o sistema não registra sucesso de download
- **AND** pode registrar falha operacional sem identidade clínica
