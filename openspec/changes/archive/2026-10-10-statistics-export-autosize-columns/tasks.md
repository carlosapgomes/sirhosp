# Tasks: statistics-export-autosize-columns

Change ainda não aprovada para implementação. Execução somente via
`/slice-loop` ou `/change-loop` após aprovação explícita.

## 1. COL-001 — Largura de coluna conforme o conteúdo

Contract: `slices/slice-001-autosize-columns.md`.

- [x] 1.1 RED: failing-before (helper inexistente, larguras no default)
  registrado em `/tmp/sirhosp-slice-COL-001-report.md`.
- [x] 1.2 GREEN: helper `autosize_columns` + chamada no builder, sem tocar
  valores/contrato (só `export.py` + novo unit; nenhum teste existente
  editado).
- [x] 1.3 Review independente read-only: **ACCEPT**, zero findings +
  validações focadas (unit 4205, integration 949, lint, typecheck,
  markdown-lint, `openspec validate --strict`). Slice COL-001 ACEITO pelo
  controller.

## 2. Gate final da change e revisão humana

Não é um segundo slice.

- [x] 2.1 `./scripts/test-in-container.sh quality-gate` e
  `./scripts/test-in-container.sh integration` no estado final, exit 0
  (evidência do worker no estado aceito, sem mudança de código após).
- [x] 2.2 `openspec validate statistics-export-autosize-columns --strict`
  passando; `.md` com markdown-lint passando.
- [x] 2.3 `READY_FOR_HUMAN_FINAL_REVIEW` + aceite humano explícito do
  operador (2026-10-10); archive autorizado para a rc.36 (sem sync de
  specs: `skip_specs: true`).
