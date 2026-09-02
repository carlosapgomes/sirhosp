# TCF-S2 — Badge vivo via HTMX (endpoint self-rearming)

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/topbar-census-freshness/proposal.md`, `design.md` e
   `tasks.md`;
3. delta `openspec/changes/topbar-census-freshness/specs/portal-shell-freshness/spec.md`
   (requisito "Badge refreshes without page reload");
4. relatório COMPLETE de TCF-S1 (`/tmp/sirhosp-slice-TCF-S1-report.md`) e o
   commit aprovado (BASE_REF obrigatoriamente esse commit);
5. `apps/core/context_processors.py` (pós-S1: chaves
   `census_sync_label/title/age_class` já injetadas em todo RequestContext);
6. `templates/includes/topbar.html` (pós-S1) e `templates/base.html`
   (HTMX 2.0.4 carregado globalmente — confirme o `<script src=...htmx...>`);
7. `apps/services_portal/urls.py` (padrão de rotas do portal) e
   `apps/services_portal/views.py` — padrão de views autenticadas
   (`@login_required`) e um exemplo de render de template;
8. `tests/integration/test_topbar_census_freshness.py` (casa dos testes de
   render do badge, criada no S1 — estender, não duplicar).

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico aos anteriores: BASE_REF (= commit aprovado do TCF-S1) + árvore
limpa; baselines oficiais ANTES de editar (unit = valor final do S1,
integration = valor final do S1 — registre os números reais do commit
base); matriz requisito→arquivo→teste; RED real; GREEN mínimo; inspeções
`rg`; gates completos (`quality-gate`, `integration`,
`openspec validate topbar-census-freshness --strict`,
`./scripts/markdown-lint.sh`) com passed >= baseline; relatório
evidencial. Qualquer falha ⇒ INCOMPLETO sem marcar `tasks.md`/commit.

## Objetivo do slice

O badge do topbar passa a se atualizar sozinho a cada 60 s, sem recarregar
a página: o HTML do badge vira um fragmento próprio
(`templates/includes/topbar_sync.html`) que carrega
`hx-get`/`hx-trigger="every 60s"`/`hx-swap="outerHTML"` apontando para um
endpoint leve autenticado que devolve o mesmo fragmento (self-rearming).
Anonymous recebe **401 sem corpo de login** (HTMX não faz swap de 4xx; nada
de página de login empilhada dentro do badge). O fragmento usa as chaves
`census_sync_*` já injetadas pelo context processor.

## Contexto técnico atual

- Pós-TCF-S1: `topbar.html` renderiza o badge inline com
  `census_sync_label/title/age_class` (estático por carga de página);
  trocar por `{% include "includes/topbar_sync.html" %}`.
- `render(request, template)` usa RequestContext ⇒ os context processors
  rodam também para o fragmento do endpoint; nenhuma lógica de
  apresentação precisa ser duplicada (DRY).
- `@login_required` redireciona 302 → HTMX segue o redirect via AJAX e
  empilharia a página de login dentro do badge. Por isso o endpoint usa
  **verificação manual**: `request.user.is_authenticated` falso →
  `HttpResponse(status=401)` (corpo vazio). Documente no código o porquê
  (comentário curto).
- `apps/services_portal/urls.py`: padrão `path(..., views.x,
  name="...")` sob `app_name = "services_portal"`.
- HTMX 2.0.4 é carregado em `templates/base.html` (global) — o badge em
  qualquer página do shell já o enxerga; não adicione novo `<script>`.

## Escopo funcional

- **R1** — `templates/includes/topbar_sync.html` (novo): o elemento raiz é
  o próprio `div.sirhosp-topbar-sync` do S1 com os atributos
  `hx-get="{% url 'services_portal:census_sync_badge' %}"`,
  `hx-trigger="every 60s"`, `hx-swap="outerHTML"`; conteúdo idêntico ao do
  S1 (label "Censo: ", dot com classe de idade, title completo,
  fallbacks). `topbar.html` passa a apenas `{% include %}` o fragmento.
- **R2** — View `census_sync_badge` em `apps/services_portal/views.py`:
  GET somente; manual auth (401 vazio para anonymous, sem
  `@login_required`); autenticado → `render(request,
  "includes/topbar_sync.html")` (status 200, `text/html`). Sem query além
  das que o context processor já faz (1 agregado indexado).
- **R3** — Rota em `apps/services_portal/urls.py`:
  `path("atualizacao-censo/", views.census_sync_badge,
  name="census_sync_badge")`.
- **R4** — Testes (estender `tests/integration/test_topbar_census_freshness.py`):
  autenticado → 200 + fragmento com "Censo:" + atributos `hx-get`,
  `hx-trigger="every 60s"`, `hx-swap="outerHTML"` (self-rearming: a
  resposta contém os mesmos atributos que o elemento da página); anonymous
  → 401 + corpo sem `csrfmiddlewaretoken`/form de login; página do shell
  autenticada contém o fragmento com os atributos hx; orçamento — no GET
  do endpoint exatamente 1 query tocando `census_censussnapshot` e ZERO
  tocando `ingestion_ingestionrun` (CaptureQueriesContext).
- **R5** — Nada além do badge muda: dashboard, censo, métricas, pacientes,
  workers e CSS intocados; comportamento estático do S1 preservado
  (JS desabilitado ⇒ badge estático continua correto).

## Arquivos esperados e limite

Máximo de **7 arquivos** (emenda aprovada pelo operador, 2026-09-02 — ver
abaixo):

1. `apps/services_portal/views.py`;
2. `apps/services_portal/urls.py`;
3. `templates/includes/topbar.html`;
4. `templates/includes/topbar_sync.html` (novo);
5. `tests/integration/test_topbar_census_freshness.py` (apenas adições);
6. `tests/integration/test_summary_progress_http.py` (somente as 3
   asserções globais de ausência de `hx-trigger` — emenda);
7. `tests/integration/test_ingestion_http.py` (somente a asserção global
   da linha ~357 — emenda).

### Emenda aprovada (2026-09-02) — modernização de asserções legadas

O requisito "Badge refreshes without page reload" coloca
`hx-trigger="every 60s"` em toda página autenticada, tornando obsoleta a
heurística global `'hx-trigger' not in content` de 4 testes pré-existentes
(escritas quando a única fonte possível de `hx-trigger` naquelas páginas
era a área de progresso). A intenção original — estado terminal ⇒ área de
progresso não faz polling de 3 s — permanece e fica **mais precisa**:

- `test_summary_progress_http.py` (3×): `'hx-trigger="every' not in
  content` → `'hx-trigger="every 3s' not in content` (espelha as
  asserções positivas `"every 3s" in content` da mesma família;
  linhas ~176/188);
- `test_ingestion_http.py` (~357): `"hx-trigger" not in content` →
  padrão disjuntivo do teste irmão da linha ~936 do mesmo arquivo
  (`"hx-trigger" not in content or "every 3s" not in content`).

Zero linhas de produção alteradas. Se o badge um dia usar `every 3s`,
ambos voltam a falhar (rede continua armada).

Fora de escopo (proibido): `apps/core/context_processors.py` (sem mudança
de semântica), CSS, dashboard, models/migrations, `base.html`/
`base_sidebar.html`, workers, dependências. Precisando de outro arquivo,
pare e peça emenda.

## TDD obrigatório

### RED (falhando pelo motivo certo antes da implementação)

1. endpoint `services_portal:census_sync_badge` não existe ⇒ reverse
   falha/404 (teste de 200 autenticado falha);
2. anonymous: espera 401 sem corpo de login (hoje sem rota ⇒ falha);
3. página autenticada contém `hx-get`+`hx-trigger="every 60s"` no badge
   (hoje: inline sem hx ⇒ falha);
4. orçamento do endpoint: 1 query census / 0 ingestion (hoje sem endpoint
   ⇒ falha junto com o item 1).

### GREEN

R1–R3 minimamente; R4 prova o contrato; R5 pela estrutura existente.

### REFACTOR

Local apenas: se `topbar.html` ficar com duplicação de fallbacks, mover o
default para o fragmento; sem JS custom, sem polling manual, sem
websockets (YAGNI — HTMX declaraativo resolve).

## Checks de inspeção obrigatórios

```bash
rg -n "census_sync_badge" apps/services_portal/urls.py \
  apps/services_portal/views.py templates/includes/topbar_sync.html
