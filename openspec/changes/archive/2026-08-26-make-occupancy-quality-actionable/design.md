# Design: Qualidade de ocupação acionável

## Context

`occupancy-v3` separou capacidade oficial da fotografia física, deduplicou
posições exatas e preservou conflitos. A primeira operação real em 23/08/2026
mostrou cinco medições aceitas pelo gate de cobertura, todas fisicamente
parciais e, portanto, inelegíveis para médias. O primeiro censo tinha cobertura
46/40 e reconciliação fechada, mas 14 posições conflitantes e 12 linhas ocupadas
sem leito bastaram para remover o dia inteiro das estatísticas.

O comportamento é fiel à ADR-0005, mas a premissa de tolerância zero não serve
a um sistema cujo objetivo é observar e reduzir imperfeições do sistema de
origem. Também se verificou que o conflito atual mistura divergência de
ocupante, status e faixa etária, embora elas tenham efeitos distintos sobre a
contagem física.

Na interface, os grupos oficiais usam `display_name` limpo, enquanto setores de
origem exibem nomes como `0 T` ou `2 6 - 2A`. A página contém dois resumos e duas
listas longas. O usuário precisa reencontrar o setor para consultar posições.

## Goals / Non-goals

**Goals:**

- Fazer censos v4 aceitos contribuírem às estatísticas com ressalvas.
- Tipar conflitos pelo impacto real e contar ocupação quando ela é inequívoca.
- Explicar cada tratamento sem usar “exclusão” como categoria genérica.
- Persistir aliases limpos por código-fonte em catálogo temporal.
- Manter dois resumos semânticos e uma única lista detalhada.
- Tornar conflitos e linhas sem posição acionáveis a todos os autenticados.
- Preservar histórico, privacidade agregada, exact-run e fluxo clínico.

**Non-goals:**

- Mudar o gate de 40 setores ou sua automação Playwright.
- Corrigir dados na origem ou editar snapshots.
- Reprocessar v1–v3 ou estatísticas anteriores.
- Criar escolha autoritativa de paciente/status.
- Alterar capacidade, CO ou partição 3A.
- Criar novo perfil de autorização ou infraestrutura.

## Decisions

### 1. V4 separa aceitação, elegibilidade e qualidade

O gate existente continua primário:

```text
extração com menos de 40 setores distintos -> rejeitada antes do snapshot
extração com 40 ou mais -> aceita -> medição pode ser materializada
```

Uma medição v4 só existe para um censo aceito e, se criada com sucesso, entra no
resumo diário. Conflitos e omissões tornam a medição `com ressalvas`, mas não a
retiram da média. Falha estrutural de catálogo ou reconciliação aborta a
transação e não produz medição.

V2 e v3 preservam integralmente suas regras históricas de elegibilidade. Em
especial, uma medição v3 fisicamente parcial continua excluída. Não haverá
backfill.

**Alternativa rejeitada:** manter qualquer conflito como inelegibilidade. A
produção demonstrou que isso elimina todas as observações do dia mesmo com
cobertura suficiente.

### 2. Conflitos são classificados depois de colapsar duplicatas exatas

A chave física permanece `(identidade de origem normalizada, leito
normalizado)`. Prontuário nunca é chave da posição. Para cada chave:

1. colapsar assinaturas exatamente iguais e contar linhas extras duplicadas;
2. analisar as assinaturas únicas restantes;
3. classificar pelo impacto mais forte.

Categorias v4:

- `unambiguous`: uma assinatura única após deduplicação;
- `occupant_conflict`: todas as alternativas estão ocupadas e usam o mesmo
  seletor etário efetivo, mas divergem em prontuário ou nome; conta uma posição
  ocupada, sem paciente vencedor;
- `age_conflict`: alternativas ocupadas de código particionado divergem entre
  `under_12`, `age_12_or_over` ou classificação desconhecida; a posição física
  é ocupada, mas não entra em grupo oficial etário;
- `status_conflict`: a mesma posição possui estados divergentes; não entra no
  numerador nem recebe estado vencedor;
- `unidentified`: linha sem leito utilizável; não forma posição e, quando
  ocupada, não entra no numerador.

Divergência de faixa em código não particionado é advertência de metadado, não
motivo para omitir uma ocupação física inequívoca. Divergência entre estados
não ocupados continua `status_conflict`, mas não altera numerador oficial.

**Alternativa rejeitada:** contar todo conflito ocupado uma vez. Uma posição
simultaneamente ocupada e vaga não tem estado físico confiável.

### 3. Reconciliação v4 usa schema 2 e duas pontes fechadas

O JSON v4 permanece allowlisted e recebe somente inteiros/agregados. A primeira
ponte explica linhas ocupadas brutas:

```text
raw_occupied_rows =
    duplicate_occupied_extra_rows
  + occupant_conflict_extra_occupied_rows
  + status_conflict_occupied_rows
  + age_conflict_occupied_rows
  + unidentified_occupied_rows
  + unknown_age_partition_positions
  + counted_occupied_positions
```

