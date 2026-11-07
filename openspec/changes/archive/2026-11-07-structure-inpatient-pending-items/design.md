# Design

## Context

Ver [proposal.md](proposal.md) para motivação e escopo e
[catalog.md](catalog.md) para a classificação completa. Este design é uma
proposta para revisão, não autorização de implementação.

Estado observado:

- `apps/pending_items/models.py` já define `PendingItemType`, `PendingItem`
  e `PendingItemRevision`, com FKs protegidas e revisões sequenciais.
- `services.py` valida texto obrigatório, grava estado/revisão atomicamente,
  serializa Admission antes de PendingItem e verifica versão observada.
- `forms.py` oferece apenas tipo e observação obrigatória. Templates
  contextuais e de edição rápida repetem a renderização desses controles.
- `queries.py` centraliza o recorte conservador atual, filtros e indicadores;
  `views_export.py` reutiliza esse recorte.
- `export.py` já usa openpyxl em memória e força todas as células a texto,
  inclusive horários. Testes atuais verificam exatamente esse contrato.
- A suíte Playwright em `tests/integration/test_pending_items_browser.py`
  já utiliza live_server, PostgreSQL sintético e assets locais fixados.
- PI-03/04/07/08 e PP-01/02/05/07/09 permanecem válidos. A mudança modifica
  explicitamente texto obrigatório universal, catálogo inicial somente Outro,
  campos editáveis, snapshots e esquema/tipagem do XLSX.

## Goals / Non-Goals

**Goals:** manter uma única identidade de pendência e seus caminhos seguros de
escrita; tornar os detalhes consultáveis em formulário, histórico, painel e
planilha; limitar variação a quatro perfis conhecidos.

**Non-Goals:** substituir o domínio existente, criar EAV/JSON genérico como
fonte dos dados, permitir configuração arbitrária de campos, mudar FSM,
permissões ou integrações clínicas. Não alterar scraping, workers, systemd ou
os fluxos de confirmação de saída/merge.

## Decisions

### D1 — Estender entidades e acrescentar categoria

Adicionar `PendingItemCategory` com nome único e slug estável único.
Acrescentar ao tipo:
FK de categoria, perfil fixo, indicação de complementos RNM e regra de
observação obrigatória. Slugs de tipos continuam globalmente únicos;
substituir unicidade global do nome por unicidade de nome dentro da categoria.
Isso permite RNM em Imagem e CHD sem misturar identidades. Slugs de categoria
e tipo são definíveis somente na criação e imutáveis depois, inclusive sem
uso. Modelo e admin devem rejeitar alterações, não apenas ocultar o controle;
renomear o nome visível não modifica a identidade usada pela carga.

Perfil possui somente quatro valores. Complementos RNM são uma capacidade
fixa dos dois tipos de RNM, permitida somente no perfil Agendamento; não são
um construtor de campos. Administração pode criar tipos nos perfis existentes,
mas não criar um quinto perfil nem mudar o contrato de um tipo já usado.
**Usado** significa referenciado por qualquer `PendingItem` ou por qualquer
`PendingItemRevision`, inclusive quando não há mais itens com esse tipo ou
quando todos estão finalizados. Não consultar apenas itens atuais/ativos.

O contrato protegido de tipo usado abrange **categoria, perfil, complementos
RNM e obrigatoriedade de observações**. A mudança de categoria não pode
reclassificar indiretamente todas as pendências; é necessário criar outro tipo
e usar a edição explícita, versionada, de cada pendência ativa pertinente.
Nomes visíveis de categoria/tipo continuam renomeáveis, salvo Outro.

Independentemente de uso, `outro` conserva nome Outro, categoria
`outras-pendencias`, perfil Registro simples, sem complementos RNM e com
observação obrigatória, além de não ser excluível. Regulação > Outros também
exige observação, sem depender de comparação frágil de rótulo. A inicialização
única do catálogo na migration segue a exceção delimitada em D8; manutenção
administrativa e reaplicação não podem usar essa exceção.

