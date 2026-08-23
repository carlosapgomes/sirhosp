# ADR-0006 — Ocupação v4 acionável: conflitos tipados, elegibilidade com ressalvas e lista única em `/beds`

## Status

Accepted

## Contexto

A ativação de `occupancy-v3` mostrou que o censo pode ser completo para a
extração e, ainda assim, conter conflitos ou linhas ocupadas sem identidade de
posição. Em 23/08/2026, cinco medições aceitas pelo gate de cobertura foram
materializadas corretamente, mas todas ficaram fora das estatísticas diárias
porque a política v3 (ADR-0005) torna qualquer conflito físico bloqueante.

Essa tolerância zero é inadequada para o objetivo operacional: o sistema de
origem sempre terá algum ruído, e a página deve tornar os problemas visíveis
para orientar melhoria progressiva, não eliminar dias inteiros de estatística.
Além disso, `/beds` usava nomes limpos na realidade oficial e nomes técnicos
com prefixos físicos na fotografia de origem, empregava a expressão pouco
familiar "sistema legado" e obrigava o usuário a localizar o mesmo setor em
duas listas longas.

Esta ADR registra as decisões de tratamento de conflito, elegibilidade v4,
nomenclatura e composição visual, e substitui parcialmente as decisões
afetadas da ADR-0005. V1, v2, v3, a ADR-0005 e todos os valores persistidos
continuam imutáveis e históricos.

## Decisão

- **Tolerância zero substituída apenas em v4**: toda medição v4 materializada
  de um censo aceito (gate primário de 40 setores inalterado) é elegível para
  o resumo diário. Conflitos e omissões tornam a medição `com ressalvas de
  qualidade`, mas não a retiram das médias; os rótulos deixam claro que as
  médias usam as ocupações consideradas. V1, v2 e v3 preservam integralmente
  suas regras históricas de elegibilidade, sem backfill.
- **Conflitos tipados pelo impacto real**: após colapsar duplicatas exatas, a
  chave física `(identidade de origem normalizada, leito normalizado)` é
  classificada por precedência:
  - `occupant_conflict`: alternativas ocupadas com o mesmo seletor etário
    divergem em prontuário/nome; conta uma posição ocupada sem paciente
    vencedor;
  - `status_conflict`: estados divergentes; a posição não entra no numerador
    nem recebe estado vencedor;
  - `age_conflict`: seletor etário divergente em código particionado; a
    posição não é atribuída a grupo etário;
  - `unidentified`: linha ocupada sem leito utilizável; não forma posição e
    não entra no numerador.
- **Elegibilidade com warning**: `OccupancyMeasurement.quality_warning` e o
  contador diário `quality_warning_measurement_count` registram ressalvas sem
  reutilizar os contadores históricos de exclusão v2/v3. Idempotência: a
  reexecução não duplica o contador.
- **Reconciliação schema 2 fechada e privada**: duas pontes (linhas ocupadas
  brutas e posições ocupadas contadas) fecham por construção com agregados
  allowlisted; nenhuma chave física, leito, nome, prontuário, idade exata ou
  assinatura é persistida.
- **Aliases limpos são dado temporal de catálogo**: cada membership v4
  declara `source_display_name` (rótulo humano) distinto de
  `configured_source_name` (nome bruto para auditoria de drift). Catálogos
  antigos sem alias usam o nome configurado como fallback documentado, sem
  consulta ao catálogo atual e sem regex em runtime.
- **"Sistema de origem"**: a interface passa a chamar a fotografia física de
  `sistema de origem`; o nome bruto aparece somente como proveniência
  secundária (`Nome no sistema de origem`); termos técnicos históricos em
  specs e ADRs anteriores não são reescritos.
- **Dois resumos e uma lista única**: `/beds` mantém os resumos agregados
  `Capacidade oficial e ocupação` e `Posições registradas no sistema de
  origem` simultâneos e sem abas, e substitui as duas listas longas por uma
  única seção `Setores e posições`. Cada unidade expansível é um componente
  conexo do grafo bipartido entre grupos oficiais e códigos-fonte do catálogo
  exato, cobrindo genericamente 1:1, vários códigos por grupo, 3A particionada
  e CO com vários códigos, sem hardcode por código ou stable key. Cada posição
  física aparece uma vez; fontes compartilhadas não duplicam capacidade.
