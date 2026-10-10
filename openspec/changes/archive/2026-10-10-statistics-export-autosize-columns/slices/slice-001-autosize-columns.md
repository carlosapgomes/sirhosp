# Slice COL-001 — Largura de coluna conforme o conteúdo (ZIP por setor)

## Identity

- Change: `statistics-export-autosize-columns`.
- Slice: `COL-001`.
- Task: grupo 1 de `tasks.md`.

## Objective

Dimensionar as colunas de cada XLSX do ZIP pelo maior conteúdo da coluna,
sem alterar nenhum valor ou contrato do export.

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/statistics-export-autosize-columns/proposal.md`.
- `openspec/changes/statistics-export-autosize-columns/design.md` (D1–D4).
- `apps/statistics_reports/export.py` (`build_single_group_workbook`,
  `_write_group_sheet`, `_write_cell`).
- `tests/integration/test_daily_statistics_export.py` (padrão ZIP; devem
  continuar verdes sem modificação, salvo assertions novas de largura).
- `tests/unit/test_daily_statistics_sector_slug.py` (padrão de unit local).

Follow the repository engineering policy in `AGENTS.md` and preserve existing
conventions. Prefer the smallest correct change; avoid speculative
abstraction and unrelated refactoring.

## Requirements

| ID | Requisito | Evidência planejada |
| --- | --- | --- |
| R1 | Cada coluna de cada XLSX recebe `width` explícito quando o conteúdo excede o default: `min(60, max(8.43, max_len + 2))`, cabeçalhos incluídos, vazias contam 0 | Unit de `autosize_columns` (curto/longo/vazio/cabeçalho maior que dados/teto) |
| R2 | Determinismo: mesmo conteúdo → mesmas larguras (fingerprint estável) | Unit repetido + suíte ZIP existente verde sem edição |
| R3 | Nenhum valor, seção, ordem, filename, slug ou auditoria muda | Integration ZIP existente (33 testes) verde + diff sem toque em valores |
| R4 | Tudo em memória, sem query nova, sem degradação relevante | Sem N+1 (nenhuma query no helper); tempo da suíte focada registrado |

## Expected blast radius

Superfícies esperadas:

- `apps/statistics_reports/export.py` (helper + 1 chamada).
- Novo `tests/unit/test_daily_statistics_column_width.py` (+ poucas
  assertions de largura no integration do ZIP, se necessário).

Superfícies sensíveis / fora de escopo sem escalada:

- `presentation.py`, `views.py`, `models.py`, migrations, template,
  filenames, auditoria, `bestFit`, quebra de texto, fontes.

## Failing-before plan

1. Unit de `autosize_columns` falha (`AttributeError`, helper não existe).
2. Assertion de largura em XLSX real falha (colunas no default 8.43).

## Implementation constraints

- Helper puro sobre `Worksheet`, sem projeção/DB/clock/random.
- Não usar `bestFit`; não gravar `width` quando o conteúdo cabe no default.
- `str(value)` para não-texto; `None`/vazio conta 0.
- Constantes nomeadas (`PADDING`, `MAX_WIDTH`, `DEFAULT_WIDTH`); sem magic
  numbers espalhados.

## Validation

### Focused validation

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

### Project-required gates

Seguir `AGENTS.md`; `openspec validate statistics-export-autosize-columns
--strict` passa (change com `skip_specs: true`). `.md` com markdown-lint.

### Runtime/verification evidence

Reabrir XLSX do ZIP com openpyxl e conferir `column_dimensions` gravadas
para coluna curta (default) vs longa (dimensionada, ≤ 60).

## Acceptance criteria

- [ ] R1: larguras gravadas seguem a fórmula para todos os casos do unit.
- [ ] R2: duas gerações do mesmo conteúdo têm larguras idênticas; suíte ZIP
  existente verde sem edição de comportamento.
- [ ] R3: diff não toca valores, seções, ordem, filenames ou auditoria.
- [ ] R4: helper sem I/O nem query; tempo da suíte registrado no relatório.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se algum teste existente quebrar por causa
das larguras (ex. fingerprint byte a byte pinado), se for preciso mudar
contrato/spec, ou se surgir decisão de apresentação além de D1–D4.

## Evidence report

Caminho: `/tmp/sirhosp-slice-COL-001-report.md`. Seguir relatório
obrigatório de `AGENTS.md`. Sem dados reais.

## Worker handoff

Implement only this approved slice.
Treat the slice and referenced OpenSpec artifacts as the implementation contract.
Reconstruct context from the listed files; do not rely on prior conversation.
Follow the repository engineering policy.
Produce failing-before evidence, implement the smallest correct change, run focused validation, and produce the required evidence report.
Do not update `tasks.md`, commit, push, merge, archive, or start another slice.
If a new decision is required, stop with `BLOCKED_NEEDS_DECISION` and evidence.
Otherwise finish with `READY_FOR_REVIEW` and `REPORT_PATH=/tmp/sirhosp-slice-COL-001-report.md`.