Alternativas descartadas: entidade nova em paralelo perderia o reaproveitamento
da FSM e integrações; uma tabela por procedimento multiplicaria persistência
e exportadores sem necessidade; nome globalmente único obrigaria rótulos
artificiais para RNM.

### D2 — Campos tipados, sem datas genéricas ambíguas

Acrescentar os seguintes campos a `PendingItem` e snapshots equivalentes a
`PendingItemRevision`:

| Informação               | Representação proposta | Aplicação               |
| ------------------------ | ---------------------- | ----------------------- |
| Agendada                 | Booleano anulável      | Agendamento             |
| Data agendada            | Data anulável          | Agendamento com Sim     |
| Início do tratamento     | Data anulável          | Tratamento com período  |
| Previsão de término      | Data anulável          | Tratamento com período  |
| Assinatura do sumário em | Data/hora anulável     | Assinatura de documento |
| Contraste                | Booleano anulável      | RNM                     |
| Sedação                  | Booleano anulável      | RNM                     |

`description` continua representando observações, agora podendo ficar vazio
conforme o tipo; não se duplica texto em um segundo campo. Categoria é obtida
pelo tipo no estado atual, sem FK redundante de categoria em PendingItem.

Datas de tratamento e agendamento são datas civis, não instantes convertidos
por timezone. Assinatura é um instante informado no fuso institucional.
Criação/finalização continuam sendo horários de operação do sistema: não são
substituídos pelas datas informadas pela equipe.

Nulo significa ausente, nunca Não. A aplicabilidade determina se a ausência é
Não informado ou Não aplicável. Agendada exige Sim/Não no novo cadastro e na
edição aplicável; nulo existe para compatibilidade histórica e perfis não
aplicáveis. Contraste e sedação aceitam nulo como Não informado.

Alternativas descartadas: um único campo data perderia a semântica; texto/JSON
livre tornaria validação e análise em Excel mais frágeis. Os poucos campos
anuláveis são proporcionais ao catálogo já conhecido.

### D3 — Uma validação de domínio compartilhada

Evoluir o caminho canônico de escrita em `services.py`, com validação
reutilizada pelos formulários, preservando locks, transação, elegibilidade,
autorização e token de versão. Não confiar apenas em campos ocultados no HTML.

Regras:

- Categoria/tipo devem corresponder; a classificação persistida vem do tipo.
- Observações são normalizadas como hoje e exigidas somente conforme o tipo.
- Campos complementares preenchidos fora do perfil são rejeitados.
- Agendada Não não aceita data. Sim aceita data ausente. Datas passadas são
  admitidas, sem supor erro por passagem do tempo.
- Previsão de término anterior ao início é inválida quando ambas existem;
  qualquer uma pode estar ausente. Não calcular duração ou término.
- Todos os campos participantes entram na comparação de mudança efetiva.
- Uma alteração só de detalhe deve criar versão; reenvio idêntico não cria.
- Troca de tipo preserva campos ainda aplicáveis. Para remover detalhes que
  deixarem de se aplicar, a interface deve avisar e exigir confirmação;
  reenvio direto sem confirmação da remoção deve ser rejeitado. Os valores
  removidos permanecem na revisão anterior.
- Alterar Agendada de Sim para Não com data já preenchida segue a mesma regra
  de confirmação de remoção, sem apagar silenciosamente a data.
- Finalizações humanas e por Sistema copiam os detalhes sem exigir novo
  preenchimento dos campos de cadastro.

#### Enforcement local e validação relacionada

Além da validação compartilhada, impor as constraints locais abaixo no banco,
com testes que tentem persistir estados inválidos sem passar pelo formulário:

