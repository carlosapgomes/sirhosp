# Design: statistics-export-zip-per-sector

## Context

Ver `proposal.md` para motivação. Estado atual (levantado por scouts):

- `apps/statistics_reports/views.py:73-115` serve um workbook único via
  `build_export_workbook(projection)` + `HttpResponse` +
  `Content-Disposition: attachment` + `Cache-Control: private, no-store` +
  `StatisticsExportLog(user, report, sheet_count, row_count)`.
- `apps/statistics_reports/export.py:122-290` monta o workbook com `openpyxl`
  em `BytesIO`: uma aba por `projection.groups` (`zip(strict=True)`), 7
  seções fixas por aba (`SECTIONS`), sanitização de aba em 31 chars
  (`sheet_titles`), filename só com data+revisão, anti-fórmula em
  `_write_cell`.
- Projeção (`presentation.build_daily_report_projection`) entrega grupos em
  ordem de página com 4 queries bulk, sem N+1. Export é read-only no domínio.
- Setor é string (sem modelo `Setor`); nomes reais contêm acentos, espaços
  múltiplos e siglas. Não há slug geral; `slugify` sem uso, `unidecode` não
  instalado, único NFKD é `_fold_name` privado da ingestão.
- Não há geração de ZIP server-side; downloads seguem padrão
  `BytesIO` + `Content-Disposition`.
- `StatisticsExportLog(models.py:524-554)` guarda só agregados, sem nominal.

## Goals / Non-Goals

Goals:

- Substituir o download por ZIP com um XLSX por setor, reutilizando projeção
  e escrita de seção existentes.
- Filenames determinísticos com data, ASCII seguro e unicidade garantida.
- Auditoria com `file_count` explícito e total de linhas, sem nominal.
- Manter permissões, `?date=`, 404, `no-store`, ordenação, seções e
  query budget.

Non-Goals:

- Segundo formato, streaming/`write_only`, paginação, novos filtros,
  mudança de projeção/materialização/permissões ou nova dependência.

## Decisions

### D1 — Substituir o endpoint, sem segundo formato

Mesma rota `statistics/export/` passa a retornar o ZIP. Rejeitada a opção de
`?format=zip` ou rota paralela: o operador decidiu caminho único para não
manter dois contratos de export. É **BREAKING** e está declarado na proposal.

### D2 — Continuar 100% em memória

`BytesIO` por workbook + `zipfile.ZipFile(BytesIO, ZIP_DEFLATED)` + um
`BytesIO` final para o ZIP, servido via `HttpResponse`. Rejeitado streaming
neste change (YAGNI): volume típico são dezenas de setores e poucas centenas
de linhas; o teste de carga do slice mede bytes/tempo e decide se um follow-up
é necessário.

### D3 — Filenames com data e slug snake_case

- ZIP: `estatisticas-diarias-{YYYY-MM-DD}-r{N}.zip`.
- Interno: `estatisticas-diarias-{YYYY-MM-DD}-r{N}-{slug}.xlsx`, com
  `slug = NFKD → ascii → lower → [^a-z0-9]+ → _ → strip(_)`,
  fallback `setor`, truncagem para nome completo ≤ 120 chars, desempate
  determinístico `_2`, `_3` case-insensitive. Grupo desconhecido vira
  `setor_nao_identificado`.
- Rejeitado camelCase (imprevisível com nomes iniciados em número e siglas) e
  kebab-case (equivalente, mas o projeto usa `_` em stems como
  `estatisticas-diarias` já com hífen no stem; o slug do setor usa `_` para
  separar do stem de forma legível). `django.utils.text.slugify` não é usado
  (produz hífens e depende de comportamento Django); `unicodedata` stdlib
  basta, sem `unidecode`.

### D4 — Auditoria com `file_count` explícito

Migration `0006` adiciona `StatisticsExportLog.file_count`
(`PositiveInteger`). Linhas antigas recebem backfill `file_count=1` (eram um
arquivo). Novas linhas ZIP registram `file_count = nº de XLSX`,
`row_count = total de linhas de dados` e `sheet_count = nº total de sheets`
(igual a `file_count` porque cada XLSX tem 1 sheet; documentado, sem
reaproveitar `sheet_count` como "nº de arquivos"). Sem nominal, criada só
após a resposta pronta.

### D5 — Reuso de `_write_group_sheet`

Extrair `build_single_group_workbook(group, report)` que cria um `Workbook`
com 1 sheet e chama `_write_group_sheet`. `build_sector_zip` itera
`projection.groups` em ordem e escreve cada resultado no ZIP. A sheet interna
mantém a sanitização atual (`sheet_titles` para 1 título) para minimizar
diferença; o título completo continua em A1. Remove-se
`build_export_workbook`/`export_filename` do caminho servido (ou mantém como
legado morto? Não: remover para não manter dois builders).

### D6 — `zipfile` stdlib, `ZIP_DEFLATED`, sem dependência

Nada de `xlsxwriter`/`pandas`. `Content-Type: application/zip`,
`Content-Disposition: attachment; filename="<zip>"`.

### D7 — Template indica o novo formato

Texto do botão vira `Exportar ZIP por setor` (mesma permissão
`export_daily_statistics`, mesmo `?date=`). Sem novo botão paralelo.

## Risks / Trade-offs

- [Memória 2–3x: N workbooks + bytes do ZIP + body da resposta] →
  Mitigação: manter em memória por decisão, medir no slice (dia `WIDE_DAY`
  ampliado sintético, bytes/tempo), sem cap artificial neste change.
- [Colisão pós-normalização (`CLÍNICA` vs `CLINICA`, truncagem)] →
  Mitigação: desempate determinístico + teste de colisão.
- [Filename expõe estrutura setorial + data] → Aceito pelo operador como
  necessário ao fluxo de estatísticas; sem prontuário/nome de paciente no
  filename.
- [Quebra de leitores do XLSX único] → BREAKING explícito; stem preservado,
  extensão `.zip`.
- [ZIP com muitos arquivos em FS Windows/macOS] → ASCII, sem
  `<>:"/\|?*`, sem ponto inicial, ≤ 120 chars, case-insensitive único.

## Migration Plan

1. Migration `0006_statistics_export_log_file_count.py`: adiciona
   `file_count` com default/backfill `1` para linhas legadas.
2. Deploy: monólito Django padrão, sem workers novos, sem ordem especial.
   Sem reconstrução de revisões.
3. Rollback: reverter código + migration. ZIPs já baixados continuam válidos;
   endpoint volta ao XLSX único da revisão anterior. Sem perda de dados
   (log preserva linhas antigas com `file_count=1`).

## Open Questions

Nenhuma. As cinco decisões do operador (memória, data nos filenames,
`file_count`, caminho único, substituição) estão incorporadas acima.
