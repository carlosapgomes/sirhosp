# Tasks: statistics-export-zip-per-sector

Change ainda não aprovada para implementação. Execução somente via
`/slice-loop` ou `/change-loop` após aprovação explícita.

## 1. ZIP-001 — Export ZIP com um XLSX por setor

Contract: `slices/slice-001-zip-per-sector.md`.

- [x] 1.1 RED: failing-before (ZIP esperado vs XLSX único, unit de
  `sector_slug`, audit `file_count` ausente) registrado em
  `/tmp/sirhosp-slice-ZIP-001-report.md`.
- [x] 1.2 GREEN: builder ZIP + normalização, view ZIP, migration `0006`
  (`file_count` + backfill `1`), botão substituído, remoção do caminho
  único servido.
- [x] 1.3 Paridade e hardening: seções/counts/ordenação/anti-fórmula por
  XLSX, filenames com data, nada-em-disco, query budget, carga sintética
  medida (19 arquivos/102377 bytes/0.17s).
- [x] 1.4 Review independente read-only: ACCEPT-WITH-P2 → correção P2
  (assertions A2/B2) → ACCEPT-REPAIR; validações focadas
  (check, unit 4194, integration 949, lint, typecheck, markdown-lint,
  `openspec validate --strict`) passando. Slice ZIP-001 ACEITO pelo
  controller.

## 2. Gate final da change e revisão humana

Não é um segundo slice. Verifica o estado aceito do ZIP-001.

- [x] 2.1 `./scripts/test-in-container.sh quality-gate` e
  `./scripts/test-in-container.sh integration` no estado final, exit 0
  (evidência do worker no estado aceito + check/typecheck repetidos
  pelo controller pós-commit).
- [x] 2.2 `openspec validate statistics-export-zip-per-sector --strict`
  passando; nenhum `.md` rastreado alterado.
- [x] 2.3 `READY_FOR_HUMAN_FINAL_REVIEW` + aceite humano explícito do
  operador (2026-10-10); sync + archive autorizados para a rc.35.