| Etapa e tabela     | Invariante estrutural                                                                                                         |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| S1, tipo           | Perfil pertence aos quatro valores fixos; complementos RNM só são permitidos com perfil Agendamento                           |
| S1, revisão        | Perfil/capacidade RNM do snapshot obedecem à mesma relação quando conhecidos; metadados antigos nulos continuam desconhecidos |
| S2, item e revisão | Data agendada preenchida exige Agendada Sim; Agendada Não ou desconhecida não pode carregar uma data                          |
| S2, item e revisão | Início ou término pode ser nulo; quando ambos existem, previsão de término é maior ou igual ao início                         |

As constraints novas coexistem com as atuais de estado/finalização/versão.
Não exigir dados hoje ausentes para validar revisões antigas. Aplicabilidade
dos campos do item por perfil, coerência categoria/tipo e o conceito de tipo
usado dependem de relações: ficam no caminho de domínio/modelo/admin, com
testes diretos dessas fronteiras, não em CHECKs que consultem outra tabela.
Imutabilidade após criação/uso também exige comparar o estado persistido;
não prometer que uma CHECK local a implementa, nem introduzir triggers gerais.

Não acrescentar automações por datas. `close_pending_items_for_confirmed_exit`
continua idempotente, fechando somente ativas com autoria Sistema e motivo de
saída confirmada. Não tocar seus pontos de integração para mudar semântica.

### D4 — Snapshot completo, incluindo classificação observada

Além dos campos tipados de D2 e dos dados/autoria já existentes, cada revisão
nova preserva explicitamente estes metadados da classificação observada:

- Nome e slug da categoria.
- Nome e slug do tipo.
- Perfil do formulário.
- Booleano de habilitação dos complementos RNM.
- Booleano de obrigatoriedade de observações.

Esses metadados são entregues em S1; os sete valores complementares de item
listados em D2 entram em S2. Não confundir a capacidade RNM do tipo com as
respostas Contraste/Sedação da pendência. Metadados novos de revisões antigas
são anuláveis para expressar desconhecido; o nome do tipo e os demais dados
históricos já registrados continuam intactos. Renomear catálogo não reescreve
snapshots nem passa a exigir consulta ao contrato atual para interpretar uma
versão antiga.

Revisões antigas recebem campos novos ausentes, sem reconstrução textual nem
categoria histórica presumida. A tela deve explicar a ausência de informação
na versão antiga. Não criar versões de edição fictícias durante migration.

Snapshots são parte da gravação atômica atual; uma falha ao gravar revisão
reverte também os dados novos. Não criar histórico paralelo nem endpoint de
CRUD de revisões.

### D5 — Formulário progressivo e acessível com a stack atual

Usar Django Templates, HTMX e Bootstrap existentes. Compartilhar renderização
dos campos entre cadastro, edição contextual e edição rápida, evitando uma
segunda implementação das regras do perfil.

Fluxo primário: categoria -> tipo -> detalhes aplicáveis -> observações ->
salvar. Busca complementar filtra tipos por nome e apresenta Categoria > Tipo;
selecionar resultado define a categoria correspondente. Pode ser implementada
com os recursos locais existentes, sem biblioteca de busca externa.

Manter paciente e episódio visíveis. Não exibir checklist completo, dezenas
de campos vazios ou abas por categoria. Sim em Agendada revela a data;
complementos RNM são independentes. Mudanças de seleção não podem apagar texto
válido digitado sem aviso. Controles têm rótulos, foco previsível e operação
por teclado; erros ficam associados aos campos.

Salvar volta à lista contextual. Salvar e adicionar outra confirma o registro
e abre cadastro vazio para o mesmo episódio, sem copiar detalhes anteriores.
Usar POST/redirect/GET para não reenviar o cadastro ao atualizar a página.
Não introduzir cadastro em lote ou endpoint público novo. Se fragmentos HTMX
exigirem rota auxiliar, aplicar autenticação, autorização pertinente e cache
private/no-store como nas superfícies existentes.

