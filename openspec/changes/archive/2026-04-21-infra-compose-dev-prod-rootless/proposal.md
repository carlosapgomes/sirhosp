<!-- markdownlint-disable MD013 -->

# Change Proposal: infra-compose-dev-prod-rootless

## Why

Antes de iniciar a Fase B (espelhamento diário de internados), precisamos reduzir atrito operacional para setup, teste manual e validação de ponta a ponta.

Hoje o projeto roda localmente por comandos `uv` e já suporta PostgreSQL por variáveis de ambiente, mas ainda não existe empacotamento padrão em container para:

- subir banco + aplicação com um comando;
- executar fluxo de ingestão sob demanda com worker em ambiente previsível;
- separar modo desenvolvimento (hot reload) e modo deploy (web server de produção);
- funcionar em ambiente rootless já disponível na máquina.

## What Changes

- Introduzir empacotamento da aplicação Django em imagem de container com build reprodutível.
- Introduzir stack Compose com PostgreSQL + serviços da aplicação.
- Separar execução em dois modos explícitos:
  - **dev**: volume montado, `runserver`, feedback rápido;
  - **prod**: comando de produção (Gunicorn), sem mount de código.
- Incluir serviço de worker para processamento de `IngestionRun` no ambiente containerizado.
- Documentar runbook de setup/execução/testes manuais no host browser.

## Non-Goals

- Não alterar regras de negócio clínicas.
- Não implementar Fase B nesta change.
- Não introduzir Celery/Redis/k8s.
- Não fazer tuning avançado de observabilidade/escala nesta rodada.

## Capabilities

### New Capabilities

- `containerized-runtime`: execução padronizada local/deploy com Compose, PostgreSQL e serviços web/worker.

### Modified Capabilities

- `evolution-ingestion-on-demand`: ganha suporte operacional containerizado para execução manual e validação de fluxo.

## Impact

- Setup mais rápido para QA manual e demo.
- Menor drift entre ambientes de desenvolvimento e execução operacional.
- Base pronta para iniciar Fase B com menos risco infra.
