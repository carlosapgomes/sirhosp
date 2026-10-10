# Slice ZIP-001 — Export ZIP com um XLSX por setor (substitui workbook único)

## Identity

- Change: `statistics-export-zip-per-sector`.
- Slice: `ZIP-001`.
- Task: grupo 1 de `tasks.md`.

## Objective

Substituir o download de `/statistics/export/` por um ZIP com um XLSX por
setor, com filenames com data e auditoria com `file_count`.

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/statistics-export-zip-per-sector/proposal.md`.
- `openspec/changes/statistics-export-zip-per-sector/design.md` (D1–D7).
- `openspec/changes/statistics-export-zip-per-sector/specs/daily-statistics-reporting/spec.md`.
- `apps/statistics_reports/views.py` (export view atual).
- `apps/statistics_reports/export.py` (`build_export_workbook`,
  `_write_group_sheet`, `sheet_titles`, `export_filename`).
- `apps/statistics_reports/models.py` (`StatisticsExportLog`).
- `apps/statistics_reports/templates/statistics_reports/daily_report.html`
  (botão atual).
- `tests/integration/test_daily_statistics_export.py` (padrão de download,
  filename travado, nada-em-disco, query budget).

Follow the repository engineering policy in `AGENTS.md` and preserve existing
conventions. Prefer the smallest correct change; avoid speculative
abstraction and unrelated refactoring.

## Requirements

| ID | Requisito | Evidência planejada |
| --- | --- | --- |
| R1 | Endpoint existente serve ZIP com 1 XLSX por grupo, na ordem da página, incluindo condicional desconhecido | Integration: abre ZIP, lista nomes, confere ordem e condicional |
| R2 | ZIP e internos com data+revisão; slug snake ASCII único determinístico, fallback e desempate | Unit da normalização (acentos, espaços, inválidos, colisão, truncagem, fallback) + integration dos nomes |
| R3 | Cada XLSX preserva contrato da aba: 7 seções em ordem, counts, colunas, ordenação, A1/B1/A2/B2, anti-fórmula | Integration: reabre cada XLSX com openpyxl e compara seções/valores |
| R4 | HTTP preservado: permissão `export_daily_statistics`, `?date=` + default seguro, 404 sem READY, `private, no-store`, `application/zip` + `attachment` com data | Integration de auth/data/headers (espelha suíte atual) |
| R5 | Auditoria com `file_count` + `row_count` total, sem nominal, sem persistir, só após resposta pronta; falhas não logam | Integration de audit + migration com backfill `file_count=1` |
| R6 | Tudo em memória (`BytesIO` + `ZIP_DEFLATED`), mesma projeção sem N+1, nenhum arquivo residual | Test nada-em-disco + query budget small vs wide |
| R7 | Caminho único: botão vira `Exportar ZIP por setor`; builder único removido do caminho servido, sem segundo endpoint | Template test + grep sem rota/format paralelos |

## Expected blast radius

Superfícies esperadas:

- `apps/statistics_reports/export.py` (builder ZIP, `sector_slug`,
  `build_single_group_workbook`, remoção do caminho único servido).
- `apps/statistics_reports/views.py` (resposta ZIP + audit `file_count`).
- `apps/statistics_reports/models.py` + migration `0006` (`file_count`).
- `apps/statistics_reports/templates/statistics_reports/daily_report.html`
  (rótulo do botão).
- `tests/integration/test_daily_statistics_export.py` (+ unit de slug onde
  o projeto colocar).

Superfícies sensíveis / fora de escopo sem escalada:

- `presentation.py`, materialização, catálogo, permissões, seleção de data,
  navegação nominal LSPA-S1, outros exports (`censo_export_xlsx`,
  reconciliação), Celery/Redis, streaming/paginação.

Arquivo adicional só com justificativa no relatório.

## Failing-before plan

1. Novo teste integration que baixa `/statistics/export/` e espera ZIP com
   N XLSX falha (endpoint ainda serve XLSX único).
2. Unit de `sector_slug` com `OBSTETRÍCIA`, espaços múltiplos, `/:*?` e
   colisão falha (função não existe).
3. Teste de audit esperando coluna `file_count` falha (migration ausente).
4. Medir ZIP do `WIDE_DAY` sintético só após GREEN (carga, não RED).

## Implementation constraints

- Reutilizar `projection.groups` em ordem e `_write_group_sheet`; não
  recalcular agrupamento, ordenação ou colunas na camada de export.
- Stdlib (`zipfile`, `unicodedata`, `re`) + `openpyxl`; nenhuma dependência
  nova.
- Nomes internos ≤ 120 chars, ASCII, sem `<>:"/\|?*`, sem ponto inicial,
  unicidade case-insensitive.
- Não persistir arquivo em disco; não logar nominal; não tocar
  `presentation.py`/materialização.
- Não implementar segundo formato nem `?format=`; remover, não duplicar, o
  builder servido antigo.
- Migration com backfill `file_count=1` para linhas legadas.

## Validation

### Focused validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

Acrescentar o teste de carga sintética do ZIP (bytes/tempo no `WIDE_DAY`
ampliado, sem dados reais) e registrar números no relatório.

### Project-required gates

Seguir `AGENTS.md`; gate final do change cobre o slice único. Todos os `.md`
alterados passam por `./scripts/markdown-lint.sh` e
`openspec validate statistics-export-zip-per-sector --strict` passa.

### Runtime/verification evidence

Download via test client + `zipfile.ZipFile(BytesIO(response.content))` +
`openpyxl.load_workbook` por entry: nomes com data, seções em ordem, counts
e anti-fórmula. Sem Playwright além do existente (download é HTTP direto).

## Acceptance criteria

- [ ] R1: ZIP com 1 XLSX por grupo em ordem, condicional só quando há linha
  sem setor.
- [ ] R2: ZIP e internos com `{data}-r{N}`; slugs ASCII únicos, colisão com
  sufixo, fallback e truncagem cobertos.
- [ ] R3: cada XLSX com 7 seções em ordem, headers/counts/ordenação e
  anti-fórmula iguais ao contrato.
- [ ] R4: auth/data/404/`no-store`/`application/zip`/`attachment` verificados.
- [ ] R5: `file_count` + `row_count` logados sem nominal; falha não loga;
  migration com backfill.
- [ ] R6: em memória, sem arquivo residual, query budget inalterado, carga
  medida.
- [ ] R7: botão substituído, sem endpoint/formato paralelo, sem builder
  legado no caminho servido.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se houver contradição proposal/spec/design,
necessidade de streaming/migração extra/mudança de permissão ou projeção,
expansão material, risco novo de privacidade/integridade além do aceito para
filenames, ou impossibilidade de manter memória/query budget sem redesign.

## Evidence report

Caminho: `/tmp/sirhosp-slice-ZIP-001-report.md`. Seguir relatório
obrigatório de `AGENTS.md` (requirements → evidence, RED/GREEN, arquivos,
comandos/exit, verification, desvios, riscos). Sem dados reais.

## Worker handoff

Implement only this approved slice.
Treat the slice and referenced OpenSpec artifacts as the implementation contract.
Reconstruct context from the listed files; do not rely on prior conversation.
Follow the repository engineering policy.
Produce failing-before evidence, implement the smallest correct change, run focused validation, and produce the required evidence report.
Do not update `tasks.md`, commit, push, merge, archive, or start another slice.
If a new decision is required, stop with `BLOCKED_NEEDS_DECISION` and evidence.
Otherwise finish with `READY_FOR_REVIEW` and `REPORT_PATH=/tmp/sirhosp-slice-ZIP-001-report.md`.
