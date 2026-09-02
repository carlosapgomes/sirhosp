# TCF-S1 — Badge "Censo:" com a foto do censo no topbar (estático)

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md` (raiz do repositório);
2. `openspec/changes/topbar-census-freshness/proposal.md`, `design.md` e
   `tasks.md`;
3. delta `openspec/changes/topbar-census-freshness/specs/portal-shell-freshness/spec.md`;
4. `apps/core/context_processors.py` (arquivo a reescrever — função
   `sync_status`);
5. `templates/includes/topbar.html`, `templates/base_sidebar.html` (quem
   inclui o topbar) e `templates/base.html` (apenas para contexto do shell);
6. `apps/census/models.py` — somente `CensusSnapshot` (`captured_at`,
   índice `census_captured_idx`);
7. `static/css/sirhosp.css` — bloco `.sirhosp-topbar-sync` (~linha 174) e
   media queries (~linha 416);
8. `tests/unit/test_sync_status_context_processor.py` (será reescrito —
   semântica muda por design);
9. `apps/services_portal/views.py::dashboard` (linhas ~66-81) — apenas para
   entender que o card "Última varredura completa" usa
   `Max(CensusSnapshot.captured_at)` e NÃO deve ser alterado.

Pré-condição: working tree limpa sobre o commit base aprovado (tip do
`master`). Este change não depende de nenhum change ativo.

## Protocolo obrigatório para implementador DeepSeek4-Flash

Idêntico aos slices MSA: BASE_REF + árvore limpa; baselines oficiais ANTES de
editar (`unit` 3187, `integration` 494 — exit 0, resumos colados); matriz
requisito→arquivo→teste antes de codar; RED real (testes falhando pelo motivo
esperado com o código atual); GREEN mínimo; inspeções `rg` interpretadas;
gates completos (`quality-gate`, `integration`,
`openspec validate topbar-census-freshness --strict`,
`./scripts/markdown-lint.sh`) com passed >= baseline; relatório evidencial.
Qualquer item falho ⇒ INCOMPLETO sem marcar `tasks.md`/commit.

## Objetivo do slice

O badge do topbar (todas as ~30 páginas do shell) deixa de mostrar a hora do
último `IngestionRun` individual e passa a mostrar a hora da **última foto
do censo** (`Max(CensusSnapshot.captured_at)`), com rótulo "Censo: HH:MM",
data quando a foto não é de hoje ("Censo: 30/08 18:26"), `title` sempre com
timestamp completo e dot com classe de idade (`is-fresh` ≤ 2 h, `is-stale`
≤ 6 h, `is-outdated` > 6 h ou sem foto). O sinal antigo é **descartado**
(decisão do operador): nenhuma query sobre `IngestionRun` permanece no
caminho de render do topbar. Sem foto: "--:--" + `is-outdated`
(fail-closed, como hoje).

## Contexto técnico atual

- `apps/core/context_processors.py::sync_status` injeta `{"sync_time":
  "HH:MM"}` lendo `IngestionRun` (query ~142 ms em produção — ver
  `proposal.md`); é registrado em `config/settings.py:73` e roda em TODA
  renderização com RequestContext.
- `templates/includes/topbar.html` renderiza
  `{{ sync_time|default:"--:--" }}` dentro de
  `div.sirhosp-topbar-sync > span.dot + span.sirhosp-topbar-sync-label`.
- `templates/base_sidebar.html` inclui o topbar com
  `with page_title=... sync_time=sync_time|default:"--:--"` — o `with` é
  aditivo (o include enxerga todo o contexto), então NOVAS chaves do
  processor chegam ao topbar **sem** alterar o `base_sidebar.html`. Não
  toque nele: o trecho `sync_time=...` passa a ser um pass-through inócuo
  de variável não usada (documentado no design).
- `.sirhosp-topbar-sync .dot` em `static/css/sirhosp.css` tem cor estática
  (`var(--bs-primary)`); media queries escondem o label em telas pequenas —
  comportamento preservado.
- `CensusSnapshot.captured_at` tem índice (`census_captured_idx`); o
  agregado custa ~0,163 ms em produção. Use `django.db.models.Max` +
  `.aggregate`, como o dashboard já faz (não replique outra abordagem).

## Escopo funcional

- **R1** — Helper no próprio `apps/core/context_processors.py` (funções de
  módulo puras, sem request): timestamp da foto
  (`CensusSnapshot.objects.aggregate(Max("captured_at"))`), rótulo
  ("HH:MM" hoje / "dd/mm HH:MM" não hoje, sempre com prefixo de rótulo
  tratado pelo template — o processor devolve apenas o valor temporal),
  `title` completo ("Foto do censo de dd/mm/aaaa hh:mm" ou análogo) e
  classe de idade. Constantes `FRESH_WITHIN = timedelta(hours=2)`,
  `STALE_WITHIN = timedelta(hours=6)`. Tudo com `timezone.localtime`.
- **R2** — `sync_status` reescrito: remove TODA referência a
  `IngestionRun`; injeta `census_sync_label`, `census_sync_title`,
  `census_sync_age_class`; fail-closed para "--:--" + `is-outdated`
  (sem foto ou exceção). `sync_time` deixa de existir no contexto.
- **R3** — `templates/includes/topbar.html`: label "Censo: " + valor novo;
  `title="{{ census_sync_title }}"` no badge; classe de idade no dot
  (`class="dot {{ census_sync_age_class }}"`); fallbacks "--:--".
- **R4** — `static/css/sirhosp.css`: regras fechadas para
  `.sirhosp-topbar-sync .dot.is-fresh` / `.is-stale` / `.is-outdated`
  usando variáveis Bootstrap (`--bs-success`, `--bs-warning`,
  `--bs-danger`); sem mudar layout/estrutura existente do badge.
- **R5** — Testes: reescrita completa de
  `tests/unit/test_sync_status_context_processor.py` para a semântica da
  foto (hoje/outra-data/sem-foto/exceção fail-closed, classes de idade nas
  fronteiras 2 h/6 h inclusivas, title completo, chaves novas) + novo
  `tests/integration/test_topbar_census_freshness.py`: página autenticada
  renderiza "Censo: HH:MM" a partir de snapshot sintético, outra-data
  renderiza dd/mm, classe de idade no HTML, title presente, e **nenhuma
  query em `ingestion_ingestionrun`** durante o render (CaptureQueriesContext
  sobre o GET autenticado).

## Arquivos esperados e limite

Máximo de **5 arquivos**:

1. `apps/core/context_processors.py`;
2. `templates/includes/topbar.html`;
3. `static/css/sirhosp.css`;
4. `tests/unit/test_sync_status_context_processor.py` (reescrita por design);
5. `tests/integration/test_topbar_census_freshness.py` (novo).

Fora de escopo (proibido tocar): `templates/base_sidebar.html`,
`templates/base.html`, dashboard (`views.py`, `dashboard.html`),
models/migrations, `apps/services_portal`, workers, URLs, dependências.
Precisando de outro arquivo, pare e peça emenda ao planner.

## TDD obrigatório

### RED (falhando pelo motivo certo antes da implementação)

1. unit: foto de hoje → label "HH:MM" e chaves novas (hoje o processor
   devolve `sync_time` de IngestionRun ⇒ falha);
2. unit: foto de outro dia → "dd/mm HH:MM" (hoje: semântica de run ⇒
   falha);
3. unit: classes de idade nas fronteiras (≤2 h fresh; 2-6 h stale; >6 h
   outdated; sem foto outdated) — chave inexistente hoje ⇒ falha;
4. integration: página autenticada (ex.: `/painel/`) com snapshot sintético
   de hoje renderiza "Censo: HH:MM" e NÃO contém "Sincronizado:" (hoje
   renderiza o antigo ⇒ falha);
5. integration: CaptureQueriesContext do GET autenticado contém query em
   `ingestion_ingestionrun` ZERO vezes (hoje: 1 ⇒ falha).

### GREEN

R1–R4 minimamente; R5 prova o contrato.

### REFACTOR

Local: extrair a montagem de apresentação (label/title/classe) para função
pura separada da função de acesso ao banco se melhorar leitura; sem
antecipar o slice TCF-S2 (endpoint/fragmento HTMX); YAGNI.

## Checks de inspeção obrigatórios

```bash
rg -n "IngestionRun" apps/core/context_processors.py   # → VAZIO (exit 1)
rg -n "CensusSnapshot|census_sync_" apps/core/context_processors.py \
  templates/includes/topbar.html