### D6 — Apresentação e filtros sem alterar o recorte

Uma apresentação compartilhada dos detalhes deve atender contexto, duas visões
do agregado e histórico. S2 entrega a apresentação compartilhada inicial na
listagem/histórico contextuais; S3 a reutiliza no agregado, sem refazer a mesma
regra em renderização paralela. Mostrar apenas informações pertinentes, com ausência
explícita quando aplicável; não renderizar Não para campo não aplicável.
Agendada é um detalhe visual, nunca novo status.

Adicionar categoria a parsing, opções e aplicação dos filtros em `queries.py`,
antes de agrupamento/paginação. Categoria e tipo são interseção: combinação
incompatível não ignora filtros nem amplia resultados. Painel mostra orientação;
XLSX correspondente contém somente cabeçalhos.

Manter todos os filtros existentes, indicadores hospitalares independentes
dos filtros, primeira unidade por episódio e exclusão conservadora de casos
ambíguos. Não adicionar novos gráficos, alertas ou indicadores clínicos.

### D7 — XLSX retangular, datas nativas e texto seguro

Manter `views_export.py` usando a mesma seleção de `queries.py`, sem paginação
e sem depender da visualização. O contrato exato de 23 colunas está em PP-08;
as duas primeiras identificam pendência e episódio, seguidas de contexto,
classificação, detalhes e autoria. Não usar uma coluna por procedimento,
concatenação de pendências ou abas por categoria.

Evoluir o serializador puro de `export.py` para aceitar tipos de célula:

- Textos sempre como strings literais, inclusive nomes e observações iniciados
  por `=`, `+`, `-` ou `@`; nunca inferir fórmulas a partir de conteúdo.
- Datas como valores date e formato `dd/mm/yyyy`.
- Instantes de assinatura/criação/atualização convertidos ao fuso institucional
  e serializados sem timezone, com formato `dd/mm/yyyy hh:mm`.
- Agendada, Contraste e Sedação como Sim/Não; desconhecido aplicável como Não
  informado; não aplicável vazio. Data desconhecida permanece célula vazia.
- Registro do paciente permanece texto, preservando zeros à esquerda.
- IDs são identificadores, não fórmulas; sem expor novas informações clínicas.

Usar autofiltro no intervalo completo e congelamento da primeira linha.
Larguras devem ser limitadas para observações longas, com quebra de texto,
sem transformar uma nota extensa em coluna impraticável. Arquivo em memória,
sem persistência de informações sensíveis e com proteção de cache existente.

A alteração de posição/tipo de células é uma quebra explícita documentada na
proposal; atualizar testes que hoje assumem 13 colunas e todas as células
textuais. A proteção contra fórmula permanece exigida em todos os textos.

### D8 — Migrations não destrutivas e carga determinística

Separar alteração de estrutura e carga de dados quando facilitar testes.
Em S1, adicionar categoria inicialmente anulável e metadados de classificação,
carregar/validar o catálogo e só então tornar categoria obrigatória nos tipos.
S2 adiciona os campos de D2. Preservar PKs, FKs, estados, autoria e revisões;
não reconstruir campos a partir de observações.

#### Carga inicial versus reaplicação

A inicialização única parte do estado histórico anterior a S1 (migration 0002)
e aplica a matriz abaixo. A reaplicação parte de catálogo já inicializado.
Esses são contextos explícitos da operação de carga/teste, não heurística
baseada no nome atual. A migration inicial é a única entrada autorizada para
inicializar campos de tipos preexistentes por correspondência exata. Reaplicar
não pode voltar a esse modo nem reinterpretar uma renomeação como colisão
inicial. Não é necessária tabela de proveniência, flag de ativação ou nova CLI.

Na carga inicial, slug+nome exatamente iguais ao catálogo são a correspondência
explícita aprovada; nome isolado, sem o slug, não prova identidade. Comparações
são exatas, sem aproximação, aliases, acentuação ignorada ou parsing de texto.

