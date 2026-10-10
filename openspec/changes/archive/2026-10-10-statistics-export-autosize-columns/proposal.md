# Proposal: statistics-export-autosize-columns

## Why

As abas dos XLSX do ZIP de `/statistics/` saem com a largura de coluna
padrão do Excel (~8,43 caracteres), então textos reais — nomes de setor,
nomes de pacientes, especialidades, origens/destinos — aparecem cortados
(`###` ou truncados visualmente) até o usuário ajustar manualmente cada
coluna em cada arquivo. Dimensionar as colunas no momento da exportação
elimina esse atrito para a equipe de estatísticas, que abre dezenas de
arquivos por dia.

## What Changes

- Após escrever cada XLSX (um por setor, mesma estrutura atual), o
  exportador define `worksheet.column_dimensions[col].width` por coluna a
  partir do maior conteúdo daquela coluna (cabeçalhos incluídos), com
  margem fixa e teto — efeito visual de auto-fit ao abrir, no Excel e no
  LibreOffice.
- Nenhum valor, seção, ordem, coluna, filename, slug, auditoria ou
  comportamento HTTP muda: é somente apresentação (larguras gravadas).
- Sem dependência nova (só `openpyxl`, já usado); tudo em memória.

### Não objetivos

- Não tentar "auto-fit ao abrir" via flag `bestFit` (não é honrado pelos
  leitores — ver design D1).
- Não truncar/quebrar texto, não mesclar células, não mudar fontes/tamanhos.
- Não mudar projeção, materialização, permissões, filenames, auditoria ou
  performance além de um laço O(células) por aba.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

Nenhuma — nenhum requisito de `daily-statistics-reporting` muda: o contrato
de conteúdo (seções, colunas, valores, ordenação) permanece idêntico; só as
larguras gravadas (detalhe de apresentação não pinado na spec) passam a
refletir o conteúdo. Change com `skip_specs: true`.

## Impact

- Código esperado: `apps/statistics_reports/export.py` (helper
  `autosize_columns` + chamada em `build_single_group_workbook`) e testes
  (`tests/unit/` novo + assertions no integration do ZIP).
- Testes existentes do ZIP (33) devem continuar verdes sem modificação;
  fingerprint determinístico preservado (mesmo conteúdo → mesmas larguras).
- Risco principal: estimativa de largura por contagem de caracteres é
  aproximada (fonte proporcional) — margem + teto absorvem; ver design.
