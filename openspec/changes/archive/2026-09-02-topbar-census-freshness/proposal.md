# Proposal — `topbar-census-freshness`

## Problema

O badge do topbar ("Sincronizado: HH:MM", presente em todas as ~30 páginas do
portal via `templates/includes/topbar.html`) exibe a `finished_at` do último
`IngestionRun` individual bem-sucedido (`apps/core/context_processors.py::
sync_status`). Durante ciclos de varredura sempre existe um run terminado há
poucos segundos, então o valor parece "agora" e os usuários o leem como hora
de carregamento da página — quando na verdade esperam ver quando o sistema
foi sincronizado com o legado. A informação que eles querem (foto do censo,
"Última varredura completa") existe apenas no card do dashboard.

Agravante medido em produção (eon, 2026-09-01): o context processor roda em
toda renderização com RequestContext (incluindo swaps parciais HTMX) e faz
`ORDER BY finished_at DESC LIMIT 1` sobre `ingestion_ingestionrun` com
1.185.756 linhas e sem índice em `(status, finished_at)` —
**141,8 ms por request** (Parallel Seq Scan). A consulta equivalente da foto
do censo (`max(captured_at)`, índice `census_captured_idx`) custa
**0,163 ms** (~870× mais rápida).

## Objetivo

1. O badge do topbar passa a exibir a hora da **última foto do censo**
   (`Max(CensusSnapshot.captured_at)`), com rótulo "Censo: HH:MM", data
   quando não for hoje ("Censo: 30/08 18:26"), tooltip com timestamp
   completo e dot com cor por idade do dado.
2. O badge é atualizado ao vivo via HTMX (polling leve a cada 60 s),
   eliminando a associação com carregamento de página.
3. O sinal atual (último run individual) é **descartado** — irrelevante para
   o usuário comum (decisão do operador, 2026-09-01).
4. Eliminação do custo oculto de 141,8 ms/request.

## Escopo incluído

- `apps/core/context_processors.py` (reescrita do `sync_status`).
- `templates/includes/topbar.html` (+ novo fragmento
  `templates/includes/topbar_sync.html` no slice 2).
- `static/css/sirhosp.css` (classes de idade do dot).
- Endpoint HTMX autenticado no `services_portal` (slice 2).
- Testes: reescrita dos unitários do processor + novos de render/endpoint.

## Escopo excluído

- Card "Última varredura completa" do dashboard (mantido como está; já usa a
  mesma semântica de foto do censo).
- Migração do sinal "último run" para `/metrica-ingestao` (descartado).
- Novos índices, models, migrations, dependências, workers.
- Mudanças no orquestrador adaptativo ou nos limiares de varredura.
- Media queries mobile (mantém comportamento atual: dot + hora).

## Decisões do operador (2026-09-01)

1. Semântica: foto do censo (`Max(CensusSnapshot.captured_at)`).
2. Rótulo: "Censo: 18:26".
3. Dot por idade: sim — verde ≤2 h, âmbar ≤6 h, vermelho >6 h.
4. Atualização HTMX viva: sim, agora.
5. Sinal antigo: descartar.

## Critérios de sucesso

- Badge em todas as páginas mostra a hora da foto do censo, nunca a hora do
  request nem de runs individuais.
- Dado com mais de 24 h exibe data ("Censo: 30/08 18:26"); tooltip sempre
  com timestamp completo.
- Dot reflete idade da foto nas três faixas acordadas.
- Sem recarregamento, o badge se atualiza a cada 60 s via HTMX.
- Anonymous recebe 401 do endpoint (sem swap de login dentro do badge).
- Nenhuma query sobre `IngestionRun` no caminho de render do topbar.
- Gate completo verde (unit/integration com crescimento esperado).
