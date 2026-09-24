## Why

A equipe de Estatística precisa de um relatório diário nominal e reproduzível das
entradas, transferências, óbitos, altas e pacientes presentes por setor. As
superfícies atuais mostram a situação mais recente do hospital ou agregados de
fluxo, mas não preservam uma projeção diária fechada, versionada e exportável
com os limites censitários e a procedência exigidos para conferência
operacional.

## What Changes

- Criar uma projeção diária materializada e versionada, em `America/Bahia`, a
  partir de censos completos e das evidências persistidas de admissões, altas e
  óbitos.
- Definir o censo de abertura pelo primeiro `IngestionRun` aceito de
  `census_extraction` concluído entre 00:00 e 03:00 e o censo de fechamento pelo
  último run aceito iniciado a partir de 20:00 e concluído antes da meia-noite.
- Usar o último censo aceito anterior como âncora exclusiva de comparação para
  detectar movimentos presentes no primeiro censo do dia, sem confundir o
  `CensusExecutionBatch` clínico com a fotografia censitária.
- Registrar internações, admissões por transferência interna, óbitos, saídas por
  transferência interna e altas hospitalares; eventos sem procedência suficiente
  usam os rótulos descritivos `Entrada no setor — origem não identificada`,
  `Saída do setor — destino não identificado` ou, quando a natureza interna já
  estiver confirmada, `Transferência interna — origem não identificada` e
  `Transferência interna — destino não identificado`, sempre distinguindo
  horário clínico de horário ou intervalo de detecção.
- Materializar a fotografia final por agrupamento oficial e catálogo histórico,
  com capacidade, pacientes, lotação, saldo, excedente e lista nominal do último
  censo do dia.
- Adicionar `/statistics/`, com seletor de data, accordions por setor, listas
  internas, badges de contagem e ordenação natural por leito.
- Adicionar exportação XLSX da revisão selecionada, com uma folha por
  agrupamento oficial e todas as seções presentes mesmo quando vazias.
- Restringir página, item de menu e exportação por permissões dedicadas e
  registrar cada arquivo servido em log de auditoria sem persistir o workbook.
- Permitir regenerações automáticas auditáveis para incorporar evidências
  tardias sem alterar a fotografia censitária de fechamento.
- Classificar o change como **CRÍTICO**, por envolver persistência clínica,
  autorização de dados sensíveis, exportação nominal e auditoria.
- Não implementar correções manuais pela equipe de Estatística neste change.
- Não reconstruir dias anteriores à ativação da feature.
- Não prometer observação contínua: movimentos inteiramente ocorridos entre duas
  fotografias censitárias permanecem tecnicamente indetectáveis.

## Capabilities

### New Capabilities

- `daily-statistics-reporting`: materialização, consulta autorizada, revisão
  automática, exportação XLSX e auditoria do relatório estatístico diário por
  setor.

### Modified Capabilities

- `services-portal-navigation`: incluir o item autorizado `Estatísticas` entre
  `Leitos` e `Fluxo Hospitalar`, com estado ativo coerente.

## Impact

- Novo módulo Django de projeção de relatórios estatísticos, modelos,
  migrations, serviço materializador e management command.
- Leitura integrada de `IngestionRun`, `CensusSnapshot`, medições de ocupação,
  catálogo de capacidade, admissões, altas e óbitos, sem mudar suas regras
  clínicas canônicas.
- Novas permissões, rota, view, template, menu e endpoint XLSX.
- Novo log de exportação nominal e política `no-store` para página e download.
- Integração operacional via PostgreSQL e systemd/management commands, sem
  Celery, Redis ou dependência adicional; `openpyxl` já está disponível.
- Testes unitários e de integração com dados exclusivamente sintéticos,
  incluindo limites de meia-noite, qualidade degradada, idempotência,
  precedência de saídas, segurança do XLSX e autorização.
- Riscos principais: transferências invisíveis entre censos, setor inferido para
  altas/óbitos, atraso ou duplicidade de evidências, classificação de origens,
  exposição de dados sensíveis e conflito entre revisões concorrentes.
