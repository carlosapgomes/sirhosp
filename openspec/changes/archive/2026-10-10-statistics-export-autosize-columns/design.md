# Design: statistics-export-autosize-columns

## Context

Ver `proposal.md` para motivação. Estado atual: `build_single_group_workbook`
em `apps/statistics_reports/export.py` escreve as 7 seções via
`_write_group_sheet` e nunca toca em `column_dimensions` — as abas abrem com
a largura padrão do Excel (~8,43). O formato OOXML grava larguras como valores
fixos por coluna; não há flag de "auto-fit ao abrir" honrada pelos leitores.

## Goals / Non-Goals

Goals: colunas com largura proporcional ao conteúdo em cada XLSX, de forma
determinística, sem mudar nenhum valor ou contrato.

Non-Goals: auto-fit real ao abrir, quebra de texto, mudança tipográfica,
novo formato de filename, auditoria ou pipeline.

## Decisions

### D1 — Larguras fixas pré-calculadas, sem `bestFit`

Gravar `width` explícito por coluna. Rejeitado `bestFit=True`: é carimbo que
o Excel escreve após ajuste manual, não instrução — Excel e LibreOffice não
recalculam ao abrir. Largura explícita é respeitada pelos dois.

### D2 — Estimativa por contagem de caracteres

`width = min(MAX_WIDTH, max(DEFAULT, max_len + PADDING))`, onde `max_len` é o
maior `len(str(value))` da coluna (células vazias/`None` contam 0;
cabeçalhos entram na medição), `PADDING = 2`, `MAX_WIDTH = 60`,
`DEFAULT = 8.43` (padrão do Excel; abaixo disso não se grava nada, mantendo
o default e o diff mínimo do arquivo). Rejeitada medição tipográfica real
(Pillow/font metrics): peso morto para ganho visual marginal; margem + teto
absorvem a imprecisão da fonte proporcional. Números e datas usam sua forma
gravada (`str(value)`), consistente com o que o leitor exibe.

### D3 — Onde calcular

No fim de `build_single_group_workbook`, após `_write_group_sheet`, um
helper puro `autosize_columns(worksheet)` — unit-testável sem projeção nem
workbook completo. Mesma chamada serve a todos os arquivos do ZIP
(`build_sector_zip` reutiliza o builder por grupo).

### D4 — Determinismo

Sem data/hora, sem aleatoriedade, sem dependência de ambiente: mesmo conteúdo
→ mesmas larguras → fingerprint do workbook estável (preserva a invariante
LSPA-S1 de que resolução nominal posterior não altera o exportado).

## Risks / Trade-offs

- [Fonte proporcional: `len()` superestima/underestima vs render real] →
  Mitigação: `PADDING=2` + teto 60; teste com strings longas reais
  (sintéticas) confere visualmente via largura gravada.
- [Texto muito longo (ex. origem detalhada) alarga demais] → Teto 60 corta o
  efeito, resto fica para ajuste manual pontual (comportamento atual).
- [Custo O(células)] → Mesmo laço que já escreve as células; sem nova query,
  sem medição de carga dedicada (coberta pela invariante do ZIP-001).

## Migration Plan

Sem migration, sem deploy especial, sem rollback além do code-only padrão.

## Open Questions

Nenhuma.
