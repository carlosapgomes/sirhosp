<!-- markdownlint-disable MD013 -->
# Change Proposal: admission-period-representation

## Why

Hoje o sistema mistura dois conceitos diferentes:

1. **janela de extração** (operacional, solicitada pelo usuário);
2. **período de internação** (clínico, real no sistema fonte).

Uma janela de extração pode cobrir só parte de uma internação, múltiplas internações ou nenhum evento, sem que isso signifique ausência de internações conhecidas.

Com isso, há risco de representação incorreta no portal:

- paciente aparece sem contexto completo de períodos de internação;
- evento pode ser associado à internação errada quando faltar `admission_key`;
- lista de pacientes não mostra claramente cobertura entre internações conhecidas x internações com eventos.

## What Changes

- Capturar a **lista completa de internações conhecidas do paciente** durante a extração (independente da janela de evoluções).
- Persistir internações conhecidas mesmo quando:
  - a janela não retornar evoluções;
  - a etapa de evoluções falhar após a captura de internações.
- Associar evoluções à internação por:
  1. `admission_key`;
  2. fallback determinístico por `happened_at` + regras de desempate.
- Melhorar observabilidade da execução:
  - `IngestionRun` passa a reportar métricas de internações capturadas/atualizadas.
- Ajustar representação no portal:
  - lista de pacientes com resumo de cobertura (internações conhecidas vs com eventos);
  - lista de admissões com badge explícito **"Sem eventos extraídos"** quando aplicável.

## Non-Goals

- Não implementar backfill retroativo de banco existente.
- Não alterar arquitetura para Celery/Redis.
- Não criar nova UI de busca HTML (permanece JSON endpoint).
- Não redesenhar a automação inteira; apenas estender contrato para incluir snapshot de internações.

## Decisões de negócio já confirmadas

- Falha ao capturar internações => **falha do run**.
- Falha ao extrair evoluções após capturar internações => **persistir internações e marcar run como failed**.
- Trazer internações conhecidas completas, mas extrair apenas evoluções do período solicitado.
- Vinculação determinística: `admission_key` com fallback por `happened_at`.
- Mostrar na UI internações sem eventos como **"Sem eventos extraídos"**.
- Execução desta change em branch separada de `main`.

## Impact

- Melhor qualidade semântica da linha do tempo clínica.
- Melhor rastreabilidade operacional (run status mais informativo).
- Menor risco de interpretação incorreta de cobertura de dados por paciente.