A segunda explica posições ocupadas contadas:

```text
counted_occupied_positions =
    official_numerator
  + occupied_unrated_positions
  + occupied_unmapped_positions
  + occupied_linked_pending_positions
```

Uma posição `occupant_conflict` contribui uma vez à segunda ponte; suas
alternativas adicionais entram em `occupant_conflict_extra_occupied_rows`.
Status e idade conflitantes permanecem fora de `counted_occupied_positions`.

O schema também preserva posições por status, conflitos por tipo, duplicatas,
linhas sem identidade e indicador agregado de ressalva. Nenhuma chave física,
leito, nome, prontuário, idade exata ou assinatura é persistida.

### 4. Fora da taxa é política, não sinônimo de erro

V4 deixa de agregar tudo em `unambiguous_occupied_outside_calculable` e separa:

- `occupied_unrated_positions`: fora da taxa por política publicada;
- `occupied_unmapped_positions`: gap de catálogo;
- `occupied_linked_pending_positions`: capacidade conhecida com cálculo
  pendente.

A UI usa, respectivamente, “fora do escopo da taxa”, “sem mapeamento no
catálogo” e “cálculo pendente”.

### 5. Qualidade v4 é explícita no modelo e no resumo

`OccupancyMeasurement` recebe um estado/flag v4 de qualidade com ressalvas,
nulo para algoritmos históricos. `DailyOccupancySummary` recebe contador de
medições v4 com ressalvas.

No resumo diário:

- v1 preserva elegibilidade histórica;
- v2/v3 preservam exclusões históricas já especificadas;
- toda medição v4 materializada é elegível;
- `quality_warning_measurement_count` conta v4 com conflito, linha ocupada sem
  posição, idade desconhecida/ambígua ou posição ocupada não mapeada;
- médias continuam equal-weight e usam o numerador considerado persistido;
- rótulos deixam claro que são médias das ocupações consideradas.

Contadores históricos `age_excluded_measurement_count` e
`position_excluded_measurement_count` não são reutilizados como advertência v4.

### 6. Alias limpo é dado temporal de catálogo

Cada membership de um catálogo novo recebe `source_display_name`, diferente de
`configured_source_name`:

- `configured_source_name`: nome bruto esperado para auditoria de drift;
- `source_display_name`: rótulo humano limpo usado na UI.

O alias é obrigatório, não vazio, limitado e consistente quando o mesmo código
aparece em duas memberships etárias. Catálogos antigos preservam fallback sem
ser editados. Não remover prefixos por regex em runtime.

O catálogo integral v4 mantém 43 grupos, 48 memberships, 47 códigos, quatro
`unrated` e capacidades 666/666. O JSON declara `occupancy-v4` e usa nova versão
de schema. Dry-run reporta algoritmo, totais e cobertura de aliases sem escrever.

### 7. A lista única deriva componentes do grafo catálogo↔origem

A página mantém no topo:

1. `Capacidade oficial e ocupação`;
2. `Posições registradas no sistema de origem`.

As duas listas detalhadas são substituídas por `Setores e posições`. Cada item
expansível representa um componente conexo do grafo bipartido entre grupos
oficiais e códigos-fonte do catálogo exact-run.

Isso resolve genericamente:

- 1 grupo ↔ 1 código;
- Cardio: 1 grupo ↔ 2 códigos;
- 3A: 2 grupos ↔ 1 código;
- CO: 1 grupo ↔ 5 códigos.

Título determinístico:

- um grupo no componente: `display_name` oficial;
- vários grupos e um alias-fonte: o alias-fonte;
- demais casos: composição ordenada dos nomes oficiais, sem hardcode por código.

Cada expansão contém:

- mini-tabela oficial com valores persistidos por grupo;
- mini-resumo físico por código-fonte com alias limpo;
- nome bruto somente como proveniência secundária;
- posições normalizadas uma única vez;
- casos de conflito e linhas sem leito.

Setores unmapped formam unidades de alerta próprias e não recebem nome oficial.

### 8. Detalhe de qualidade é autenticado e não autoritativo

Todo usuário já autenticado em `/beds` pode expandir:

- uma posição em conflito;
- alternativas únicas envolvidas, com quantidade de linhas equivalentes;
- motivo: ocupante, status ou faixa etária;
- linha ocupada sem identidade de posição.

Como a página já autoriza nomes, prontuários e links de pacientes, os detalhes
podem manter essa informação em memória e no HTML autenticado. Regras:

- não escolher nem destacar alternativa como verdadeira;
- marcar cada alternativa como “registro divergente — não autoritativo”;
- não persistir detalhe em measurement, summary ou logs;
- não incluir PHI em alertas agregados, relatórios ou consultas operacionais;
- manter `login_required` e o redirecionamento anônimo.

### 9. Terminologia explica tratamento

