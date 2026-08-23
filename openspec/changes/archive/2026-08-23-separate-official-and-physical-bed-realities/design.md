## Context

`/beds` combina hoje uma `OccupancyMeasurement` imutável, calculada sobre os
grupos oficiais, com totais obtidos diretamente de todas as linhas do último
`CensusSnapshot`. O censo de 21/08/2026 às 06:36 demonstrou a diferença:
636 ocupações calculáveis sobre capacidade 666 e 667 linhas brutas ocupadas em
847 linhas totais. As 31 linhas ocupadas restantes pertenciam a grupos sem
taxa, mas os dois números receberam rótulos equivalentes.

A mesma captura continha 31 linhas ocupadas na 3A Infantil, das quais sete eram
duplicatas exatas do mesmo leito, nome e prontuário. O código v2 conta cada
linha por decisão anterior de não deduplicar prontuários. Essa decisão continua
válida para prontuários compartilhados por leitos distintos, porém não define a
identidade física do mesmo leito repetido.

O catálogo oficial informa capacidade por grupo, não a identidade nominal dos
leitos que compõem essa capacidade. Portanto, `capacidade oficial disponível`
é um saldo setorial calculado; `vago no legado` é um estado físico observado.
Os conceitos não podem compartilhar rótulo ou ser compensados implicitamente.

Stakeholders incluem direção, gestão de leitos, qualidade, operação clínica e
usuários autenticados de `/beds`. A mudança deve preservar privacidade,
história imutável, fluxo clínico e operação simples em Django/PostgreSQL.

## Goals / Non-Goals

**Goals:**

- Definir uma identidade física determinística e transversal a todos os setores.
- Introduzir v3 sem reinterpretar v1/v2.
- Preservar bruto, colapsar duplicata exata e explicitar conflito.
- Persistir evidência agregada suficiente para reconciliar o numerador oficial.
- Calcular disponibilidade oficial sem compensação entre setores.
- Separar as duas realidades em blocos e tabelas visualmente distintos.
- Manter alertas e histórico agregado sem identificadores de paciente.

**Non-Goals:**

- Limpar o legado, editar snapshots ou fazer backfill.
- Deduplicar pacientes entre leitos ou parear mãe e criança.
- Produzir cadastro nominal de leitos oficiais.
- Alterar capacidades, associação etária da 3A ou política dos grupos unrated.
- Alterar autenticação, permissões ou processamento clínico.
- Introduzir dependência, fila ou serviço operacional novo.

## Decisions

### 1. Três camadas, mas somente duas realidades principais na UI

A implementação distinguirá:

1. **capacidade oficial e ocupação:** catálogo publicado, numerador elegível,
   disponibilidade, excedente e taxa;
2. **posições registradas no legado:** posições físicas inequívocas e seus
   estados observados;
3. **evidência bruta:** linhas preservadas para auditoria, expostas somente como
   contagens de duplicata, conflito e identidade ausente.

A terceira camada é diagnóstico subordinado, não um terceiro painel concorrente.

**Alternativa rejeitada:** apenas renomear os cards atuais. Isso não corrige a
inflação por duplicatas nem permite explicar conflitos.

### 2. Identidade física usa origem e leito, nunca prontuário isolado

A chave da posição será composta pela identidade de origem e pelo leito
normalizados:

- usar código de setor normalizado quando presente;
- usar nome de setor normalizado somente como fallback para código vazio;
- exigir leito não vazio para afirmar uma posição física.

A assinatura observada de uma posição ocupada inclui status, prontuário, nome e
faixa etária normalizados em memória. Para posição não ocupada, o status basta.
Prontuário igual em leitos diferentes continua representando duas posições.

- chave e assinatura iguais repetidas: uma posição e linhas extras duplicadas;
- mesma chave com assinaturas diferentes: uma posição em conflito;
- leito vazio: linha sem identidade física confirmada.

Nenhuma chave, assinatura, nome, prontuário ou leito será copiado para a história
agregada.

