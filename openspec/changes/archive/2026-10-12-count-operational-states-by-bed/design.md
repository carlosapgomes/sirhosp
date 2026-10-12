# Design

## Context

A página `/beds/` renderiza, para measurements `occupancy-v5`, um sumário
agregado da "situação real" derivado exclusivamente do JSON de
reconciliação persistido em `OccupancyMeasurement.physical_reconciliation_json`
(schema 3, apenas inteiros agregados via allowlist). Os estados
operacionais desse sumário são hoje contados por **linha** em
`_calculate_v5` (`apps/census/occupancy.py`), enquanto pacientes e pontes
físicas v3/v4 contam entidades deduplicadas. O detalhamento por unidade
(`Setores, pacientes e estados de leitos`) reclassifica as linhas do censo
exato em memória, sem persistir nada — padrão que esta mudança estende.

Ver `proposal.md` para motivação e decisões aprovadas pela operação
(histórico imutável; linhas sem leito fora do badge; aviso de foto não mais
recente).

## Goals / Non-Goals

Goals:

- Uma única regra de contagem por leito compartilhada por materialização,
  card e página de detalhe (impossível divergirem).
- Prova aritmética pública do card: a página de detalhe fecha com os badges
  por construção.
- Zero persistência nova de identidade: nenhuma linha nominal em JSON,
  logs ou banco.

Non-Goals (além dos não-objetivos do proposal):

- Não criar framework genérico de "detalhe de card" para outros agregados.
- Não alterar `DailyOccupancySummary` ou séries históricas (elas não leem
  `operational_rows_by_status`; verificação obrigatória no slice 1).
- Não introduzir HTMX parcial: a página de detalhe é página inteira.

## Decisions

### D1 — Precedência por consenso; divergente não conta

Regra: chave física = (identidade de fonte normalizada, leito normalizado)
— a mesma chave da ponte v3/v4 (`_normalize_positions`).

- Todas as linhas da chave concordam no estado → conta 1 posição nesse
  estado; repetições viram `operational_duplicate_extra_rows`.
- Linhas divergem (dois estados distintos, ou estado + paciente) → não
  conta em nenhum badge; incrementa `operational_conflict_positions`.
- Linha operacional sem leito → fora do badge; incrementa
  `operational_rows_without_bed`.

Alternativas consideradas e rejeitadas:

- Ordem determinística de estados ("reservado vence vazio"): fabrica um
  estado que a fonte não decidiu, quebra a auditabilidade e cria uma
  segunda semântica de conflito no domínio (v3/v4 nunca escolhem vencedor).
- Contar linha e leito simultaneamente (dois números no card): reproduz a
  confusão que motivou a mudança.

Nota de classificação: a reclassificação de nome-marcador em linha ocupada
(`_operational_status`) permanece; o caso "ocupado + marcador no mesmo
leito" é divergência de chave porque uma linha é paciente e a outra é
estado.

### D2 — Classificador compartilhado, com projeção de estado efetivo v5

A contagem por leito opera em duas etapas explícitas:

1. **Projeção de estado efetivo v5** de cada linha do censo, reusando os
   contratos existentes: linha não ocupada → seu `bed_status`; linha
   ocupada cujo nome normalizado contém marcador (`_operational_status`)
   → estado operacional correspondente (variantes diferentes do mesmo
   estado, como `DESOCUPADO` e `VAZIO`, projetam no mesmo estado);
   linha ocupada com identidade válida → linha de paciente (fora da
   contagem operacional); identificação parcial → caso incompleto
   (fora da contagem operacional).
2. **Colapsamento por chave** `(identidade de fonte normalizada, leito
   normalizado)` — a mesma chave da ponte v3/v4 — sobre os estados
   efetivos: linhas operacionais de chaves unânimes contam 1 posição no
   estado; chaves com mais de um estado efetivo, ou com estado + linha de
   paciente/incompleta, são divergentes; linhas sem leito ficam fora.

A regra de consenso/divergência não reusa `_classify_key_rows`/
`_row_signature` diretamente: a assinatura v3/v4 incorpora nome e
prontuário crus em linhas ocupadas, sem a projeção de marcadores — sem a
etapa 1, um marcador isolado seria tratado como posição ocupada e
variantes do mesmo estado como divergência. Chaves só de pacientes não
participam da contagem operacional (compartilhamento de leito entre
pacientes já é caso da lista de unidades).

A função resultante é consumida por:

1. `_calculate_v5` (materialização → números persistidos);
2. `_v5_real_totals` (card — lê o persistido, não recalcula);
3. nova view de detalhe (reclassifica em memória as snapshots do run
   exato, para listar os casos por setor).

O card continua lendo **apenas o JSON persistido**; a página de detalhe
reclassifica em memória com o **mesmo** classificador, portanto
reconciliar por construção. Teste dedicado garante o fechamento
card ↔ detalhe sobre o mesmo censo sintético.