Substituições obrigatórias:

- “sistema legado” → “sistema de origem”;
- “duplicatas ocupadas excluídas” → “linhas duplicadas consolidadas”, com
  explicação de que a posição conta uma vez;
- conflito → mostrar posições conflitantes, linhas envolvidas e se a ocupação
  foi computada ou não;
- sem identidade → “não computadas por ausência de posição”;
- `unrated` → “posição válida fora do escopo da taxa oficial”.

O título da ponte passa a `Como as ocupações foram tratadas`.

### 10. Histórico e ativação permanecem isolados

V4 só inicia por novo catálogo futuro. Release, migrations e deploy não ativam
algoritmo. A publicação ocorre depois do deploy, para meia-noite futura de
`America/Bahia`. V1–v3, catálogos, medições e resumos existentes permanecem
imutáveis.

Após vigência v4, rollback funcional para versão sem suporte não é permitido;
preferir correção forward.

## Data model

Mudanças aditivas esperadas:

- `OccupancyMeasurement`: flag/estado nullable de qualidade v4;
- `DailyOccupancySummary`: contador não negativo de medições v4 com ressalvas;
- `CapacitySectorMembership`: `source_display_name` nullable para legado e
  obrigatório em novas publicações;
- reconciliação v4: JSON schema 2, sem migration de estrutura;
- migrations separadas por slice, sem `RunPython` e sem backfill.

## Privacy and security

- Snapshots brutos e detalhes permanecem no banco atual.
- Histórico agregado contém somente allowlist de inteiros.
- Detalhes conflitantes existem apenas durante renderização exact-run.
- Todos os usuários autenticados mantêm a autorização nominal já existente.
- Anônimos continuam redirecionados.
- Nenhum relatório de slice ou produção contém dados reais.

## Slice strategy

Três slices equilibram verticalidade e escopo:

1. **MOQA-S1:** algoritmo v4 completo até resumo diário, quatro arquivos.
2. **MOQA-S2:** catálogo/alias integral e dry-run, cinco arquivos.
3. **MOQA-S3:** experiência `/beds` e ADR, até seis arquivos.

Dividir tipagem e resumo criaria fatias horizontais sem valor observável.
Misturar catálogo e UI aumentaria o primeiro slice para mais de nove arquivos.
Uma quarta fatia somente de documentação seria horizontal; ADR acompanha a UI.

## Risks / trade-offs

- **Média usa numerador com omissões conhecidas:** rótulo “ocupações
  consideradas”, contador de ressalvas e ponte explícita evitam falsa precisão.
- **Classificação errada de conflito:** função pura, precedência explícita,
  fixtures sintéticas combinatórias e reconciliação fechada.
- **Detalhe PHI em conflito:** somente HTML autenticado exact-run; história,
  logs e relatórios continuam agregados.
- **Alias diverge da origem:** nome bruto preservado e mismatch visível; mudança
  de alias exige novo catálogo futuro.
- **Lista única duplica posição em relações N:M:** componentes conexos e testes
  específicos para 3A, Cardio e CO.
- **DeepSeek antecipa slices:** limites rígidos de arquivos, prompts completos,
  inspeções e condições automáticas de INCOMPLETO.

## Deployment and activation

1. Implementar S1–S3 por TDD e commits separados.
2. Auditar artefatos, ADR, migrations e relatórios.
3. Sincronizar/arquivar o change v3 se ainda estiver ativo.
4. Executar quality gate e integração.
5. Publicar release e imagem imutáveis.
6. Fazer backup e deploy sem ativação.
7. Confirmar v3 vigente e executar dry-run v4 futuro.
8. Publicar catálogo v4 explicitamente para data futura.
9. Validar primeiro censo v4 com agregados seguros.
10. Sincronizar specs e arquivar este change.

## Operational closure

O primeiro censo completo v4 foi validado posteriormente somente por agregados:
a medição técnica 81, de 24/08/2026, pertenceu a run concluído, usou catálogo
v4 exato, manteve-se elegível com ressalvas e fechou as duas pontes do schema 2:
651 linhas ocupadas e 598 posições contadas, das quais 574 formaram o numerador
oficial. O resumo diário, aliases, exact-run, autenticação e fluxo clínico
permaneceram operacionais.

A observação também confirmou um defeito histórico no classificador v4: uma
linha operacional não ocupada isolada podia ser classificada como conflito de
status pela comparação entre assinaturas e grupos ocupados. O defeito não é
ocultado por este encerramento e nenhuma medição v4 é corrigida, recalculada ou
reinterpretada. `occupancy-v5`, vigente a partir de 26/08/2026, substitui essa
semântica de forma forward ao contar pacientes identificados e apresentar
estados operacionais factualmente. V1–v4 permanecem imutáveis.

## Open questions

Nenhuma. Foram aprovados “sistema de origem”, detalhes para todos os usuários
autenticados e lista única com resumos agregados separados.