| Contexto e caso                                                                                            | Resultado obrigatório                                                                                                                                 |
| ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Inicial: slug canônico ausente e sem colisão de nome na categoria final                                    | Criar a entrada canônica com os metadados do catálogo                                                                                                 |
| Inicial: tipo preexistente com slug e nome canônicos exatos, incluindo Outro                               | Adotar a mesma PK e inicializar uma única vez categoria/perfil/capacidade RNM/observação obrigatória conforme catálogo, sem alterar itens ou revisões |
| Inicial: slug reservado encontrado com nome divergente                                                     | Abortar atomicamente, sem renomear, fundir ou assumir significado                                                                                     |
| Inicial: nome igual ao canônico, mas slug diferente                                                        | Preservar o tipo preexistente como distinto em Outras pendências/Registro simples e criar o canônico; nunca substituir sua PK ou suas referências     |
| Inicial: a preservação acima colide em nome dentro da mesma categoria final                                | Abortar atomicamente e pedir decisão explícita; não contornar a unicidade com renomeação automática                                                   |
| Inicial: tipo sem slug reservado e sem correspondência canônica                                            | Preservar PK/nome/slug em Outras pendências/Registro simples, sem RNM; observação opcional no estado final, salvo Outro                               |
| Reaplicação: slug existente, com nome visível renomeado ou contrato customizado legitimamente antes do uso | Preservar PK, nome, categoria, perfil, capacidade RNM e regra de observação; não restaurar defaults nem comparar o nome atual com o nome inicial      |
| Reaplicação: slug canônico ausente                                                                         | Recriar a entrada com defaults somente se não houver colisão de nome na categoria de destino; caso contrário, abortar atomicamente                    |

Categorias não existiam antes de S1. Na instalação/carga inicial são criadas
com os slugs/nomes do catálogo; se o estado inicial fornecido contiver categoria
com slug reservado e nome divergente, abortar. Slug e nome coincidentes permitem
reutilizar a categoria sem trocar sua PK. Nome igual com outro slug aborta por
unicidade de nome, sem adoção ou renomeação. Em reaplicação, a categoria é
reconhecida pelo slug e seu nome visível é preservado; se o slug estiver ausente,
criar a categoria canônica apenas se seu nome não colidir. Colisões de qualquer
constraint aplicável abortam toda a carga, sem escrita parcial.

A adoção inicial é uma inicialização de schema autorizada, inclusive quando
o tipo legado já é referenciado: não é uma permissão posterior de alterar o
contrato usado. Registros/revisões mantêm seu conteúdo; revisões anteriores
continuam sem classificação histórica presumida. A imutabilidade de D1 passa
a proteger os novos contratos para todas as manutenções seguintes.

No estado pós-S1, nem reaplicação nem admin podem alterar o contrato fixo de
Outro. Se a reaplicação encontrar esse contrato inconsistente, abortar sem
corrigir silenciosamente. Para os demais tipos, customização legítima significa
que passou pelas guardas de D1; a reaplicação não é caminho de bypass.

Testar todas as linhas da matriz com fixtures sintéticas e também banco novo,
reaplicação após renomear nome visível, contratos usados só em revisão e rollback
de colisão. Diagnóstico contém apenas identificadores de catálogo, nunca dados
de pacientes. Não acessar produção para elaborar fixtures.

Não haverá script de limpeza nesta change. A observação do usuário de que há
poucos testes em produção não é autorização de exclusão. Preservação aditiva
é mais simples do que inventar uma rotina destrutiva especial.

### D9 — Entregas e verificação

Quatro slices verticais, sequenciais e sujeitos à revisão humana dos contratos:

1. Catálogo categorizado utilizável no admin e identificável nos seletores
   atuais, com migrations conservadoras e snapshots da classificação.
2. Cadastro e gestão contextual dos quatro perfis, incluindo todos os
   formulários de edição para não deixar o modal antigo apagar dados novos.
