# Slice S3 - Sidecar Tailscale no Compose dev

## Handoff para executor com contexto zero

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/dev-tailscale-vpn-proxy/proposal.md`
4. `openspec/changes/dev-tailscale-vpn-proxy/design.md`
5. `openspec/changes/dev-tailscale-vpn-proxy/tasks.md`
6. Relatórios anteriores em `/tmp/sirhosp-slice-S1-report.md` e
   `/tmp/sirhosp-slice-S2-report.md`

Implemente **somente este slice**.

## Objetivo

Adicionar ao `compose.dev.yml` um sidecar Tailscale dev-only em userspace com
SOCKS5 interno e propagar `PLAYWRIGHT_PROXY_SERVER` aos serviços que executam ou
podem disparar Playwright.

## Escopo permitido

- `compose.dev.yml`
- documentação/env example somente se já existir arquivo apropriado e a alteração
  for pequena; caso contrário deixar para S4

## Limite de arquivos

Até 5 arquivos alterados.

## RED/GREEN operacional

1. RED: registrar que `compose.dev.yml` não possui serviço `tailscale-app` nem
   `PLAYWRIGHT_PROXY_SERVER`.
2. GREEN: `docker compose config` mostra o sidecar e a env opcional.

## Regras técnicas obrigatórias

O serviço `tailscale-app` deve usar:

- `image: tailscale/tailscale:latest`;
- `TS_AUTHKEY` vindo do ambiente;
- `TS_USERSPACE=true`;
- `TS_SOCKS5_SERVER=0.0.0.0:1055`;
- `TS_EXTRA_ARGS=--accept-routes`;
- volume nomeado para `/var/lib/tailscale`.

É proibido adicionar:

- `/dev/net/tun`;
- `NET_ADMIN`;
- `NET_RAW`;
- `privileged`;
- `network_mode: service:tailscale-app`;
- host networking.

## Serviços que devem receber env

Propagar `PLAYWRIGHT_PROXY_SERVER=${PLAYWRIGHT_PROXY_SERVER:-}` para serviços que
executam ou podem disparar Playwright no dev, especialmente `web` e `worker`.
Não alterar `compose.prod.yml`.

## Validação

Execute no mínimo:

```bash
docker compose --env-file .env -f compose.yml -f compose.dev.yml config
./scripts/test-in-container.sh check
```

Se `TS_AUTHKEY` estiver disponível no ambiente local, executar smoke de
conectividade documentado ou equivalente, sem login e sem persistir resposta real
no repositório.

## Relatório obrigatório

Gerar `/tmp/sirhosp-slice-S3-report.md`.

Pare ao final do slice.
