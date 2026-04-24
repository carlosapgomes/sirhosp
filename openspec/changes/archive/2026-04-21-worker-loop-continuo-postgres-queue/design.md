<!-- markdownlint-disable MD013 -->

# Design: worker-loop-continuo-postgres-queue

## Context

A fila já está no PostgreSQL (`IngestionRun`). O worker atual executa uma vez e encerra. Com `restart: unless-stopped`, o container entra em ciclo de restart mesmo sem erro.

## Goals

- Manter worker `Up` continuamente.
- Polling periódico para buscar runs `queued`.
- Dormir quando não houver trabalho.
- Processar imediatamente quando houver trabalho.

## Decision

Adicionar modo contínuo ao comando `process_ingestion_runs`:

- `--loop`: mantém processo vivo.
- `--sleep-seconds <N>`: intervalo entre polls quando não houver trabalho.

Compose dev/prod usará `--loop --sleep-seconds 5` (valor inicial simples).

## Operational flow

1. Worker inicia em loop.
2. Busca runs `queued`.
3. Se houver, processa lote.
4. Se não houver, loga estado ocioso e dorme N segundos.
5. Retoma polling.

## Risks

- Polling muito curto pode gerar ruído/carga desnecessária.
- Polling muito longo aumenta latência para início do processamento.

## Mitigation

- Tornar `sleep-seconds` configurável.
- Iniciar com 5s no compose.

## Validation strategy

RED/GREEN operacional (sem suíte nova obrigatória):

- RED: worker em modo one-shot + restart flapping.
- GREEN: worker em loop, `Up` estável, processa run `queued`.
