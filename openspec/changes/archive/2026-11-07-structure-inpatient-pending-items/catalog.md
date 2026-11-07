# Catálogo consolidado de pendências

## Escopo e convenções

Catálogo administrativo proposto para esta change: **10 categorias, 45 tipos
solicitados e o fallback protegido Outro**, totalizando 46 entradas iniciais.
Tipos administrativos preexistentes não são excluídos por essa contagem.

Categoria indica organização do acompanhamento, não atribuição automática de
responsabilidade. Todos os tipos usam os estados Ativa, Resolvida e Encerrada
sem resolução; não geram prioridade ou interpretação clínica.

Os identificadores abaixo são estáveis e globalmente únicos entre tipos.
Slugs de categorias e tipos só podem ser definidos na criação: são imutáveis
mesmo sem uso. Nomes de tipos podem se repetir entre categorias, mas não na
mesma categoria; nomes de categorias são únicos. O identificador existente
`outro` é mantido. Renomear nome visível não altera a identidade da entrada.

## Perfis fixos

| Perfil                  | Campos complementares               | Obrigatoriedade                                                 |
| ----------------------- | ----------------------------------- | --------------------------------------------------------------- |
| Agendamento             | Agendada?; data agendada            | Sim/Não explícito nos novos cadastros; data opcional quando Sim |
| Tratamento com período  | Data de início; previsão de término | Ambas opcionais                                                 |
| Registro simples        | Nenhum além das observações comuns  | Observações conforme regra do tipo                              |
| Assinatura de documento | Data/hora da assinatura             | Opcional                                                        |

Observações são opcionais, exceto para **Regulação > Outros** e **Outras
pendências > Outro**, que exigem texto não vazio. Medicamento, procedimento
específico, especialidade da interconsulta e demais detalhes ficam nas
observações, sem novos cadastros auxiliares nesta change.

RNM usa o perfil Agendamento com dois complementos independentes: **Contraste**
e **Sedação**, cada qual com Não informado, Sim ou Não. Isso vale tanto para
Imagem quanto para CHD. Não há um quinto perfil nem interpretação automática
entre essas opções. CPRM permanece um tipo separado, conforme solicitado.

## Centro Cirúrgico

Categoria: `centro-cirurgico`.

| Identificador    | Tipo          | Perfil      |
| ---------------- | ------------- | ----------- |
| cc-cirurgia      | Cirurgia      | Agendamento |
| cc-procedimentos | Procedimentos | Agendamento |

## Exames de imagem

Categoria: `exames-imagem`.

| Identificador     | Tipo       | Perfil                         |
| ----------------- | ---------- | ------------------------------ |
| imagem-tomografia | Tomografia | Agendamento                    |
| imagem-rnm        | RNM        | Agendamento + complementos RNM |
| imagem-cprm       | CPRM       | Agendamento                    |
| imagem-usg        | USG        | Agendamento                    |
| imagem-eco-tt     | ECO TT     | Agendamento                    |
| imagem-eco-te     | ECO TE     | Agendamento                    |

As quatro entradas originais RNM com/sem contraste e com/sem sedação são
representadas pelo mesmo tipo, permitindo informar as duas dimensões juntas.

## CHD (Centro de Hemorragia Digestiva)

Categoria: `chd`.

| Identificador           | Tipo                   | Perfil                         |
| ----------------------- | ---------------------- | ------------------------------ |
| chd-cpre                | CPRE                   | Agendamento                    |
| chd-ecoeda              | EcoEDA                 | Agendamento                    |
| chd-eda                 | EDA                    | Agendamento                    |
| chd-eda-dilatacao       | EDA + dilatação        | Agendamento                    |
| chd-eda-troca-protese   | EDA + troca de prótese | Agendamento                    |
| chd-gtt                 | GTT                    | Agendamento                    |
| chd-colonoscopia        | Colonoscopia           | Agendamento                    |
| chd-retossigmoidoscopia | Retossigmoidoscopia    | Agendamento                    |
| chd-rnm                 | RNM                    | Agendamento + complementos RNM |

RNM nesta categoria é preservada como solicitada, sem supor erro ou mover
automaticamente para Imagem. A busca sempre distingue as duas categorias.

## Hemodinâmica

Categoria: `hemodinamica`.

| Identificador      | Tipo          | Perfil      |
| ------------------ | ------------- | ----------- |
| hemo-arteriografia | Arteriografia | Agendamento |
| hemo-flebografia   | Flebografia   | Agendamento |
| hemo-cate          | CATE          | Agendamento |
| hemo-embolizacao   | Embolização   | Agendamento |
| hemo-angioplastia  | Angioplastia  | Agendamento |

CATE tem uma única entrada; a duplicidade da lista original foi corrigida.

## Radiointervenção

Categoria: `radiointervencao`.

| Identificador  | Tipo                         | Perfil      |
| -------------- | ---------------------------- | ----------- |
| radio-biopsia  | Biópsia                      | Agendamento |
| radio-drenagem | Drenagem de abscesso/coleção | Agendamento |

## Quadro clínico

Categoria: `quadro-clinico`.

