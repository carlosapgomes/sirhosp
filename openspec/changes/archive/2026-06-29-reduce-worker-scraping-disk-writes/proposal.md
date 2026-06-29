# Reduce Worker Scraping Disk Writes

## Why

Os workers de ingestão Playwright executam `full_sync` continuamente e podem
criar grande volume de escrita efêmera no overlay do Docker, especialmente com
até 15 réplicas em produção. Reduzir essa escrita preserva a vida útil dos NVMe
e aumenta a previsibilidade operacional sem mudar o domínio clínico nem a
persistência PostgreSQL.

## What Changes

- Configurar o serviço `worker` de produção para usar armazenamento temporário
  em RAM nos diretórios de temp, cache e config usados por Python, Playwright e
  Chromium.
- Definir `shm_size` conservador e parametrizável para melhorar o
  comportamento do Chromium headless sem reservar RAM antecipadamente.
- Propagar variáveis de ambiente de runtime para direcionar temporários e
  caches efêmeros para `/tmp`.
- Adicionar rotação de logs Docker ao `worker` para evitar crescimento
  indefinido de logs em execução contínua.
- Documentar comandos mínimos de verificação operacional após subir até 15
  workers.
- Não alterar o serviço `db`, `summary_worker`, `web` ou `tailscale_app` neste
  change inicial.
- Não refatorar os scrapers neste change; processamento em memória e redução de
  lançamentos de Chromium ficam como evolução futura.

## Capabilities

### New Capabilities

- `production-worker-runtime-io-control`: define requisitos de configuração
  operacional para reduzir escrita efêmera em disco físico nos workers
  Playwright de produção.

### Modified Capabilities

Nenhuma.

## Impact

- Código/configuração afetada: `compose.prod.yml` e documentação operacional
  enxuta, se necessária.
- Sistemas afetados: workers de ingestão em produção executados com Docker
  Compose e `--scale worker=N`.
- Dependências: nenhuma nova dependência; usa recursos nativos de Docker
  Compose (`tmpfs`, `shm_size`, `logging`).
- Riscos principais: pressão de memória/swap se todos os workers usarem seus
  limites máximos simultaneamente; configuração inválida de Compose; permissões
  incorretas para usuário `10001` em diretórios tmpfs.
- Não-objetivos: persistir artefatos temporários/debug de scraping; alterar
  schema de banco; introduzir Celery/Redis; mudar a lógica de scraping ou
  parsing.