**Alternativa rejeitada:** deduplicar somente por prontuário. Isso eliminaria
posições legítimas e reintroduziria inferência mãe-criança proibida.

### 3. V3 consome somente posições inequívocas

`occupancy-v3` usará uma função pura de normalização compartilhada pela
materialização e pela apresentação física:

- duplicatas exatas contribuem uma vez;
- conflitos e linhas sem identidade física não contribuem para numeradores;
- conflito ou identidade ausente ocupada torna a taxa pontual parcial;
- a medição parcial permanece persistida, mas não entra em médias diárias;
- idade desconhecida da 3A mantém a regra parcial já existente;
- grupos unrated e unmapped continuam fora da taxa.

O fluxo clínico continua usando os snapshots brutos e não é bloqueado por
parcialidade de ocupação.

**Alternativa rejeitada:** apagar duplicatas na ingestão. Isso destruiria a
proveniência bruta e poderia alterar outros módulos clínicos.

### 4. Reconciliação será agregada e persistida

A medição v3 armazenará um JSON de esquema allowlisted e versionado contendo
somente inteiros agregados necessários às duas realidades, incluindo:

- linhas ocupadas brutas;
- posições físicas identificadas por status;
- linhas duplicadas extras, inclusive ocupadas;
- posições conflitantes e linhas ocupadas afetadas;
- linhas sem identidade física e linhas ocupadas afetadas;
- ocupações excluídas por idade desconhecida;
- ocupações inequívocas em grupos não calculáveis;
- numerador oficial resultante.

Também persistirá flag de parcialidade física. O JSON não aceita chaves livres
com dados de linha e será coberto por teste de privacidade.

**Alternativa rejeitada:** recalcular a ponte em `views.py`. Isso quebraria o
contrato exact-run e permitiria divergência entre histórico e página.

### 5. Disponibilidade oficial é calculada por setor

Para cada grupo calculável v3:

```text
disponibilidade_i = max(capacidade_i - ocupação_i, 0)
excedente_i = max(ocupação_i - capacidade_i, 0)
```

No hospital:

```text
disponibilidade = soma(disponibilidade_i)
excedente = soma(excedente_i)
taxa = soma(ocupação_i) / soma(capacidade_i)
```

Assim, excedente em um setor não consome disponibilidade de outro. O rótulo
será `Disponibilidade na capacidade oficial`, acompanhado de explicação de que
não identifica nominalmente leitos oficiais vagos.

V1/v2 preservam seus campos históricos; campos novos ficam nulos quando não
fazem parte do algoritmo original.

### 6. A versão do algoritmo passa a integrar o catálogo temporal

`CapacityCatalogVersion` ganhará versão de algoritmo opcional para compatibilidade.
Catálogos existentes sem o campo continuam despachados pela estrutura já
persistida: sem partição para v1 e com partição etária para v2. Toda nova
publicação passará a exigir versão explícita suportada.

Um novo JSON integral, sem editar os artefatos inicial ou corrigido, repetirá a
configuração oficial vigente e declarará `occupancy-v3`. O comando fará dry-run
e publicação atômica para data futura. A seleção em runtime usará o valor
persistido do catálogo v3, nunca data hardcoded.

**Alternativa rejeitada:** ativar v3 por data no código. Isso impediria
reprodutibilidade e tornaria deploy equivalente a ativação funcional.

### 7. Resumo diário preserva motivos de inelegibilidade

Uma medição é elegível somente se não tiver parcialidade etária nem física. O
resumo manterá total, elegíveis, excluídas por idade e excluídas por qualidade
de posição. Os contadores de motivo podem se sobrepor; o total de inelegíveis é
sempre derivado de `measurement_count - eligible_measurement_count`, nunca da
soma dos motivos.

Se nenhuma medição for elegível, médias, mínimos, máximos e excedentes ficam
nulos. Não haverá backfill de resumos v1/v2.

### 8. `/beds` terá duas seções sempre visíveis