3. Acompanhamento no agregado, resumos/histórico e filtro por categoria.
4. XLSX estruturado e evidência integrada final.

A revisão da decomposição separou a manutenção administrativa do catálogo,
que tem superfície e evidência próprias, do cadastro estruturado pela equipe.
Não há slice apenas de banco ou backend: S1 entrega o fluxo administrativo;
S2 entrega o ciclo cadastro/edição/finalização com os campos reais.

Ao final de S1, os formulários de pendência ainda seguem o preenchimento
anterior, com observações obrigatórias e nomes contextualizados por categoria;
os detalhes por perfil e a flexibilização de observações chegam juntos em
S2. Não se adicionam flags de ativação nem campos de item antecipados. Esse
estado intermediário não representa a feature final pronta para deploy.
S3 reutiliza a escrita completa de S2; não a reimplementa.

Reutilizar seams unitários e de integração existentes. Para cada comportamento
novo, exigir RED antes da implementação e GREEN depois. Verificação de produto
usa a suíte Playwright atual com live_server e dataset sintético, desktop e
mobile, sem acessar portal ou pacientes de produção. Download real deve ser
aberto com openpyxl para conferir valores, tipagem e ausência de fórmulas.

Gates oficiais e relatórios seguem `AGENTS.md`; integração é obrigatória,
separadamente do quality-gate. Browser sem assets/Chromium não constitui
aceite: é bloqueio de infraestrutura. Verificação do portal implantado é
opcional e exige a autorização própria de `docs/dev-verification.md`.

## Risks / Trade-offs

- Ausência confundida com Não -> booleanos anuláveis, apresentação por
  aplicabilidade e testes de ida/volta até o XLSX.
- Troca de tipo apaga detalhes -> confirmação explícita, validação no serviço
  e snapshot anterior preservado.
- Catálogo muda o contrato de registros -> slugs imutáveis; categoria, perfil
  e capacidades protegidos para referências atuais ou históricas; contrato de
  Outro sempre fixo; inicialização/reaplicação delimitadas pela matriz D8.
- Campos anuláveis sem uso em alguns tipos -> escolha deliberada para poucos
  perfis fixos; aplicar as constraints locais enumeradas em D3 e validar no
  domínio o que depender de relações.
- Planilha quebra leitores posicionais -> contrato exato documentado,
  identificação das colunas e atualização de testes; comunicar no deploy.
- Registros de teste em produção -> preservar por padrão e manter qualquer
  descarte fora da change.
- Módulo administrativo ainda contém dado sensível -> manter autorização,
  cache, logs mínimos e testes somente sintéticos.

## Migration Plan

1. Após aprovação e implementação revisada, executar migrations em banco
   sintético novo e atualizado; conferir catálogo, identidades e revisões.
2. Executar quality-gate, integração e jornadas de produto no estado final.
3. Em deploy autorizado, realizar backup conforme operação existente e aplicar
   migrations antes de servir o código novo. Comunicar mudança do XLSX.
4. Conferência em produção é de leitura, autorização e renderização. Escritas
   serão observadas no primeiro uso assistido, sem criar pacientes ou notas de
   teste em produção e sem presumir evidência não obtida.
5. Em falha, interromper uso da feature e corrigir para frente. Não reverter
   migrations removendo colunas/revisões depois de haver escritas novas; código
   anterior não é rollback seguro após observações opcionais e dados novos.
   Eventual restauração exige decisão operacional explícita e avaliação do
   backup e das escritas posteriores, nunca descarte automático.

## Aprovação e detalhamentos

Decisões de produto consolidadas na conversa estão refletidas no catálogo e
nas specs. Nomes técnicos, ordem de colunas, filtro por categoria, detalhes da
carga e validações de coerência são propostas concretas para revisão humana.
Nenhum slice está autorizado para execução apenas por existir neste diretório.
