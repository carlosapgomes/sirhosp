# Tasks — `topbar-census-freshness`

## 1. TCF-S1 — Badge de frescor da foto do censo (estático)

- [x] 1.1 Baselines oficiais (unit 3187 / integration 494) registradas e
      árvore limpa sobre o commit base.
- [x] 1.2 RED: testes novos falham com o comportamento atual (unit do
      processor reescrito para a semântica da foto; render do topbar com
      "Censo: HH:MM", data quando não hoje, classes de idade, title
      completo, ausência de query sobre IngestionRun).
- [x] 1.3 GREEN: `sync_status` reescrito com helper da foto do censo
      (`Max(captured_at)`), chaves `census_sync_label/title/age_class`;
      topbar.html atualizado; classes CSS do dot em `sirhosp.css`.
- [x] 1.4 Gates: quality-gate, integration, openspec strict e markdown
      lint exit 0, passed >= baseline.
- [x] 1.5 Relatório `/tmp/sirhosp-slice-TCF-S1-report.md` com RED/GREEN,
      snippets antes/depois, contagens baseline vs final e handoff para
      verificador; marcar 1.1–1.5 somente após tudo verde.

## 2. TCF-S2 — Badge vivo via HTMX (self-rearming)

- [x] 2.1 BASE_REF = commit aprovado do TCF-S1; baselines re-registradas.
- [x] 2.2 RED: endpoint ausente (404/não existe), fragmento sem hx-*,
      include do topbar ainda inline; testes de endpoint (200 autenticado
      com fragmento + atributos hx, 401 anonymous sem corpo de login,
      orçamento de 1 query) falham.
- [x] 2.3 GREEN: fragmento `topbar_sync.html` com
      `hx-get/hx-trigger="every 60s"/hx-swap="outerHTML"`; view manual-auth
      (401 anonymous, render do fragmento autenticado); rota
      `services_portal:census_sync_badge`; topbar inclui o fragmento.
- [x] 2.4 Gates completos exit 0 com passed >= baseline.
- [x] 2.5 Relatório `/tmp/sirhosp-slice-TCF-S2-report.md` e marcação 2.1–2.5
      somente após tudo verde.

## 3. Verificação final do change

- [x] 3.1 Relatórios COMPLETE aprovados de TCF-S1 e TCF-S2 por verificador
      independente, com RED reproduzido e gates re-executados.
- [x] 3.2 `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` com exit code zero.
- [x] 3.3 `openspec validate topbar-census-freshness --strict` e
      `./scripts/markdown-lint.sh` sem erros.
- [x] 3.4 Revisar diff acumulado: sem PHI, sem model/migration/status/
      dependência não autorizados; nenhuma query IngestionRun no caminho do
      topbar; dashboard intocado.
