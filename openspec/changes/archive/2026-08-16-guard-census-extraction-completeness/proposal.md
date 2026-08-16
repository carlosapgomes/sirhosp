# Change Proposal: guard-census-extraction-completeness

## Why

A execução real do `run_adaptive_census_cycles --once` produziu um censo
parcial com 25 setores, enquanto o histórico recente mostra média de cerca de
43 setores por batch e mediana de 44. Como a extração parcial foi marcada como
sucesso, o sistema enfileirou um batch incompleto, comprometendo indicadores de
ocupação, gestão de leitos, qualidade assistencial, jurídico e prontuários.

## What Changes

- Introduzir validação conservadora de completude para extrações de censo:
  a extração só deve ser aceita para processamento quando tiver pelo menos 40
  setores distintos.
- Persistir e exibir métricas operacionais de cobertura da extração:
  setores encontrados, setores processados, setores com erro e total de linhas
  persistidas.
- Impedir que o orquestrador processe extração de censo que não atenda ao
  mínimo de 40 setores.
- Melhorar a robustez da coleta da lista de setores no script Playwright para
  reduzir risco de dropdown/autocomplete parcialmente carregado.
- Manter compatibilidade dos comandos manuais existentes, mas tornar falhas de
  completude explícitas e seguras.
- Não alterar regras clínicas de deduplicação, criação de pacientes,
  movimentações ou enfileiramento por paciente além do bloqueio de snapshots
  incompletos.

## Capabilities

### New Capabilities

- `census-extraction-completeness`: cobre validação de completude, métricas
  de cobertura e falha segura para extrações de censo parcialmente coletadas.

### Modified Capabilities

- `adaptive-census-orchestration`: o orquestrador deve tratar extrações abaixo
  de 40 setores como falha operacional e não chamar `process_census_snapshot`.
- `census-snapshot-processing`: o processamento por `run_id` deve rejeitar
  snapshots de censo incompletos, evitando criação de `CensusExecutionBatch`
  para extrações abaixo do limiar mínimo.
- `ingestion-run-observability`: as métricas de estágio de `census_extraction`
  devem expor contadores agregados de cobertura sem dados sensíveis.

## Impact

- Código afetado: `extract_census`, serviços de censo, orquestrador
  adaptativo, testes unitários focados e possivelmente o script Playwright de
  extração de setores.
- Banco de dados: preferir reutilizar `IngestionRunStageMetric.details_json`
  e `IngestionRun.error_message`; criar migração somente se um slice provar
  que a persistência atual é insuficiente.
- Operação: extrações com menos de 40 setores deixam de alimentar batches e
  passam a exigir nova tentativa ou investigação operacional.
- Deploy: sem nova dependência externa, sem Celery/Redis e sem alteração de
  topologia.
- Não objetivos: não criar UI nova, não implementar catálogo administrativo
  de setores, não reprocessar batches incompletos e não apagar batches
  históricos já criados.
- Riscos principais: o limiar fixo de 40 pode bloquear uma extração legítima
  se o hospital reduzir drasticamente os setores ativos; mitigação inicial é
  tornar o valor centralizado, testado e visível nos logs para ajuste futuro.