Fechamento por LINHAS (não por leitos): toda linha operacional classificada
cai em exatamente um bucket —

```text
soma(operational_positions_by_status)
  + operational_duplicate_extra_rows
  + operational_conflict_rows
  + operational_rows_without_bed
  == soma(operational_rows_by_status)
```

— de modo que um leito com dois estados distintos contribui com 2
`conflict_rows` (fechamento) e 1 `conflict_position` (linha do card).

### D3 — Schema do reconciliation 3 → 4 com fallback

Novas chaves agregadas no JSON persistido (todas inteiras, allowlist):

- `operational_positions_by_status` (substitui `operational_rows_by_status`
  como fonte dos badges);
- `operational_duplicate_extra_rows`;
- `operational_conflict_positions` (leitos divergentes — linha do card);
- `operational_conflict_rows` (linhas envolvidas em divergência —
  fechamento aritmético);
- `operational_rows_without_bed`.

`schema_version` passa a 4. Medidas de compatibilidade:

- Measurements schema 3 não são regravados (imutabilidade); o render lê a
  chave antiga quando `schema_version < 4` e mantém os números por linha.
- `_v5_real_totals` não mistura esquemas: ou lê o conjunto novo completo,
  ou o antigo — nunca um híbrido.
- A chave antiga continua sendo gravada também no schema 4 (barato,
  inteiro já calculado) para comparação de auditoria linha × leito na
  página de detalhe de fotos novas.

### D4 — Página de detalhe vinculada ao measurement

- Rota `beds/estados-operacionais/` com parâmetro `measurement` (id).
- View `@login_required` resolve o measurement, valida `algorithm_version
  == occupancy-v5`, carrega as `CensusSnapshot` do `census_run` (uma query)
  e reclassifica em memória.
- Cabeçalho: horário de captura; aviso quando `Max(captured_at)` global for
  maior que o da foto.
- Agrupamento por setor na identidade `(setor_codigo, setor)` já usada na
  lista de unidades.
- Conteúdo por setor: leitos inequívocos por estado (contagens), leitos
  divergentes (leito + conjunto de estados informados), linhas repetidas
  colapsadas (leito + estado + N linhas), casos ocupado + estado (leito +
  estados), linhas sem leito (estado + contagem).
- Privacidade: nenhum nome cru ou prontuário — apenas estado classificado,
  leito e setor (alinhado à lista de unidades, que também não exibe nome
  em linha operacional).
- Para fotos schema 3: mesma evidência por setor, com rótulo explícito de
  que os badges daquela foto contaram linhas, e a listagem dos casos que
  geraram a diferença.

### D5 — Sem migrations, sem novos modelos

Toda a informação nova é derivada: agregados no JSON existente do
measurement e reclassificação em memória na view. Nenhum modelo, campo ou
migration.

## Risks / Trade-offs

- [Números do card mudam de significado após o deploy] → subtítulo do card
  passa a dizer "por leito"; decisão de histórico imutável já aprovada;
  comunicado operacional fica fora do escopo do código.
- [Divergência silenciosa entre classificador da materialização e da
  apresentação] → D2: mesma função; teste de fechamento card ↔ detalhe;
  teste de que `operational_positions_by_status` + contadores de exceção
  fecham com o total de linhas operacionais classificadas.
- [Página de detalhe de foto antiga (schema 3) confundir usuários] →
  rótulo explícito de semântica histórica no cabeçalho do detalhe.
- [Custo de query da página de detalhe] → uma única query de snapshots do
  run, já o padrão da `/beds/`; sem N+1 (nenhuma relação além do run e do
  catálogo para o título de aliar por código, quando existir).
- [`DailyOccupancySummary` ou outra superfície ler
  `operational_rows_by_status`] → verificação obrigatória no início do
  slice 1 (`rg` no repo); consumidores já mapeados hoje — o card e a ponte
  de reconciliação do template (`bed_status.html`, seção colapsada que
  exibe `operational_rows_by_status`) — permanecem válidos porque a chave
  antiga segue gravada no schema 4; qualquer consumidor além desses é
  condição de bloqueio.

## Migration Plan

1. Deploy do código com schema 4 (slice 1 + 2 juntos ou sequenciais na
   mesma release).
2. Novos runs materializam com contagem por leito; runs antigos seguem
   renderizando schema 3 com fallback.
3. Rollback: reverter o código; JSONs schema 4 gravados permanecem
   válidos e o render de fallback lê schema 3 — para uma mesma foto nunca
   existirão dois schemas (measurement imutável por run).

## Open Questions

- Nenhuma bloqueante. Rótulos exatos de UI (texto do aviso de foto antiga,
  ordem das seções por setor) podem ser ajustados na implementação sem
  alterar contrato.
