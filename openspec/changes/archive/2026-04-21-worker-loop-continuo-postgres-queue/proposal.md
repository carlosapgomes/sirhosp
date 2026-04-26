
# Change Proposal: worker-loop-continuo-postgres-queue

## Why

No modo atual, o worker roda em execução única (`process_ingestion_runs`) e o container reinicia continuamente por causa de `restart: unless-stopped`.

Isso gera ruído operacional, confusão de status (`Restarting`) e pior legibilidade de logs, apesar da fila em PostgreSQL já existir (`IngestionRun.status=queued`).

## What Changes

- Ajustar o worker para modo contínuo opcional (loop + sleep), mantendo PostgreSQL como fila.
- Configurar compose dev/prod para usar worker contínuo em vez de restart por processo one-shot.
- Melhorar evidência operacional: worker permanece `Up`, processa quando há `queued`, dorme quando não há trabalho.

## Non-Goals

- Não introduzir Celery/Redis.
- Não alterar regras de negócio clínicas.
- Não iniciar Fase B.

## Capabilities

### Modified Capabilities

- `containerized-runtime`: worker passa a operar continuamente via polling controlado, sem flapping por reinício constante.

## Impact

- Logs mais limpos e previsíveis.
- Menos overhead de restart.
- Comportamento operacional intuitivo para testes manuais e uso local/prod simples.
