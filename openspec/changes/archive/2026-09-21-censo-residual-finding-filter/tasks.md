# Tasks — `censo-residual-finding-filter`

## 1. CRF-S1 — Filtro "Suspeita de paciente residual" em `/censo/` + export WYSIWYG

- [x] 1.1 Baselines oficiais registrados (`./scripts/test-in-container.sh
      unit` e `integration` no commit base; registrar passed reais) e árvore
      limpa; registrar `BASE_REF`.
- [x] 1.2 RED: nova classe `TestCensoFindingFilter` em
      `tests/integration/test_censo_patient_flow_findings.py` (apenas
      adições) falhando pelo motivo certo — página/export ignoram
      `?finding=residual` hoje.
- [x] 1.3 GREEN: `_build_censo_context` (param `finding`, filtro
      pós-classificador/pré-ordenação, `finding_filter` no contexto, achados
      no export quando o filtro exige — D1–D3 do design) + `censo.html`
      (select "Situação" com estado preservado, grid responsivo) — no máximo
      3 arquivos no diff.
- [x] 1.4 Verificação local: arquivo de testes afetado completo +
      `tests/unit/test_services_portal_censo.py` verdes no container; ruff
      nos arquivos alterados.
- [x] 1.5 Relatório `/tmp/sirhosp-slice-CRF-S1-report.md` com RED/GREEN,
      snippets antes/depois, contagens e handoff para verificador; marcar
      1.1–1.5 somente após tudo verde.

## 2. Verificação final do change

- [x] 2.1 Relatório COMPLETE aprovado de CRF-S1 por verificador
      independente (review round 1: `Merge verdict: OK`, zero achados; ver
      notas de execução), com checks re-executados pelo parent.
- [x] 2.2 `./scripts/test-in-container.sh quality-gate` e
      `./scripts/test-in-container.sh integration` com exit code zero,
      passed >= baseline (unit 3591 = baseline; integration 701 = 695 + 6
      novos; quality-gate exit 0).
- [x] 2.3 `openspec validate censo-residual-finding-filter --strict` e
      `./scripts/markdown-lint.sh` sem erros.
- [x] 2.4 Revisar diff acumulado: sem PHI, sem model/migration/dependência,
      classificador intocado, export sem coluna de achado.

## 3. Emendas e notas de execução (autorizadas/registradas pelo parent)

- **Emenda A — edição de 2 testes pré-existentes** (durante CRF-S1): os
  testes `test_none_finding_renders_no_placeholder` e
  `test_censo_renders_mirror_stale_label_without_surface_changes`
  asseriam ausência page-wide da string do label, o que colide com o
  `<option>` do filtro aprovado. Autorizada edição mínima escopando a
  asserção à superfície de badge/lista, preservando nomes/intenção e a
  capacidade de detectar badge residual indevido (comprovada por controle
  de mutação). O restante do arquivo permanece apenas adições.
- **Emenda B — critério de formatação**: `ruff format --check` exit 1 nos
  2 arquivos Python é drift pré-existente do BASE_REF (75/18 hunks).
  Critério vigente: zero drift incremental (invariante 75/18 comprovada;
  símbolos do slice ausentes dos hunks remanescentes). `ruff check` exit 0.
- **Notas de execução**: revisão independente feita por inspeção read-only
  (sem re-execução de testes pelo reviewer); validações re-executadas pelo
  parent: quality-gate exit 0, openspec strict válido, markdown lint sem
  erros, scan de PHI no diff limpo. Detalhes em
  `/tmp/sirhosp-slice-CRF-S1-report.md` (inclui §10 com o histórico
  completo da Emenda B).
