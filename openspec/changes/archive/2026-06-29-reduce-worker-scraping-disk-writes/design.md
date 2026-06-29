# Design: Reduce Worker Scraping Disk Writes

## Context

Em produção, o serviço `worker` executa `process_ingestion_runs --loop` e pode
ser escalado para até 15 réplicas. A carga dominante é `full_sync`, que chama
scrapers Playwright/Chromium por subprocesso para capturar snapshot de
internações e evoluções clínicas.

A análise do código mostrou uso frequente de `tempfile.TemporaryDirectory()` e
artefatos temporários de scraping, incluindo downloads Playwright, PDFs, TXT,
JSON e HTML/screenshot de debug. Sem `tmpfs`, esses arquivos efêmeros são
escritos no overlay do Docker, localizado no NVMe via `data-root`.

O servidor alvo tem cerca de 62 GiB de RAM, 8 GiB de swap em `/swapfile` e
`vm.swappiness=10`. A estratégia inicial deve reduzir escrita física sem criar
uma mudança arquitetural, sem Celery/Redis e sem refatorar scrapers.

## Goals / Non-Goals

**Goals:**

- Reduzir escrita efêmera em disco físico causada por workers Playwright.
- Manter a persistência clínica e operacional no PostgreSQL sem alterações.
- Suportar operação usual com até 15 workers de produção.
- Usar apenas recursos nativos de Docker Compose.
- Manter limites conservadores e parametrizáveis via variáveis de ambiente.
- Entregar slices verticais pequenos, fáceis de revisar por outro LLM.

**Non-Goals:**

- Refatorar código dos scrapers ou parsers.
- Persistir artefatos de debug de scraping.
- Alterar `db`, `web`, `summary_worker` ou `tailscale_app` no primeiro slice.
- Introduzir novas dependências, Celery, Redis ou microserviços.
- Garantir redução absoluta de escrita do PostgreSQL, logs do host ou swap.

## Decisions

### Decision 1: aplicar `tmpfs` somente ao serviço `worker`

O primeiro slice deve alterar apenas o runtime mais provável de causar escrita
massiva: o `worker` de ingestão Playwright. O banco precisa persistir dados, o
`summary_worker` não é o gargalo informado e o `web` não executa o fluxo
contínuo dominante de `full_sync`.

Alternativa considerada: aplicar `tmpfs` também a `web` e `summary_worker`.
Rejeitada para manter o slice mínimo e reduzir risco de drift.

### Decision 2: usar limites conservadores por réplica

A configuração inicial deve usar limites padrão pequenos e ajustáveis:

```text
/tmp:       1g por worker
/var/tmp:   128m por worker
.cache:     256m por worker
.config:     64m por worker
/dev/shm:   512m por worker
```

Com 15 workers, o teto teórico é aceitável para um servidor com 62 GiB de RAM,
mas não reserva tudo antecipadamente. Se houver `ENOSPC` em `/tmp` ou falhas do
Chromium, a operação poderá subir os valores via `.env` sem editar Compose.

Alternativa considerada: configurar 4 GiB ou mais por worker. Rejeitada por
criar um teto teórico alto demais para 15 réplicas.

### Decision 3: direcionar caches XDG para `/tmp`

Além de montar `/home/10001/.cache` e `/home/10001/.config` como `tmpfs`, o
runtime deve definir `TMPDIR`, `TEMP`, `TMP`, `XDG_CACHE_HOME` e
`XDG_CONFIG_HOME`. Isso cobre Python, bibliotecas que respeitam XDG e partes do
Chromium/Playwright que usam `HOME` ou diretórios temporários padrão.

Alternativa considerada: alterar os scripts para passar caminhos explícitos ao
Playwright. Rejeitada neste change para evitar refactor de scraping.

### Decision 4: adicionar rotação de logs no `worker`

Workers contínuos com muitos prints podem gerar escrita em logs JSON do Docker.
A rotação local no serviço limita esse risco sem mudar código.

Alternativa considerada: mudar logging da aplicação. Rejeitada por ser escopo
maior e não necessário para mitigar o risco imediato.

### Decision 5: documentar validação operacional mínima

A implementação deve incluir uma forma simples de verificar se `/tmp` e
`/dev/shm` estão em uso esperado e se `BlockIO`, RAM e swap permanecem
saudáveis. A documentação deve ser curta e focada na execução pós-deploy.

Alternativa considerada: criar scripts de diagnóstico. Rejeitada por
YAGNI; comandos manuais são suficientes para o primeiro slice.

## Risks / Trade-offs

- Pressão de memória com 15 workers → usar limites conservadores, monitorar
  `free`, `swapon --show` e `docker stats`, e subir limites só se necessário.
- Uso de swap no NVMe → manter `swappiness=10`, observar swap durante carga e
  evitar dimensionamento excessivo de `tmpfs`.
- Falhas por permissão em diretórios montados sobre `HOME` → usar `uid=10001`,
  `gid=10001` e modos restritivos nos tmpfs de cache/config.
- Falha do Chromium por `/dev/shm` insuficiente → expor `WORKER_SHM_SIZE` com
  padrão de 512 MiB e orientação para subir para 768 MiB ou 1 GiB.
- Debug descartável pode desaparecer após reinício → comportamento aceito para
  este change, pois os artefatos de scraping não devem persistir em produção.
- Métrica de escrita total pode não cair a zero → PostgreSQL, Docker image
  layers, logs e swap ainda podem escrever no NVMe.

## Migration Plan

1. Implementar o slice de Compose/documentação.
2. Validar a configuração com `docker compose config` usando valores sintéticos
   de ambiente, sem expor credenciais reais.
3. Subir produção gradualmente ou diretamente com a escala usual, conforme a
   janela operacional.
4. Monitorar `docker stats`, uso de `/tmp`, `/dev/shm`, RAM e swap durante um
   ciclo real de ingestão.
5. Se ocorrer `ENOSPC`, aumentar `WORKER_TMPFS_TMP_SIZE` para `2g`.
6. Se o Chromium falhar por memória compartilhada, aumentar `WORKER_SHM_SIZE`
   para `768m` ou `1g`.
7. Rollback: remover as novas chaves do serviço `worker` ou definir valores
   menores e recriar os containers.

## Open Questions

- Qual será a queda real de escrita SMART por hora após o deploy com 15
  workers?
- O limite de `/tmp` de 1 GiB por worker será suficiente nos piores intervalos
  de evolução clínica?
- Um change posterior deve processar PDFs e JSONs em memória para reduzir ainda
  mais escrita efêmera dentro do próprio `tmpfs`?