rg -n "is-fresh|is-stale|is-outdated" static/css/sirhosp.css \
  apps/core/context_processors.py templates/includes/topbar.html
rg -n "sync_time" apps/core/ templates/   # → VAZIO em apps/core e topbar
git diff --check && git diff --stat
```

Interprete: nenhuma referência a IngestionRun no processor; chaves novas
presentes em processor+topbar; classes fechadas no CSS; exatamente 5
arquivos no diff.

## Critérios binários de sucesso

- [ ] Baselines registrados (3187/494, exit 0).
- [ ] RED com os 5 itens falhando pelo motivo esperado.
- [ ] Badge mostra "Censo: HH:MM" da foto (hoje) / "dd/mm HH:MM" (outra
      data) / "--:--" (sem foto), com title completo sempre.
- [ ] Dot com as três classes fechadas nas fronteiras 2 h/6 h.
- [ ] Zero query IngestionRun no render (provado por teste).
- [ ] Fail-closed preservado (exceção → "--:--" + outdated).
- [ ] Dashboard, base_sidebar, base.html e todo o resto intocados.
- [ ] quality-gate + integration + openspec strict + markdown-lint exit 0,
      passed >= baseline (unit pode cair se testes antigos forem substituídos
      1:1 — documente a contagem final esperada: unit = 3187 − removidos +
      novos; integration = 494 + novos).
- [ ] Máximo 5 arquivos; relatório completo com handoff para verificador.

### Condições automáticas de INCOMPLETO

- qualquer referência a `IngestionRun` sobreviver no processor;
- label antigo "Sincronizado" sobreviver no topbar;
- query de foto feita fora de agregado único (ex.: loop sobre snapshots);
- fallbacks removidos (sem foto deve renderizar "--:--");
- dashboard/base_sidebar/metrics tocados;
- baseline/RED/gate ausentes ou sem evidência; `tasks.md` marcado com
  pendência; arquivo extra; markdown lint silenciado; relatório sem
  snippets/handoff.

## Gates de autoavaliação

1. Qual teste prova que a hora exibida é a da foto e não do request?
2. Onde as fronteiras 2 h/6 h estão testadas (inclusivas em qual lado)?
3. Qual teste impede o retorno da query de IngestionRun?
4. Como o template se comporta quando `census_sync_*` não existe
   (processador em exceção) e onde isso é testado?
5. Por que o dashboard não precisou mudar e qual teste/spec garante que os
   dois sinais permanecem iguais?

## Relatório obrigatório

Crie `/tmp/sirhosp-slice-TCF-S1-report.md` com: status; BASE_REF e árvore;
matriz requisito→arquivo→teste; baselines; RED (comandos, falhas, motivos);
GREEN; snippets antes/depois de processor, topbar e CSS; inspeções `rg`
interpretadas; pytest baseline vs final (exit, passed, failed, errors —
incluindo a contagem de testes unitários substituídos); gates; respostas aos
gates; riscos; `Handoff para verificador` com arquivos, comandos de rerun e
checklist R1–R5. Sem dados reais de pacientes.

## Prompt pronto para o implementador

```text
Read AGENTS.md, PROJECT_CONTEXT.md and openspec/changes/topbar-census-freshness/{proposal.md,design.md,tasks.md,slice-prompts/SLICE-TCF-S1.md} first. Implement ONLY TCF-S1 following the DeepSeek4-Flash protocol: BASE_REF and clean tree, official baselines (unit 3187 / integration 494), requirement matrix, real RED (census-photo semantics replacing the per-run signal: "Censo: HH:MM" label, dd/mm when not today, title with full timestamp, age classes is-fresh/is-stale/is-outdated at 2h/6h boundaries, no IngestionRun query on render), minimal GREEN in at most five files (apps/core/context_processors.py, templates/includes/topbar.html, static/css/sirhosp.css, rewritten unit test file, new integration test file), local refactor only, mandatory rg inspections, full quality gate, openspec strict and markdown lint. Dashboard, base_sidebar.html and everything else must remain untouched. If anything fails, report INCOMPLETE without marking tasks.md or committing. On success mark only 1.1-1.5, create /tmp/sirhosp-slice-TCF-S1-report.md with RED/GREEN evidence, before/after snippets, baseline-vs-final counts, gate outputs and verifier handoff, commit, push, reply REPORT_PATH=..., then STOP.
```