- **Detalhe autenticado e não autoritativo**: todo usuário autenticado de
  `/beds` pode expandir alternativas únicas de conflitos e linhas ocupadas sem
  posição, rotuladas `registro divergente — não autoritativo`, sem escolher
  primeiro/último/preferido. O detalhe existe somente em memória de
  renderização do censo exato; não é persistido, logado nem incluído em
  relatórios. Anônimos continuam redirecionados e `login_required` permanece.
- **Tratamento explícito por categoria**: duplicatas viram `Linhas duplicadas
  consolidadas` com "posição contada uma vez"; ocupado sem leito é `não
  computadas por ausência de posição`; `unrated` é posição válida fora do
  escopo da taxa oficial; `unmapped` e `linked_pending` permanecem separados.
  A ponte agrega somente contagens, sem PHI.
- **Ativação futura e correção forward**: v4 inicia somente por catálogo
  integral futuro publicado explicitamente; release, migrations e deploy não
  ativam o algoritmo. Divergências são corrigidas em versões futuras, nunca
  reescrevendo medições, catálogos, ADRs ou relatórios anteriores.
- **Substituição parcial da ADR-0005**: esta ADR substitui somente as
  decisões de ADR-0005 sobre tratamento de conflito (tolerância zero),
  elegibilidade diária, nomenclatura ("legado" → "sistema de origem") e
  composição visual (duas listas → uma lista única). As decisões de
  identidade física por origem e leito, deduplicação exata, disponibilidade
  por saldo setorial, preservação bruta e privacidade continuam vigentes.

## Alternativas Consideradas

1. **Manter qualquer conflito como inelegibilidade**
   - Vantagens: continuidade com a ADR-0005.
   - Desvantagens: produção demonstrou que isso elimina todas as observações
     do dia mesmo com cobertura suficiente.
   - Motivo da rejeição: o objetivo é observar e reduzir imperfeições do
     sistema de origem, não descartar dias inteiros.

2. **Contar todo conflito ocupado como uma ocupação**
   - Vantagens: numerador simples.
   - Desvantagens: uma posição simultaneamente ocupada e vaga não tem estado
     físico confiável.
   - Motivo da rejeição: somente a divergência exclusiva de ocupante é
     inequívoca quanto à ocupação.

3. **Manter duas listas longas com nomes limpos**
   - Vantagens: mudança mínima de layout.
   - Desvantagens: o usuário precisaria reencontrar o setor em duas listas.
   - Motivo da rejeição: a lista única por componente conexo resolve o
     reencontro sem esconder nenhuma das realidades.

4. **Escolher primeiro/último candidato de conflito**
   - Vantagens: detalhe mais curto.
   - Desvantagens: criaria autoridade implícita sobre paciente/status/idade.
   - Motivo da rejeição: a decisão exige alternativas visíveis e não
     autoritativas para todos os autenticados.

## Consequências

### Positivas

- Censos v4 aceitos contribuem às estatísticas diárias com ressalvas
  auditáveis e rótulos honestos ("ocupações consideradas").
- Cada tratamento (consolidado, computado com ressalva, não computado, fora
  da taxa) é explicado por categoria persistida, sem PHI no agregado.
- A lista única elimina duplicação visual e usa aliases limpos versionados,
  mantendo o nome bruto como proveniência.
- Conflitos e linhas sem posição tornam-se acionáveis para todos os
  autenticados, sem alterar autorização nem persistir detalhe.
- V1–v3, ADR-0005 e artefatos históricos permanecem imutáveis.

### Negativas / Trade-offs

- Médias diárias v4 usam numerador com omissões conhecidas; a ponte e o
  contador de ressalvas são o contrapeso explícito.
- Mais vocabulário de qualidade na página; cada categoria precisa de
  explicação estável.
- Ativação de v4 continua exigindo catálogo integral futuro e validação em
  dry-run antes da publicação.

## Referências

- ADR-0005 — duas realidades em `/beds` (substituída parcialmente nas
  decisões de conflito, elegibilidade, nomenclatura e composição visual;
  identidade física, deduplicação, disponibilidade e privacidade preservadas).
- ADR-0003 e ADR-0004 — catálogo temporal imutável e política CO/3A
  preservados.
- Change OpenSpec `make-occupancy-quality-actionable` (proposal, design, specs
  delta, tasks e relatórios dos slices S1–S3).
- Implementação: `apps/census/occupancy.py`, `apps/census/views.py`,
  `apps/census/capacity_catalog.py`, `apps/census/models.py`,
  `apps/census/templates/census/bed_status.html` e catálogo v4.
