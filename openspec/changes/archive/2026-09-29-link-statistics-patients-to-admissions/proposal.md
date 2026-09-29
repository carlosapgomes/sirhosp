# Proposal: link-statistics-patients-to-admissions

## Why

As listas nominais do relatório diário em `/statistics/` (entradas, saídas,
eventos com origem ou destino não identificado e pacientes do fechamento)
exibem itens de paciente não clicáveis, enquanto `/beds/` já oferece navegação
de cada paciente até sua página de internações. A ausência do link obriga o
usuário a copiar o prontuário e buscar manualmente, atrasando a conferência
clínica do relatório.

## What Changes

- Cada linha nominal das quatro listas internas de setor e das listas da seção
  `Setor não identificado` torna-se clicável e abre a página de internações do
  paciente (`/patients/<pk>/admissions/`) quando o prontuário da linha resolve
  para um paciente único.
- Quando o prontuário não resolve, o nome passa a apontar para a busca de
  pacientes filtrada pelo prontuário (`/patients/?q=<prontuario>`), no mesmo
  padrão de fallback de `/beds/`.
- A resolução prontuário → paciente ocorre em tempo de leitura na camada de
  apresentação, sem alterar revisões materializadas, impressão digital, XLSX ou
  permissões.
- Nenhuma migration, nenhum campo novo e nenhuma permissão nova.

## Capabilities

### Modified Capabilities

- `daily-statistics-reporting`: novo requisito de navegação nominal nas listas
  do relatório diário.

## Impact

- Código: `apps/statistics_reports/presentation.py` (resolução em leitura),
  `apps/statistics_reports/templates/statistics_reports/daily_report.html`
  (links).
- Testes: extensão de `tests/integration/test_daily_statistics_page.py` e
  `tests/integration/test_daily_statistics_export.py` (regressão do
  contrato do workbook).
- Sem impacto em materialização, pipeline adaptativo, Compose, deploy ou RBAC
  existente; o conteúdo exportado em XLSX permanece inalterado.
- Entrega em RC futura; nenhuma ação operacional de produção além do deploy
  padrão.