| Identificador          | Tipo            | Perfil           |
| ---------------------- | --------------- | ---------------- |
| quadro-melhora-clinica | Melhora clínica | Registro simples |
| quadro-risco-obito     | Risco de óbito  | Registro simples |
| quadro-quimioterapia   | Quimioterapia   | Registro simples |

Esses nomes não produzem avaliação de risco nem inferência clínica. A ausência
de período em Quimioterapia preserva o escopo informado pela equipe.

## Controle infeccioso

Categoria: `controle-infeccioso`.

| Identificador                   | Tipo                   | Perfil                 |
| ------------------------------- | ---------------------- | ---------------------- |
| infeccioso-antibioticos         | Antibióticos           | Tratamento com período |
| infeccioso-antifungicos         | Antifúngicos           | Tratamento com período |
| infeccioso-cultura-antibiograma | Cultura / Antibiograma | Registro simples       |
| infeccioso-painel-viral         | Painel viral           | Registro simples       |

## Regulação

Categoria: `regulacao`.

| Identificador               | Tipo              | Perfil                                     |
| --------------------------- | ----------------- | ------------------------------------------ |
| regulacao-cirurgia-cardiaca | Cirurgia cardíaca | Registro simples                           |
| regulacao-ortopedia         | Ortopedia         | Registro simples                           |
| regulacao-paliacao          | Paliação          | Registro simples                           |
| regulacao-cronicos          | Crônicos          | Registro simples                           |
| regulacao-contra-referencia | Contra-referência | Registro simples                           |
| regulacao-outros            | Outros            | Registro simples; observações obrigatórias |

## Sumário de alta

Categoria: `sumario-alta`.

| Identificador      | Tipo                          | Perfil                  |
| ------------------ | ----------------------------- | ----------------------- |
| sumario-assinatura | Assinatura do sumário de alta | Assinatura de documento |

A pendência pode ser criada antes de existir assinatura. Preencher a data/hora
não a resolve automaticamente nem constitui assinatura eletrônica no sistema.

## Outras pendências

Categoria: `outras-pendencias`.

| Identificador              | Tipo                              | Perfil                                     |
| -------------------------- | --------------------------------- | ------------------------------------------ |
| outras-definicao-conduta   | Definição de conduta médica       | Registro simples                           |
| outras-relatorio-ad        | Relatório para Atenção Domiciliar | Registro simples                           |
| outras-interconsultas      | Interconsultas                    | Registro simples                           |
| outras-agendamento-externo | Agendamento de exames externos    | Registro simples                           |
| outras-resultado-externo   | Resultado de exames externos      | Registro simples                           |
| outras-aquisicao           | Aquisição de material/medicamento | Registro simples                           |
| outras-hemodialise-acesso  | Hemodiálise para teste de acesso  | Registro simples                           |
| outro                      | Outro                             | Registro simples; observações obrigatórias |

Agendamento de exames externos continua Registro simples: acompanha a obtenção
do agendamento, sem pressupor uma data de exame já conhecida. Não é movido para
outro perfil apenas pela palavra agendamento.

## Manutenção e compatibilidade

- Instalações novas recebem este catálogo, não somente Outro.
- Administrador pode manter categorias e tipos dentro dos perfis fixos.
- Tipo usado é qualquer tipo referenciado por uma pendência ou por uma revisão,
  inclusive somente no histórico e independentemente do estado do item.
- Tipos usados e categorias referenciadas são protegidos contra exclusão.
- Categoria, perfil, habilitação RNM e obrigatoriedade de observações de tipo
  usado não podem mudar. Renomear nome visível continua permitido, salvo Outro.
- Outro tem contrato fixo mesmo sem uso: slug `outro`, nome Outro, categoria
  `outras-pendencias`, Registro simples, sem RNM, observações obrigatórias e
  exclusão proibida. Não é só uma proteção do nome.
- Na carga inicial, somente slug e nome canônicos exatamente iguais permitem
  adotar um tipo preexistente e inicializar seus novos metadados, preservando
  PK e referências. Slug reservado com nome divergente aborta toda a carga.
- Nome coincidente com slug diverso não é identidade: preservar o tipo legado
  em Outras pendências/Registro simples e criar o canônico separadamente. Se
  isso colidir com nome na mesma categoria, abortar sem renomear ou fundir.
- Tipos sem correspondência são preservados em Outras pendências/Registro
  simples, sem RNM e com observações opcionais no estado final, salvo Outro,
  sem interpretar seus textos.
- Após a inicialização, carga repetida identifica por slug e nunca sobrescreve
  nome ou contrato customizado legitimamente antes do uso. Identificador
  ausente é recriado somente sem colisão; inconsistência do contrato fixo de
  Outro aborta, em vez de ser reparada silenciosamente.
- A matriz completa e os contextos distintos de inicialização/reaplicação
  estão em [design D8](design.md#d8--migrations-não-destrutivas-e-carga-determinística).
  A inicialização única não autoriza posterior alteração de contrato usado.
  Não excluir ou fundir tipos/registros para resolver colisões.

## Decisões de detalhamento para revisão

A organização, RNM e perfis foram acordados na discussão. Identificadores,
normalização de grafia e a atribuição explícita dos tipos sem campos pedidos
a Registro simples são detalhamentos desta proposta, sujeitos à revisão antes
da implementação. Não há autorização de descarte de dados de produção.
