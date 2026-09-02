# Design — `topbar-census-freshness`

## Contexto

Investigação completa em `/tmp/sirhosp-topbar-sync-investigacao.md` (fatos de
código + medições de produção). Resumo: três semânticas de "sincronização"
convivem; o badge do topbar rastreia o run individual (ambíguo, parece page
load), a informação relevante (foto do censo) está só no dashboard, e o
context processor custa 141,8 ms/request em produção (seq scan sobre 1,19 M
de runs sem índice).

## Decisões

- **D1 — Fonte única: foto do censo.** O badge usa
  `CensusSnapshot` + `Max("captured_at")` (mesma semântica do card
  "Última varredura completa" do dashboard). Helper no
  `apps/core/context_processors.py` (funções puras de módulo, testáveis sem
  request): uma para o timestamp, uma para os valores de apresentação. O
  dashboard permanece inalterado (já computa o mesmo agregado para montar a
  foto; nenhuma divergência possível — mesma query, mesma tabela).
- **D2 — Apresentação.** Rótulo "Censo: " + `HH:MM` (timezone local) quando
  a foto é de hoje; `Censo: dd/mm HH:MM` quando não é hoje. Sem foto:
  `--:--`. `title` sempre com timestamp completo
  ("Foto do censo de dd/mm/aaaa hh:mm") para auditabilidade clínica. Sem
  relativo ("há 12 min") — timestamp absoluto sempre visível no tooltip.
- **D3 — Dot por idade.** Classes CSS no dot: `is-fresh` (≤ 2 h),
  `is-stale` (≤ 6 h), `is-outdated` (> 6 h ou sem foto). Limiares são
  constantes de módulo no helper (`FRESH_WITHIN`, `STALE_WITHIN`),
  documentadas como decisão de operação. Nota registrada: o orquestrador
  adaptativo varia o intervalo entre varreduras; limiares rígidos podem
  sinalizar "outdated" em madrugadas normais — aceito pelo operador; o
  tooltip com timestamp completo mitiga.
- **D4 — Context processor.** `sync_status` é reescrito: remove a query de
  `IngestionRun` (sinal descartado por decisão do operador — irrelevante
  para o usuário comum) e injeta o objeto de apresentação do badge. Chaves
  novas no contexto: `census_sync_label`, `census_sync_title`,
  `census_sync_age_class`. Fail-closed: qualquer falha (sem foto, erro)
  degrada para `--:--` + `is-outdated`, como hoje.
- **D5 — Atualização HTMX (Opção C aprovada).** O badge vira um fragmento
  próprio (`templates/includes/topbar_sync.html`) renderizado pelo topbar e
  por um endpoint leve (`GET`, autenticado) que devolve o mesmo fragmento
  com `Content-Type: text/html`. O fragmento carrega
  `hx-get="{% url ... %}" hx-trigger="every 60s" hx-swap="outerHTML"` — a
  resposta substitui o próprio elemento e rearma o próximo poll
  (self-rearming). HTMX 2.0.4 já é carregado globalmente em
  `templates/base.html`.
- **D6 — Autenticação do endpoint sem login-in-badge.** O endpoint NÃO usa
  `@login_required` (que redireciona 302 → HTMX seguiria e empilharia a
  página de login dentro do badge). Faz verificação manual: não
  autenticado → `401` (HTMX não faz swap de 4xx por padrão; o badge fica
  congelado até a próxima navegação completa, que levará ao login).
- **D7 — Orçamento de queries.** Caminho do badge: exatamente 1 query
  agregada index-backed (`max(captured_at)`; 0,163 ms medidos em produção
  com 440.937 snapshots). O poll de 60 s por usuário é trivial. Nenhuma
  query sobre `IngestionRun` permanece no caminho de render do topbar.
- **D8 — Privacidade.** O badge e o endpoint expõem apenas o timestamp da
  foto do censo (informação já pública dentro do portal — mesmo valor do
  card do dashboard). Nenhum PHI novo; nenhum identificador.

## Alternativas rejeitadas

- **B — só trocar o rótulo** ("Último dado recebido"): honesto, mas não
  atende à necessidade (usuário quer a varredura) e mantém 141,8 ms/request.
- **Drain do lote (`CensusExecutionBatch`)** como semântica: 30–50 min depois
  da foto; não corresponde ao que as páginas projetam.
- **D — estado "Sincronizando…" com lote ativo**: acopla o topbar ao estado
  do pipeline; adiado (não aprovado pelo operador).
- **Índice em `(status, finished_at)` para manter o sinal antigo**: sinal
  descartado; custo de manutenção sem benefício.
- **Cache TTL no processor**: desnecessário com agregado indexado de
  0,163 ms; um componente a mais sem ganho mensurável.

## Riscos

- Dot "vermelho" em madrugadas de intervalo longo → aceito (D3), tooltip
  mitiga; limiares são constantes fáceis de recalibrar.
- Poll HTMX a cada 60 s multiplicado por usuários abas abertas → custo
  trivial por request (D7); se um dia escalar, adicionar ETag/204.
- Reescrita dos 6 testes unitários existentes do processor → semântica muda
  por design; teste de caracterização antigo não se aplica.

## Dimensionamento de slices

| Slice | Entrega vertical | Arquivos (máx) |
| --- | --- | --- |
| TCF-S1 | Badge estático correto em todas as páginas (semântica, formato, dot, tooltip, perf) | 5 |
| TCF-S2 | Badge vivo: fragmento + endpoint HTMX self-rearming + 401 | 5 |
| 3.x | Verificação final (gates, diff acumulado, PHI) | — |

TCF-S1 é independente de TCF-S2 e já entrega 100% do valor em carga de
página; TCF-S2 remove a dependência de reload.
