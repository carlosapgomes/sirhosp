# Proposal: statistics-export-zip-per-sector

## Why

A equipe de estatísticas do hospital usa o relatório de `/statistics/` por
setor. Hoje o botão `Exportar XLSX` entrega um workbook único com uma aba por
setor, o que obriga a equipe a fatiar manualmente o arquivo antes de
distribuir ou processar por setor. Entregar um ZIP com um XLSX por setor
elimina esse retrabalho no fluxo real de estatísticas.

## What Changes

- **BREAKING**: `GET /statistics/export/` passa a servir um ZIP com um XLSX
  por setor, em vez do workbook único com uma aba por setor. O caminho
  unificado é abandonado; há um único caminho de export.
- Cada grupo renderizado da projeção vira exatamente um XLSX dentro do ZIP,
  na ordem da página, incluindo a seção condicional `Setor não identificado`
  quando aplicável.
- Nome do ZIP e nomes internos incluem a data (e a revisão), no formato
  `estatisticas-diarias-{YYYY-MM-DD}-r{N}`.
- Nome de cada XLSX usa slug `snake_case` ASCII determinístico do título do
  setor (NFKD sem diacríticos, minúsculas, `[^a-z0-9]+` vira `_`), único com
  sufixo `_2`, `_3` e fallback `setor`.
- Conteúdo de cada XLSX preserva o contrato atual da aba: 7 seções fixas em
  ordem, contagens, colunas, ordenação natural, título completo em A1,
  `stable_key` ou marcador em B1, data/revisão em A2/B2 e texto anti-fórmula.
- Auditoria passa a registrar `file_count` (novo campo) mais `row_count`
  total; sem payload nominal e sem persistir arquivos.
- Botão da página passa a indicar ZIP por setor. Geração continua 100% em
  memória (`BytesIO` + `zipfile` stdlib, `ZIP_DEFLATED`).

### Não objetivos

- Não criar segundo endpoint nem manter os dois formatos em paralelo.
- Não introduzir streaming, paginação, filtro novo, Celery/Redis ou nova
  dependência.
- Não mudar projeção, materialização, permissões, seleção de data segura ou
  política `private, no-store`.
- Não reconstruir dias sem revisão `READY` nem alterar navegação nominal
  (LSPA-S1).

## Capabilities

### New Capabilities

Nenhuma capability nova. O comportamento pertence à capability existente.

### Modified Capabilities

- `daily-statistics-reporting`: exportação XLSX vira exportação ZIP com um
  XLSX por setor, filenames com data e auditoria com `file_count`.

## Impact

- Código esperado: `apps/statistics_reports/export.py` (builder ZIP +
  normalização), `apps/statistics_reports/views.py` (resposta ZIP),
  `apps/statistics_reports/models.py` + migration `0006` (`file_count`),
  `apps/statistics_reports/templates/statistics_reports/daily_report.html`
  (rótulo do botão).
- Testes: `tests/integration/test_daily_statistics_export.py` e cobertura
  unit da normalização; fixtures DSRS existentes reutilizadas.
- Compatibilidade: **BREAKING** — consumidores do XLSX único precisam ler o
  ZIP. Stem do download preservado (`estatisticas-diarias-{data}-r{N}`),
  extensão muda para `.zip`.
- Decisões do operador já registradas: manter em memória; filenames com data
  (risco de expor estrutura setorial tolerado e necessário); `file_count`
  explícito; caminho único com substituição.
- Riscos principais: pico de memória 2–3x por N workbooks + ZIP em memória;
  colisões pós-normalização; quebra de quem lia o XLSX único. Ver
  `design.md`.
