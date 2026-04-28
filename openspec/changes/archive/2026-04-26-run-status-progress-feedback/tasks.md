# Tasks: run-status-progress-feedback

## 1. Slice PF-1 — Backend: view de fragmento + template parcial + testes

**Escopo**: criar endpoint que retorna HTML parcial com estágios de progresso,
template parcial reutilizável, e view `run_status` expondo `stage_metrics`.

**Limite**: até **4 arquivos alterados/criados**.

**Prompt executor**: `slice-prompts/SLICE-PF-1.md`

- [x] 1.1 (RED) Criar `tests/unit/test_run_status_progress.py`:
  - `test_fragment_returns_stages_for_running_run`: verifica que o fragmento
    contém nomes e status dos estágios
  - `test_fragment_returns_empty_for_run_without_stages`: run sem estágios
    renderiza mensagem adequada
  - `test_fragment_404_for_nonexistent_run`: run_id inválido retorna 404
  - `test_fragment_requires_auth`: endpoint exige login
  - `test_run_status_view_includes_stage_metrics`: view principal inclui
    `stage_metrics` no contexto
- [x] 1.2 Criar `apps/ingestion/templates/ingestion/_run_progress.html`:
      template parcial com lista de estágios, badges de status e durações
- [x] 1.3 Adicionar view `run_status_fragment` em `apps/ingestion/views.py`
- [x] 1.4 Adicionar URL em `apps/ingestion/urls.py`
- [x] 1.5 Atualizar view `run_status` para incluir `stage_metrics` no contexto
- [x] 1.6 **Gate PF-1**: `./scripts/test-in-container.sh check unit lint`
- [x] 1.7 Gerar `/tmp/sirhosp-slice-PF-1-report.md`

## 2. Slice PF-2 — Frontend: HTMX polling + integração no template

**Escopo**: integrar HTMX no `run_status.html`, carregar lib HTMX no
`base.html`, substituir meta-refresh por polling parcial.

**Limite**: até **4 arquivos alterados**.

**Prompt executor**: `slice-prompts/SLICE-PF-2.md`

- [x] 2.1 (RED) Atualizar `tests/integration/test_ingestion_http.py`:
  - `test_run_status_includes_progress_section`: página principal inclui
    a seção de progresso (include do partial)
  - `test_run_status_uses_htmx_not_meta_refresh`: verificar que meta-refresh
    foi removido para estados queued/running
  - `test_run_status_hx_get_attribute_present`: elemento com `hx-get`
    apontando para URL do fragmento
  - `test_terminal_state_no_polling`: estados succeeded/failed não têm
    polling ativo
  - `test_htmx_script_loaded_in_base`: `base.html` inclui tag script HTMX
- [x] 2.2 Adicionar `<script>` HTMX no `templates/base.html`
- [x] 2.3 Modificar `run_status.html`: substituir meta-refresh por HTMX
      polling + incluir `_run_progress.html`
- [x] 2.4 **Gate PF-2**: `./scripts/test-in-container.sh check integration lint`
- [x] 2.5 Gerar `/tmp/sirhosp-slice-PF-2-report.md`

## 3. Slice PF-3 — Hardening final e fechamento do change

**Escopo**: atualizar specs, quality gate completo, markdown lint, consolidar
relatórios.

**Limite**: até **3 arquivos alterados**.

**Prompt executor**: `slice-prompts/SLICE-PF-3.md`

- [x] 3.1 Atualizar/adicionar spec `run-status-progress` com cenários Gherkin
- [x] 3.2 Atualizar spec `ingestion-run-observability` com requisito de
      exposição de estágios na UI
- [x] 3.3 Executar gate completo: `./scripts/test-in-container.sh quality-gate`
- [x] 3.4 Validar markdown: `./scripts/markdown-lint.sh`
- [x] 3.5 Atualizar `tasks.md` com checklist final
- [x] 3.6 Gerar `/tmp/sirhosp-slice-PF-3-report.md`

## Stop Rule

- Implementar **um slice por vez**.
- Cada slice com ciclo TDD (red → green → refactor).
- Ao concluir um slice, parar e aguardar decisão explícita para o próximo.
- Relatório obrigatório em `/tmp/sirhosp-slice-<ID>-report.md` com:
  - resumo do slice
  - checklist de aceite
  - lista de arquivos alterados
  - fragmentos de código antes/depois por arquivo alterado
  - comandos executados e resultados
  - riscos, pendências e próximo passo sugerido