A página autenticada exibirá, nesta ordem:

1. seção primária `Capacidade oficial e ocupação` com fonte do catálogo,
   vigência, cards e tabela de grupos oficiais;
2. reconciliação agregada v3;
3. seção secundária `Posições registradas no sistema legado` com captura,
   estados físicos, duplicatas, conflitos, linhas sem identidade e tabela por
   setor-fonte.

A visão oficial mostrará Adulto e Infantil como grupos distintos. A visão física
mostrará o setor-fonte 3A e suas posições uma única vez. CO e demais grupos sem
capacidade aparecem como exclusões na visão oficial e com estados completos na
visão física. O agrupamento auxiliar da 3A deixa de parecer um setor oficial.

V1/v2 recebem rótulo de algoritmo histórico e não são recalculados. Sem medição
exata, a visão oficial permanece pendente e a fotografia física continua
visível. A autenticação e os links nominais autorizados permanecem iguais.

**Alternativa rejeitada:** abas que escondem uma das realidades. As duas fontes
precisam estar simultaneamente visíveis para reduzir confusão.

### 9. ADR substitui somente decisões afetadas

Uma ADR nova registrará identidade física, deduplicação exata, conflito,
disponibilidade setorial e separação visual. Ela não reescreverá catálogo,
capacidades, CO, 3A ou imutabilidade decididos nas ADR-0003 e ADR-0004.

## Data Model

Mudanças aditivas esperadas:

- `CapacityCatalogVersion`: versão explícita opcional do algoritmo;
- `OccupancyMeasurement`: disponibilidade oficial, parcialidade física e JSON
  agregado de reconciliação física;
- `OccupancyGroupMeasurement`: disponibilidade oficial do grupo;
- `DailyOccupancySummary`: contagem de medições excluídas por qualidade de
  posição.

A migration não recalcula medições, catálogos ou resumos existentes. Campos
históricos novos usam nulo ou zero seguro conforme o contrato de compatibilidade.

## Privacy and Security

- Snapshots brutos continuam protegidos pelo banco e pela autenticação atual.
- História agregada não recebe nome, prontuário, leito, idade exata ou texto
  clínico.
- Alertas mostram somente contagens.
- Logs e exceções não imprimem assinaturas ou chaves de posição.
- `/beds` continua protegido por `login_required` e mantém os links existentes.

## Deployment and Activation Plan

1. Implementar os três slices com TDD e gates em container.
2. Auditar ADR, cinco delta specs, migrations e relatórios.
3. Publicar release e imagem imutáveis.
4. Fazer backup e deploy sem publicar catálogo v3.
5. Confirmar migrations, saúde e semântica v2 ainda vigente.
6. Executar dry-run do documento v3 para a primeira data local futura aprovada.
7. Publicar explicitamente o catálogo para meia-noite de `America/Bahia`.
8. Validar o primeiro censo v3 com somente agregados seguros.
9. Preferir correção forward após a vigência; não usar versão antiga para
   materializar censos v3.

## Risks / Trade-offs

- **Normalização incorreta de leito** → normalização conservadora, fixtures
  sintéticas e conflito em vez de escolha arbitrária.
- **Campos identificáveis vazarem no JSON** → allowlist fechada, teste recursivo
  de chaves e valores e inspeção obrigatória.
- **Disponibilidade ser confundida com vaga física** → rótulos distintos,
  tooltip e tabelas separadas.
- **V3 ativar no deploy** → campo temporal no catálogo e publicação futura
  manual separada.
- **Medição parcial reduzir estatística diária** → contadores de motivo e campos
  nulos quando não houver observação elegível.
- **Crescimento de memória ao normalizar censo** → operação linear sobre um
  único run, sem consulta adicional por linha e sem nova infraestrutura.

## Open Questions

Nenhuma. Foram aprovados deduplicação transversal, conflito como parcialidade,
exclusão do numerador pontual e das médias diárias, preservação bruta e ativação
futura sem backfill.