rg -n "hx-get|hx-trigger|hx-swap" templates/includes/topbar_sync.html \
  templates/includes/topbar.html
rg -n "login_required" apps/services_portal/views.py | head -5   # contexto
rg -n "is_authenticated|status=401" apps/services_portal/views.py
rg -n "census_sync_label|census_sync_age_class" \
  templates/includes/topbar_sync.html   # → presente (consome processor)
git diff --check && git diff --stat
```

Interprete: rota+view+fragmento consistentes; os atributos hx existem
somente no fragmento (e não duplicados no topbar); 401 manual presente sem
`@login_required` nessa view; o fragmento consome as chaves do processor
(sem lógica duplicada); exatamente 7 arquivos (5 do slice + 2 da emenda
aprovada, ver seção de arquivos).

## Critérios binários de sucesso

- [ ] Baselines do commit do S1 registrados (exit 0, resumos colados).
- [ ] RED com os 4 itens falhando pelo motivo esperado.
- [ ] Endpoint 200 autenticado devolvendo o fragmento self-rearming.
- [ ] Anonymous → 401 sem corpo de login (nenhum redirect seguido).
- [ ] Páginas do shell incluem o fragmento com hx attrs; sem JS novo.
- [ ] Orçamento: 1 query census / 0 ingestion no endpoint.
- [ ] Estático pós-S1 preservado (badge correto sem JS).
- [ ] quality-gate + integration + openspec strict + markdown-lint exit 0,
      passed >= baseline.
- [ ] Máximo 7 arquivos (emenda aprovada); relatório completo com handoff
      para verificador.

### Condições automáticas de INCOMPLETO

- endpoint com `@login_required` (redirect em vez de 401);
- corpo de login em qualquer resposta do endpoint;
- atributos hx duplicados no topbar ou ausentes na resposta (não
  self-rearming);
- fragmento com lógica de apresentação duplicada em vez de consumir
  `census_sync_*`;
- JS custom/polling manual introduzido;
- processor/CSS/dashboard tocados;
- baseline/RED/gate ausentes ou sem evidência; suíte editada em vez de
  estendida; `tasks.md` marcado com pendência; arquivo extra; markdown lint
  silenciado; relatório sem snippets/handoff.

## Gates de autoavaliação

1. Por que 401 manual em vez de `@login_required` e qual teste imobiliza o
   comportamento anonymous?
2. Como o fragmento rearma o próximo poll e qual asserção prova que a
   RESPOSTA contém os mesmos atributos hx?
3. Quantas queries o endpoint executa e quais testes fixam 1 census / 0
   ingestion?
4. O que acontece com JS desabilitado e qual propriedade estrutural do
   fragmento garante que o badge permanece correto?
5. Onde se prova que nenhuma lógica de apresentação foi duplicada no
   fragmento (ele consome apenas as chaves do processor)?

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-TCF-S2-report.md` com: status; BASE_REF (= commit
S1 aprovado) e árvore; matriz requisito→arquivo→teste; baselines; RED
(comandos, falhas, motivos); GREEN; snippets antes/depois de view, urls,
topbar e fragmento; inspeções `rg` interpretadas; pytest baseline vs final;
gates; respostas aos gates; riscos; `Handoff para verificador` com
arquivos, comandos de rerun e checklist R1–R5. Sem dados reais.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and openspec/changes/topbar-census-freshness/{proposal.md,design.md,tasks.md,slice-prompts/SLICE-TCF-S2.md} first, plus the approved TCF-S1 commit as BASE_REF. Implement ONLY TCF-S2 following the DeepSeek4-Flash protocol: baselines before editing, requirement matrix, real RED (missing badge endpoint and hx attributes), minimal GREEN in at most five files (apps/services_portal/views.py, apps/services_portal/urls.py, templates/includes/topbar.html, new templates/includes/topbar_sync.html, additions to tests/integration/test_topbar_census_freshness.py): self-rearming HTMX fragment (hx-get + hx-trigger every 60s + hx-swap outerHTML) served by a GET endpoint with manual auth returning 401 with empty body for anonymous (never @login_required, never a login body), consuming only the census_sync_* context keys, exactly one census aggregate query and zero ingestion queries. No custom JS, no CSS changes, processor untouched. If anything fails, report INCOMPLETE without marking tasks.md or committing. On success mark only 2.1-2.5, create /tmp/sirhosp-slice-TCF-S2-report.md with RED/GREEN evidence, before/after snippets, baseline-vs-final counts, gate outputs and verifier handoff, commit, push, reply REPORT_PATH=..., then STOP.
```
